"""query_loki — range query over logs, tailed to the most recent lines (§2)."""

import httpx

from sentinel import schemas

from ._window import window_range

_NS = 1_000_000_000


def query(http: httpx.Client, base_url: str, p: schemas.QueryLokiParams) -> dict:
    start, end = window_range(p.window)
    r = http.get(
        f"{base_url}/loki/api/v1/query_range",
        params={"query": p.logql, "start": start * _NS, "end": end * _NS, "limit": p.limit},
    )
    r.raise_for_status()
    data = r.json().get("data", {})
    streams = [
        {"labels": s.get("stream", {}), "lines": s.get("values", [])[-p.limit:]}
        for s in data.get("result", [])
    ]
    return {"streams": streams}
