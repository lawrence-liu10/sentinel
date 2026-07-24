"""Skill (tool) tests. HTTP skills are exercised against mocked Prometheus/Loki/
Tempo; describe_service and run_playbook use injected runners so no real SSH or
ansible runs. The run_playbook cases are the safety core: a high-risk action with
dry_run=False must be gated (never executed) purely on the code-computed tier —
whatever the caller claims."""

import json

import httpx
import pytest
import respx

from sentinel import schemas
from sentinel.skills import Skills, SkillConfig
from tests.fakes import InMemoryStore

CFG = SkillConfig(
    prom_url="http://mon:9090", loki_url="http://mon:3100", tempo_url="http://mon:3200",
    service_hosts={"payments-service": "app-2", "checkout-worker": "app-2"},
    ssh_user="ubuntu", ssh_key_path="/k",
)


def _skills(store=None, run_ssh=None, run_ansible=None) -> Skills:
    return Skills(CFG, store or InMemoryStore(), run_ssh=run_ssh, run_ansible=run_ansible)


@respx.mock
def test_query_prometheus_parses_and_truncates():
    respx.get("http://mon:9090/api/v1/query_range").mock(return_value=httpx.Response(200, json={
        "status": "success",
        "data": {"resultType": "matrix", "result": [
            {"metric": {"service": "api-gateway"}, "values": [[i, str(i)] for i in range(50)]}
        ]},
    }))
    out = _skills().query_prometheus(schemas.QueryPrometheusParams(promql="up"))
    assert out["status"] == "success"
    assert out["series"][0]["metric"]["service"] == "api-gateway"
    # values truncated to the most recent points (context economy), keeping the tail.
    assert len(out["series"][0]["values"]) <= 20
    assert out["series"][0]["values"][-1] == [49, "49"]


@respx.mock
def test_query_loki_tails_lines():
    respx.get("http://mon:3100/loki/api/v1/query_range").mock(return_value=httpx.Response(200, json={
        "status": "success",
        "data": {"resultType": "streams", "result": [
            {"stream": {"level": "error"}, "values": [["100", "boom"], ["101", "kaboom"]]}
        ]},
    }))
    out = _skills().query_loki(schemas.QueryLokiParams(logql='{app="orders"}'))
    assert out["streams"][0]["labels"] == {"level": "error"}
    assert out["streams"][0]["lines"][-1] == ["101", "kaboom"]


@respx.mock
def test_query_tempo_by_trace_id_parses_spans():
    respx.get("http://mon:3200/api/traces/abc").mock(return_value=httpx.Response(200, json={
        "batches": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payments-service"}}]},
            "scopeSpans": [{"spans": [
                {"name": "charge", "durationNano": "3000000000", "status": {"code": 2}}
            ]}],
        }]
    }))
    out = _skills().query_tempo(schemas.QueryTempoParams(trace_id="abc"))
    span = out["traces"][0]["spans"][0]
    assert span["service"] == "payments-service"
    assert span["operation"] == "charge"
    assert span["duration_ms"] == 3000


def test_describe_service_returns_env_names_only():
    inspect = [{
        "Name": "/sentinel-payments-service",
        "Config": {"Image": "ghcr.io/x/sentinel-payments-service:v7",
                   "Env": ["REQUIRED_SETTING=ok", "PG_PASSWORD=hunter2", "OTEL_ENDPOINT=mon:4317"]},
        "State": {"Status": "running", "RestartCount": 2, "StartedAt": "2026-07-20T00:00:00Z"},
        "HostConfig": {"Memory": 268435456},
        "NetworkSettings": {"Ports": {"8000/tcp": [{"HostPort": "8002"}]}},
    }]
    captured = {}

    def fake_ssh(host, argv):
        captured["host"] = host
        return json.dumps(inspect)

    out = _skills(run_ssh=fake_ssh).describe_service(
        schemas.DescribeServiceParams(name="payments-service"))
    assert captured["host"] == "app-2"
    assert out["env_names"] == ["REQUIRED_SETTING", "PG_PASSWORD", "OTEL_ENDPOINT"]
    assert out["memory_limit_mb"] == 256
    # No secret VALUES anywhere in the serialized result.
    assert "hunter2" not in json.dumps(out)


def test_list_recent_deploys_reads_store():
    store = InMemoryStore()
    store.add_deploy("payments-service", "v6", "ansible")
    store.add_deploy("payments-service", "v7", "ansible")
    out = _skills(store=store).list_recent_deploys(
        schemas.ListRecentDeploysParams(service="payments-service"))
    assert [d["tag"] for d in out["deploys"]] == ["v7", "v6"]


def test_run_playbook_dry_run_maps_to_check():
    calls = []

    def fake_ansible(name, args, check):
        calls.append((name, check))
        return (0, False, "check ok")

    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "HighLatencyP95", "api-gateway", "warning")
    out = _skills(store=store, run_ansible=fake_ansible).run_playbook(
        inc, schemas.RunPlaybookParams(name="fix_config", args={"service": "api-gateway"}))
    assert calls == [("fix_config", True)]  # dry_run=True default -> --check
    assert out["status"] == "checked"
    assert out["risk_tier"] == "high"


def test_run_playbook_high_risk_real_is_gated_not_executed():
    # The adversarial safety test: even asked to really run a high-risk playbook,
    # nothing executes without an approval row — tier is computed in code.
    ran = []

    def fake_ansible(name, args, check):
        ran.append(name)
        return (0, True, "")

    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "ContainerRestartLoop", "payments-service", "critical")
    out = _skills(store=store, run_ansible=fake_ansible).run_playbook(
        inc, schemas.RunPlaybookParams(name="rollback_deploy",
                                       args={"service": "payments-service"}, dry_run=False))
    assert ran == []  # never executed
    assert out["status"] == "awaiting_approval"
    assert out["risk_tier"] == "high"
    action = store.get_action(out["action_id"])
    assert action["status"] == "awaiting_approval"


def test_run_playbook_low_risk_real_executes():
    ran = []

    def fake_ansible(name, args, check):
        ran.append((name, check))
        return (0, True, "restarted")

    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "PostgresConnExhaustion", "orders-service", "critical")
    out = _skills(store=store, run_ansible=fake_ansible).run_playbook(
        inc, schemas.RunPlaybookParams(name="restart_container",
                                       args={"service": "orders-service"}, dry_run=False))
    assert ran == [("restart_container", False)]
    assert out["status"] == "executed"
    assert out["risk_tier"] == "low"
    assert store.get_action(out["action_id"])["status"] == "executed"


def test_execute_approved_refuses_without_an_approval_row():
    # The unbypassable half of the gate: a parked high-risk action executes only
    # once an approval row exists — never before.
    ran = []

    def fake_ansible(name, args, check):
        ran.append(name)
        return (0, True, "")

    store = InMemoryStore()
    inc, _ = store.upsert_incident("gk", "ContainerRestartLoop", "payments-service", "critical")
    sk = _skills(store=store, run_ansible=fake_ansible)
    action_id = sk.run_playbook(
        inc, schemas.RunPlaybookParams(name="rollback_deploy",
                                       args={"service": "payments-service"},
                                       dry_run=False))["action_id"]

    with pytest.raises(PermissionError):
        sk.execute_approved(action_id)
    assert ran == []  # nothing ran without approval

    store.record_approval(action_id, "approved", "lawrence", "cli", None)
    out = sk.execute_approved(action_id)
    assert ran == ["rollback_deploy"]
    assert out["status"] == "executed"
