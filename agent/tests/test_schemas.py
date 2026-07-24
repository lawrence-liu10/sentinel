"""Schema tests — the system-boundary contracts (Alertmanager in, LLM diagnosis
out, tool args). Malformed input must be rejected here, not deeper in the loop."""

import pytest
from pydantic import ValidationError

from sentinel import schemas

# A representative Alertmanager v4 webhook (contracts §7). Alertmanager also sends
# receiver/externalURL/commonLabels/etc. — the model must ignore those extras.
WEBHOOK = {
    "version": "4",
    "groupKey": '{}:{alertname="HighLatencyP95", service="api-gateway"}',
    "status": "firing",
    "receiver": "sentinel-agent",
    "commonLabels": {"alertname": "HighLatencyP95"},
    "alerts": [
        {
            "fingerprint": "abc123",
            "status": "firing",
            "labels": {
                "alertname": "HighLatencyP95",
                "service": "api-gateway",
                "severity": "warning",
            },
            "annotations": {"summary": "p95 high", "description": "p95 > 1s"},
            "startsAt": "2026-07-20T19:40:00Z",
            "generatorURL": "http://mon-1:9090/graph",
        }
    ],
}


def test_webhook_parses_and_extracts_identity():
    wh = schemas.AlertmanagerWebhook.model_validate(WEBHOOK)
    assert wh.groupKey == '{}:{alertname="HighLatencyP95", service="api-gateway"}'
    assert wh.status == "firing"
    assert wh.alerts[0].labels.alertname == "HighLatencyP95"
    assert wh.alerts[0].labels.service == "api-gateway"


def test_webhook_missing_groupkey_rejected():
    bad = {k: v for k, v in WEBHOOK.items() if k != "groupKey"}
    with pytest.raises(ValidationError):
        schemas.AlertmanagerWebhook.model_validate(bad)


def test_diagnosis_valid():
    d = schemas.Diagnosis.model_validate(
        {
            "fault_label": "payments_latency",
            "summary": "payments span is 3s",
            "confidence": 0.91,
            "evidence": ["tempo trace X", "p95 query Y"],
            "runbook_cited": "runbooks/high_latency.md",
            "proposed_action": {
                "playbook": "fix_config",
                "args": {"service": "payments-service"},
                "risk_tier": "high",
            },
        }
    )
    assert d.fault_label == "payments_latency"
    assert d.proposed_action.playbook == "fix_config"


def test_diagnosis_confidence_out_of_range_rejected():
    with pytest.raises(ValidationError):
        schemas.Diagnosis.model_validate(
            {"fault_label": "unknown", "summary": "?", "confidence": 1.5, "evidence": []}
        )


def test_diagnosis_allows_no_action_for_unknown():
    d = schemas.Diagnosis.model_validate(
        {"fault_label": "unknown", "summary": "cannot tell", "confidence": 0.3, "evidence": []}
    )
    assert d.proposed_action is None


def test_run_playbook_defaults_to_dry_run():
    # The single write tool must default to a no-op dry run (safety invariant).
    p = schemas.RunPlaybookParams(name="restart_container", args={"service": "orders-service"})
    assert p.dry_run is True


def test_tempo_requires_exactly_one_selector():
    assert schemas.QueryTempoParams(trace_id="abc").trace_id == "abc"
    assert schemas.QueryTempoParams(service="payments-service").service == "payments-service"
    with pytest.raises(ValidationError):
        schemas.QueryTempoParams()
    with pytest.raises(ValidationError):
        schemas.QueryTempoParams(trace_id="abc", service="payments-service")


def test_prometheus_params_defaults():
    p = schemas.QueryPrometheusParams(promql="up")
    assert (p.window, p.step) == ("15m", "1m")
