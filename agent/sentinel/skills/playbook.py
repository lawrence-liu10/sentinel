"""run_playbook — the ONLY write tool, and the safety gate (contracts §2, §3).

Risk is computed here by `risk.classify` on the playbook name; the caller's claimed
tier is irrelevant. A high-risk action with dry_run=False is recorded as
`awaiting_approval` and returns WITHOUT executing — the ansible runner is never
called until a human approval row exists. `dry_run=True` maps to `--check` and is
always allowed.
"""

from sentinel import risk, schemas

_OUTPUT_TAIL = 2000


def run(run_ansible, store, incident_id: int, p: schemas.RunPlaybookParams,
        evidence: str | None = None) -> dict:
    tier = risk.classify(p.name)

    if p.dry_run:
        action_id = store.create_action(incident_id, p.name, p.args, tier, True, "proposed",
                                         evidence)
        rc, changed, out = run_ansible(p.name, p.args, True)  # --check
        store.set_action_status(action_id, "proposed", {"rc": rc, "changed": changed})
        return _result(action_id, tier, "checked", rc, changed, out)

    if tier == "high":
        # Gate: recorded, parked, NOT executed. Resumes only via an approval row.
        action_id = store.create_action(incident_id, p.name, p.args, tier, False,
                                         "awaiting_approval", evidence)
        return _result(action_id, tier, "awaiting_approval", None, None, None)

    # Low risk: autonomous execution, logged.
    action_id = store.create_action(incident_id, p.name, p.args, tier, False, "proposed",
                                     evidence)
    rc, changed, out = run_ansible(p.name, p.args, False)
    status = "executed" if rc == 0 else "failed"
    store.set_action_status(action_id, status, {"rc": rc, "changed": changed})
    return _result(action_id, tier, status, rc, changed, out)


def execute_approved(run_ansible, store, action_id: int) -> dict:
    """Run a high-risk action that a human has approved. The approval row is the
    unbypassable precondition: no row (or a rejection) ⇒ refuse, never execute.
    This is the second half of the gate — run_playbook won't execute high-risk,
    and this won't run without the approval."""
    approval = store.get_approval(action_id)
    if not approval or approval.get("decision") != "approved":
        raise PermissionError(f"action {action_id} has no approval row")
    action = store.get_action(action_id)
    rc, changed, out = run_ansible(action["playbook"], action["args"], False)
    status = "executed" if rc == 0 else "failed"
    store.set_action_status(action_id, status, {"rc": rc, "changed": changed})
    return _result(action_id, action["risk_tier"], status, rc, changed, out)


def _result(action_id, tier, status, rc, changed, out) -> dict:
    return {
        "action_id": action_id, "risk_tier": tier, "status": status,
        "rc": rc, "changed": changed,
        "output_tail": out[-_OUTPUT_TAIL:] if out else None,
    }
