"""Risk classifier tests — the project's central safety claim: the tier is a
code lookup keyed on the playbook name, never anything the LLM says. Unknown
playbooks are treated as high-risk (fail closed)."""

import pytest

from sentinel import risk


@pytest.mark.parametrize(
    "playbook,tier",
    [
        ("restart_container", "low"),
        ("scale_out", "low"),
        ("rollback_deploy", "high"),
        ("fix_config", "high"),
        ("restart_postgres", "high"),
        ("scale_down", "high"),
    ],
)
def test_known_playbooks_map_to_expected_tier(playbook, tier):
    assert risk.classify(playbook) == tier


def test_unknown_playbook_is_high():
    # Fail closed — an unrecognized action is never auto-executed.
    assert risk.classify("delete_everything") == "high"


def test_classify_normalizes_yml_suffix_and_path():
    assert risk.classify("rollback_deploy.yml") == "high"
    assert risk.classify("playbooks/restart_container.yml") == "low"


def test_requires_approval_true_only_for_high():
    assert risk.requires_approval("rollback_deploy") is True
    assert risk.requires_approval("restart_container") is False
    assert risk.requires_approval("scale_out") is False
    # Unknown ⇒ high ⇒ needs approval.
    assert risk.requires_approval("something_new") is True
