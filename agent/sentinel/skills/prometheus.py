"""query_prometheus — range query, compacted for the LLM (contracts §2).

Series and per-series points are capped so a noisy query can't blow the token
budget; the most recent points (the ones that matter for a live incident) are
kept.
"""

import httpx

from sentinel import schemas

from ._window import window_range

_MAX_SERIES = 10
_MAX_POINTS = 20


def query(http: httpx.Client, base_url: str, p: schemas.QueryPrometheusParams) -> dict:
    start, end = window_range(p.window)
    r = http.get(
        f"{base_url}/api/v1/query_range",
        params={"query": p.promql, "start": start, "end": end, "step": p.step},
    )
    r.raise_for_status()
    body = r.json()
    data = body.get("data", {})
    series = [
        {"metric": s.get("metric", {}), "values": s.get("values", [])[-_MAX_POINTS:]}
        for s in data.get("result", [])[:_MAX_SERIES]
    ]
    return {"status": body.get("status", "success"), "series": series}
