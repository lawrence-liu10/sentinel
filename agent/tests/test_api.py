"""API tests (contracts §5, §7). The acceptance point here is idempotency: a
duplicate Alertmanager webhook while an incident is active must attach to it, not
spawn a second incident and not re-launch the loop. The background runner is made
synchronous so launched work is observable."""

from fastapi.testclient import TestClient

from sentinel.api import create_app
from tests.fakes import InMemoryStore

WEBHOOK = {
    "version": "4",
    "groupKey": '{}:{alertname="HighLatencyP95", service="api-gateway"}',
    "status": "firing",
    "alerts": [{
        "fingerprint": "abc",
        "labels": {"alertname": "HighLatencyP95", "service": "api-gateway",
                   "severity": "warning"},
        "annotations": {"summary": "p95 high", "description": "p95 > 1s"},
        "startsAt": "2026-07-20T19:40:00Z",
    }],
}


class RecordingLoop:
    def __init__(self) -> None:
        self.ran: list[int] = []
        self.resumed: list[tuple[int, int]] = []

    def run_incident(self, incident_id: int) -> None:
        self.ran.append(incident_id)

    def resume_after_approval(self, incident_id: int, action_id: int) -> None:
        self.resumed.append((incident_id, action_id))


def _client(store=None, loop=None):
    store = store or InMemoryStore()
    loop = loop or RecordingLoop()
    app = create_app(store, loop, background=lambda fn, *a: fn(*a))  # run inline
    return TestClient(app), store, loop


def test_alert_creates_incident_and_launches_loop():
    client, store, loop = _client()
    r = client.post("/alerts", json=WEBHOOK)
    assert r.status_code == 200
    inc_id = r.json()["incident_id"]
    assert loop.ran == [inc_id]
    assert store.get_incident(inc_id)["alertname"] == "HighLatencyP95"


def test_duplicate_webhook_produces_exactly_one_incident():
    client, store, loop = _client()
    first = client.post("/alerts", json=WEBHOOK).json()["incident_id"]
    second = client.post("/alerts", json=WEBHOOK).json()
    assert second["incident_id"] == first
    assert second["created"] is False
    assert loop.ran == [first]             # launched once, not twice
    assert len(store.list_incidents()) == 1


def test_resolved_webhook_does_not_spawn_incident():
    client, store, loop = _client()
    r = client.post("/alerts", json={**WEBHOOK, "status": "resolved"})
    assert r.status_code == 200
    assert store.list_incidents() == []
    assert loop.ran == []


def test_incident_detail_and_steps_endpoints():
    client, store, loop = _client()
    inc_id = client.post("/alerts", json=WEBHOOK).json()["incident_id"]
    store.append_step(inc_id, phase="gather", tool_name="query_prometheus")
    assert client.get(f"/incidents/{inc_id}").json()["id"] == inc_id
    steps = client.get(f"/incidents/{inc_id}/steps").json()
    assert steps[-1]["tool_name"] == "query_prometheus"


def test_missing_incident_returns_404():
    client, _, _ = _client()
    assert client.get("/incidents/999").status_code == 404


def test_approvals_queue_and_approve_resumes_loop():
    client, store, loop = _client()
    inc, _ = store.upsert_incident("gk", "HighLatencyP95", "payments-service", "warning")
    action_id = store.create_action(inc, "fix_config", {"service": "payments-service"},
                                    "high", False, "awaiting_approval", "evidence")
    queue = client.get("/actions", params={"status": "awaiting_approval"}).json()
    assert [a["id"] for a in queue] == [action_id]

    r = client.post(f"/actions/{action_id}/approve",
                    json={"decided_by": "lawrence", "channel": "dashboard"})
    assert r.status_code == 200
    assert loop.resumed == [(inc, action_id)]


def test_approve_non_awaiting_action_conflicts():
    client, store, loop = _client()
    inc, _ = store.upsert_incident("gk", "X", "svc", "warning")
    action_id = store.create_action(inc, "restart_container", {}, "low", False, "executed")
    r = client.post(f"/actions/{action_id}/approve", json={"decided_by": "x"})
    assert r.status_code == 409


def test_healthz_and_metrics():
    client, _, _ = _client()
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/metrics").status_code == 200
