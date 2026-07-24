"""Approval gate — the human decision on a parked high-risk action (§5, §8).

`decide` writes the approvals row and either resumes the loop (approve) or fails
the incident (reject). Resumption reloads state from the store, so it works whether
the decision arrives seconds or hours later, and across an agent restart. The
dashboard/Slack in Phase 7 call the same `decide`; the CLI here is the first channel.
"""

import argparse


def decide(store, loop, action_id: int, *, decision: str, decided_by: str,
           channel: str, note: str | None = None) -> None:
    action = store.get_action(action_id)
    if action["status"] != "awaiting_approval":
        raise ValueError(
            f"action {action_id} is not awaiting approval (status={action['status']})")
    store.record_approval(action_id, decision, decided_by, channel, note)
    if decision == "approved":
        loop.resume_after_approval(action["incident_id"], action_id)
    elif decision == "rejected":
        store.set_action_status(action_id, "rejected")
        store.set_status(action["incident_id"], "failed")
    else:
        raise ValueError(f"unknown decision: {decision}")


def _parse(argv):
    p = argparse.ArgumentParser(prog="sentinel.approve",
                                description="Approve or reject a parked high-risk action.")
    p.add_argument("action_id", type=int)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--reject", action="store_true")
    p.add_argument("--by", required=True, help="who is deciding")
    p.add_argument("--note", default=None)
    return p.parse_args(argv)


def _default_runtime():
    # Composition root (Store + Loop wired from env) — completed at Stage B deploy.
    from sentinel.runtime import build_approval_runtime

    return build_approval_runtime()


def main(argv=None, *, build_runtime=None) -> None:
    args = _parse(argv)
    store, loop = (build_runtime or _default_runtime)()
    decision = "approved" if args.approve else "rejected"
    decide(store, loop, args.action_id, decision=decision, decided_by=args.by,
           channel="cli", note=args.note)
    print(f"action {args.action_id} {decision} by {args.by}")
