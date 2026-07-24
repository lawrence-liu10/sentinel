"""Approval-gate tests. Approving writes the approvals row and resumes the parked
loop; rejecting marks the action rejected and fails the incident without running
anything. Deciding on an action that isn't awaiting approval is an error."""

import pytest

from sentinel import approvals
from tests.fakes import InMemoryStore


class FakeLoop:
    def __init__(self) -> None:
        self.resumed: list[tuple[int, int]] = []

    def resume_after_approval(self, incident_id: int, action_id: int) -> None:
        self.resumed.append((incident_id, action_id))


def _awaiting(store) -> tuple[int, int]:
    inc, _ = store.upsert_incident("gk", "HighLatencyP95", "payments-service", "warning")
    action_id = store.create_action(inc, "fix_config", {"service": "payments-service"},
                                    "high", False, "awaiting_approval", "the evidence")
    return inc, action_id


def test_approve_records_row_and_resumes_loop():
    store, loop = InMemoryStore(), FakeLoop()
    inc, action_id = _awaiting(store)
    approvals.decide(store, loop, action_id, decision="approved",
                     decided_by="lawrence", channel="cli")
    assert store.get_approval(action_id)["decision"] == "approved"
    assert loop.resumed == [(inc, action_id)]


def test_reject_marks_rejected_fails_incident_and_does_not_resume():
    store, loop = InMemoryStore(), FakeLoop()
    inc, action_id = _awaiting(store)
    approvals.decide(store, loop, action_id, decision="rejected",
                     decided_by="lawrence", channel="cli", note="too risky")
    assert store.get_action(action_id)["status"] == "rejected"
    assert store.get_incident(inc)["status"] == "failed"
    assert loop.resumed == []


def test_decide_refuses_action_not_awaiting_approval():
    store, loop = InMemoryStore(), FakeLoop()
    inc, _ = store.upsert_incident("gk", "X", "svc", "warning")
    action_id = store.create_action(inc, "restart_container", {}, "low", False, "executed")
    with pytest.raises(ValueError):
        approvals.decide(store, loop, action_id, decision="approved",
                         decided_by="x", channel="cli")


def test_cli_main_approves_via_injected_runtime():
    store, loop = InMemoryStore(), FakeLoop()
    inc, action_id = _awaiting(store)
    approvals.main([str(action_id), "--approve", "--by", "lawrence"],
                   build_runtime=lambda: (store, loop))
    assert loop.resumed == [(inc, action_id)]
    assert store.get_approval(action_id)["decision"] == "approved"
