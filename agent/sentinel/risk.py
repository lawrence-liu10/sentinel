"""Risk classifier — the safety kernel (contracts §3).

The tier of an action is decided *here in code*, keyed only on the playbook name.
Whatever tier the LLM claims in its diagnosis is advisory and never reaches this
module. An unrecognized playbook is high-risk by default (fail closed), so a new
or misspelled action can never be auto-executed.
"""

# playbook name -> tier. Reads are `read_only` and don't go through here; this
# table covers the write playbooks only.
_TIERS: dict[str, str] = {
    "restart_container": "low",
    "scale_out": "low",
    "rollback_deploy": "high",
    "fix_config": "high",
    "restart_postgres": "high",
    "scale_down": "high",
}


def _normalize(playbook: str) -> str:
    """Reduce a playbook reference to its bare name: strip any directory and the
    .yml/.yaml suffix, so 'playbooks/rollback_deploy.yml' == 'rollback_deploy'."""
    name = playbook.rsplit("/", 1)[-1]
    for suffix in (".yml", ".yaml"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def classify(playbook: str) -> str:
    """Return the risk tier for a playbook. Unknown ⇒ 'high' (fail closed)."""
    return _TIERS.get(_normalize(playbook), "high")


def requires_approval(playbook: str) -> bool:
    """True iff the action is high-risk and needs a human approval row first."""
    return classify(playbook) == "high"
