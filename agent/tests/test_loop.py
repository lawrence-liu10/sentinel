"""Loop state-machine tests. The real Skills run (so the risk gate is exercised
end-to-end); only external effects — the LLM, HTTP to LGTM, ansible, SSH — are
doubled. The loop must: auto-execute low-risk, PARK high-risk for approval and
resume only after one, and escalate on low confidence or budget exhaustion."""

import json

from sentinel.loop import Loop
from sentinel.skills import SkillConfig, Skills
from tests.fakes import FakeHttp, FakeLLM, InMemoryStore, llm_text, llm_tool_call

CFG = SkillConfig(
    prom_url="http://m:9090", loki_url="http://m:3100", tempo_url="http://m:3200",
    service_hosts={"orders-service": "app-1", "payments-service": "app-2"},
    ssh_user="u", ssh_key_path="/k",
)


def _skills(store, ansible_calls, http=None) -> Skills:
    def fake_ansible(name, args, check):
        ansible_calls.append((name, check))
        return (0, True, "ok")

    return Skills(CFG, store, http=http or FakeHttp(),
                  run_ssh=lambda h, a: "[]", run_ansible=fake_ansible)


def _diagnosis(fault, playbook, service, tier, confidence=0.9):
    return json.dumps({
        "fault_label": fault, "summary": f"{fault} detected", "confidence": confidence,
        "evidence": ["a query I ran"], "runbook_cited": None,
        "proposed_action": {"playbook": playbook, "args": {"service": service},
                            "risk_tier": tier},
    })


def _loop(llm, skills, store, **kw) -> Loop:
    return Loop(llm, skills, store, sleep=lambda s: None, **kw)


def test_low_risk_incident_auto_remediates_and_resolves():
    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "PostgresConnExhaustion", "orders-service", "critical")
    llm = FakeLLM([
        llm_tool_call("query_loki", {"logql": '{app="orders"}'}),
        llm_text(_diagnosis("db_conn_leak", "restart_container", "orders-service", "low")),
        llm_text("## Postmortem\nConnections maxed; restarted orders-service."),
    ])
    ansible = []
    _loop(llm, _skills(store, ansible), store).run_incident(inc)

    assert ansible == [("restart_container", False)]          # auto-executed, no human
    row = store.get_incident(inc)
    assert row["status"] == "resolved"
    assert row["root_cause"] == "db_conn_leak"
    assert row["postmortem_md"].startswith("## Postmortem")
    assert len(store.get_steps(inc)) >= 3                      # audit trail populated


def test_high_risk_incident_parks_then_resumes_after_approval():
    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "HighLatencyP95", "payments-service", "warning")
    llm = FakeLLM([
        llm_tool_call("query_tempo", {"service": "payments-service"}),
        llm_text(_diagnosis("payments_latency", "fix_config", "payments-service", "high", 0.92)),
    ])
    ansible = []
    skills = _skills(store, ansible)
    loop = _loop(llm, skills, store)
    loop.run_incident(inc)

    # Parked, NOT executed — code-computed high tier gates it.
    assert ansible == []
    assert store.get_incident(inc)["status"] == "awaiting_approval"
    pending = store.list_actions(status="awaiting_approval")
    assert len(pending) == 1
    action_id = pending[0]["id"]

    # Human approves; loop resumes and now executes + confirms + resolves.
    store.record_approval(action_id, "approved", "lawrence", "cli", None)
    llm.script.append(llm_text("## Postmortem\nFixed payments config."))
    loop.resume_after_approval(inc, action_id)

    assert ansible == [("fix_config", False)]
    assert store.get_incident(inc)["status"] == "resolved"


def test_low_confidence_escalates_without_acting():
    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "HighErrorRate", "api-gateway", "critical")
    unsure = json.dumps({"fault_label": "unknown", "summary": "unclear", "confidence": 0.4,
                         "evidence": [], "runbook_cited": None, "proposed_action": None})
    ansible = []
    _loop(FakeLLM([llm_text(unsure)]), _skills(store, ansible), store).run_incident(inc)

    assert ansible == []
    assert store.get_incident(inc)["status"] == "failed"


def test_tool_call_budget_exhaustion_escalates():
    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "HighLatencyP95", "api-gateway", "warning")
    # The model never finalizes — just keeps calling a read tool.
    llm = FakeLLM([llm_tool_call("query_prometheus", {"promql": "up"})] * 50)
    ansible = []
    _loop(llm, _skills(store, ansible), store, max_tool_calls=3).run_incident(inc)

    assert store.get_incident(inc)["status"] == "failed"
    # Never exceeded the budget.
    reads = [s for s in store.get_steps(inc) if s["tool_name"] == "query_prometheus"]
    assert len(reads) <= 3
