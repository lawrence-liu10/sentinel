"""query_tempo — fetch a trace by id, or find the slowest trace for a service and
return its spans (contracts §2). Exactly one selector is enforced by the schema.

Tempo's search/trace API shape is confirmed live at Stage B; parsing here is
defensive (OTLP-JSON: batches → scopeSpans → spans).
"""

import httpx

from sentinel import schemas

_NANO_PER_MS = 1_000_000


def query(http: httpx.Client, base_url: str, p: schemas.QueryTempoParams) -> dict:
    if p.trace_id:
        return {"traces": [_fetch_trace(http, base_url, p.trace_id)]}

    params = {"tags": f'service.name="{p.service}"'}
    if p.min_duration:
        params["minDuration"] = p.min_duration
    r = http.get(f"{base_url}/api/search", params=params)
    r.raise_for_status()
    found = r.json().get("traces", [])
    if not found:
        return {"traces": []}
    slowest = max(found, key=lambda t: float(t.get("durationMs", 0) or 0))
    return {"traces": [_fetch_trace(http, base_url, slowest.get("traceID"))]}


def _fetch_trace(http: httpx.Client, base_url: str, trace_id: str) -> dict:
    r = http.get(f"{base_url}/api/traces/{trace_id}")
    r.raise_for_status()
    body = r.json()
    spans: list[dict] = []
    duration_ms = 0
    for batch in body.get("batches", []):
        service = _resource_service(batch.get("resource", {}))
        for scope in batch.get("scopeSpans", []):
            for sp in scope.get("spans", []):
                dur = int(sp.get("durationNano", 0)) // _NANO_PER_MS
                duration_ms = max(duration_ms, dur)
                spans.append({
                    "service": service,
                    "operation": sp.get("name"),
                    "duration_ms": dur,
                    "status": _status(sp.get("status", {})),
                })
    return {"trace_id": trace_id, "duration_ms": duration_ms, "spans": spans}


def _resource_service(resource: dict) -> str | None:
    for attr in resource.get("attributes", []):
        if attr.get("key") == "service.name":
            return attr.get("value", {}).get("stringValue")
    return None


def _status(status: dict) -> str:
    # OTLP status code: 0 UNSET, 1 OK, 2 ERROR.
    return "error" if status.get("code") == 2 else "ok"
