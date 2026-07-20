"""Shared observability wiring for all four Sentinel services.

Three pillars, one import:
  * metrics  — prometheus-client counter + histogram, exposed at ``/metrics``.
  * traces   — OpenTelemetry auto-instrumentation (FastAPI + optionally httpx /
               psycopg). httpx instrumentation injects the W3C ``traceparent``
               header on outbound calls, which is what stitches a request into a
               single cross-host trace in Tempo.
  * logs     — JSON to stdout, with the active span's ``trace_id`` embedded so a
               log line can be pivoted to its trace (and vice-versa) in Grafana.

Export target: OTLP/gRPC to ``OTEL_EXPORTER_OTLP_ENDPOINT`` (e.g. mon-1:4317).
When that env var is unset (local dev, tests) spans are still created — so
trace_ids exist for log correlation — but nothing is exported over the network.
"""

import json
import logging
import os
import sys
import time

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Registered once at import (module-level) so a service's single process owns
# exactly one instance of each metric family.
_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled.",
    ["service", "route", "status"],
)
_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["service", "route"],
)


def current_trace_id() -> str | None:
    """Active span's trace id as 32-char hex, or None when outside any span."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


class _JsonFormatter(logging.Formatter):
    """One JSON object per line; carries trace_id for log<->trace correlation."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "service": self._service,
            "msg": record.getMessage(),
        }
        trace_id = current_trace_id()
        if trace_id is not None:
            entry["trace_id"] = trace_id
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(service: str) -> logging.Logger:
    """JSON logging to stdout for `service`; returns the service logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger(service)


def _init_tracing(service: str) -> None:
    # OTel forbids replacing an already-installed SDK provider (it warns and
    # ignores the second call). Guard so repeated setup (e.g. across tests) and
    # the single production call are both safe.
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def setup_telemetry(
    app: FastAPI,
    service: str,
    *,
    instrument_httpx: bool = False,
    instrument_psycopg: bool = False,
) -> None:
    """Wire metrics + traces onto `app`. Each service opts into only the
    client instrumentors it actually uses, so no image carries dead deps."""
    _init_tracing(service)
    FastAPIInstrumentor.instrument_app(app)

    if instrument_httpx:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    if instrument_psycopg:
        from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor

        PsycopgInstrumentor().instrument()

    @app.middleware("http")
    async def _record_metrics(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        _REQUESTS.labels(service, path, str(response.status_code)).inc()
        _LATENCY.labels(service, path).observe(time.perf_counter() - start)
        return response

    # A plain route (not a mounted sub-app) so Prometheus scrapes /metrics
    # directly with a 200 instead of a 307 redirect to /metrics/.
    @app.get("/metrics")
    def _metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
