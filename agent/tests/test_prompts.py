"""Prompt tests. Prompts live in code so evals can regression-test them; these
guard that the safety policy, the diagnosis schema, and the tool set can't be
silently dropped from what the model is told."""

from sentinel import prompts


def test_system_prompt_embeds_safety_policy():
    sp = prompts.SYSTEM_PROMPT
    assert "computed in code" in sp        # tier is not the model's to decide
    assert "0.7" in sp                      # confidence escalation threshold
    assert "run_playbook" in sp             # the one write tool
    assert "rollback_deploy" in sp and "fix_config" in sp  # named high-risk actions
    for key in ("fault_label", "confidence", "evidence", "proposed_action"):
        assert key in sp                    # required diagnosis schema keys


def test_system_prompt_lists_the_fault_labels():
    sp = prompts.SYSTEM_PROMPT
    for label in ("payments_latency", "db_conn_leak", "bad_deploy",
                  "container_oom", "config_drift"):
        assert label in sp


def test_tool_specs_cover_all_six_tools_with_params():
    specs = prompts.tool_specs()
    names = {s["function"]["name"] for s in specs}
    assert names == {
        "query_prometheus", "query_loki", "query_tempo",
        "describe_service", "list_recent_deploys", "run_playbook",
    }
    for s in specs:
        assert s["type"] == "function"
        assert "parameters" in s["function"]


def test_initial_user_message_describes_the_alert():
    msg = prompts.initial_user_message(
        alertname="HighLatencyP95", service="api-gateway",
        summary="p95 high", description="p95 > 1s",
    )
    assert "HighLatencyP95" in msg
    assert "api-gateway" in msg
