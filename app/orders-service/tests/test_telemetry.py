"""Tests for the shared telemetry module (app/common/telemetry.py).

Instrumentation is exercised through a real FastAPI app (the module's whole job
is to instrument one), so these are integration-level tests of real behavior.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace

from common.telemetry import current_trace_id, setup_telemetry


def _instrumented_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    setup_telemetry(app, "test-service")
    return app


def test_metrics_endpoint_exposes_request_counter():
    client = TestClient(_instrumented_app())
    client.get("/ping")
    # No redirect: Prometheus scrapes exactly /metrics, so it must answer 200
    # directly rather than 307 -> /metrics/.
    r = client.get("/metrics", follow_redirects=False)
    assert r.status_code == 200
    assert "http_requests_total" in r.text


def test_request_counter_is_labeled_by_service_and_route():
    client = TestClient(_instrumented_app())
    client.get("/ping")
    body = client.get("/metrics").text
    assert 'service="test-service"' in body
    assert 'route="/ping"' in body


def test_trace_id_is_valid_hex_inside_a_span():
    setup_telemetry(FastAPI(), "test-service")
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("op"):
        tid = current_trace_id()
    assert tid is not None
    assert len(tid) == 32


def test_trace_id_is_none_outside_any_span():
    assert current_trace_id() is None
