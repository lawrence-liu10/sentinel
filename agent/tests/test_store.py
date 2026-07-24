"""Store contract tests, run against the in-memory double (the same contract the
psycopg PgStore must honor). The webhook-idempotency behavior here is the one the
Phase 4 acceptance calls out: a duplicate alert while an incident is active must
not spawn a second incident."""

from sentinel.store import Store
from tests.fakes import InMemoryStore


def _store() -> InMemoryStore:
    return InMemoryStore()


def test_inmemory_double_satisfies_store_protocol():
    # The double and the production PgStore must expose the same interface, so the
    # loop/api can be typed against Store and run on either.
    assert isinstance(InMemoryStore(), Store)


def test_upsert_creates_incident():
    s = _store()
    inc_id, created = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert created is True
    inc = s.get_incident(inc_id)
    assert inc["alertname"] == "HighLatencyP95"
    assert inc["service"] == "api-gateway"
    assert inc["status"] == "open"


def test_duplicate_while_active_returns_same_incident():
    s = _store()
    first, c1 = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    second, c2 = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert (c1, c2) == (True, False)
    assert first == second  # one incident, not two


def test_recurrence_after_resolve_creates_new_incident():
    s = _store()
    first, _ = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    s.resolve(first)
    third, created = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert created is True
    assert third != first


def test_append_step_increments_seq_per_incident():
    s = _store()
    inc, _ = s.upsert_incident("gk-1", "A", "svc", "warning")
    seq1 = s.append_step(inc, phase="gather", tool_name="query_prometheus", tokens_in=10)
    seq2 = s.append_step(inc, phase="verify", tool_name="query_tempo", tokens_in=20)
    assert (seq1, seq2) == (1, 2)
    steps = s.get_steps(inc)
    assert [st["seq"] for st in steps] == [1, 2]
    assert steps[0]["tool_name"] == "query_prometheus"


def test_action_lifecycle_and_approvals_queue():
    s = _store()
    inc, _ = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    act = s.create_action(
        inc, playbook="fix_config", args={"service": "payments-service"},
        risk_tier="high", dry_run=False, status="awaiting_approval",
        evidence="tempo shows 3s payments span",
    )
    assert [a["id"] for a in s.list_actions(status="awaiting_approval")] == [act]

    s.record_approval(act, decision="approved", decided_by="lawrence", channel="cli", note=None)
    s.set_action_status(act, status="executed", result={"rc": 0, "changed": True})
    assert s.get_action(act)["status"] == "executed"
    assert s.list_actions(status="awaiting_approval") == []


def test_diagnosis_and_postmortem_persist():
    s = _store()
    inc, _ = s.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    s.set_diagnosis(inc, root_cause="payments_latency", confidence=0.9,
                    runbook_cited="runbooks/high_latency.md")
    s.set_postmortem(inc, "## Postmortem\nroot cause: payments latency")
    inc_row = s.get_incident(inc)
    assert inc_row["root_cause"] == "payments_latency"
    assert inc_row["confidence"] == 0.9
    assert inc_row["postmortem_md"].startswith("## Postmortem")
