"""PgStore integration tests — the same Store contract as the in-memory double,
but against a real Postgres. Skipped unless DATABASE_URL is set (runs locally via
a throwaway docker pg, and in CI against a pg service)."""

import os
import re
from pathlib import Path

import pytest

DSN = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="DATABASE_URL not set (pg integration)")

SCHEMA = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text()


@pytest.fixture
def store():
    import psycopg

    from sentinel.store import PgStore
    with psycopg.connect(DSN, autocommit=True) as conn:
        # Strip -- comments before splitting (a comment may contain a ';').
        sql = re.sub(r"--[^\n]*", "", SCHEMA)
        for stmt in filter(str.strip, sql.split(";")):
            conn.execute(stmt)
        conn.execute("TRUNCATE approvals, actions, agent_steps, incidents, deploys "
                     "RESTART IDENTITY CASCADE")
    return PgStore(DSN)


def test_pg_satisfies_store_protocol(store):
    from sentinel.store import Store
    assert isinstance(store, Store)


def test_pg_upsert_dedups_while_active_and_recurs_after_resolve(store):
    first, c1 = store.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    again, c2 = store.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert (c1, c2) == (True, False)
    assert first == again                      # one active incident per groupKey

    store.resolve(first)
    third, c3 = store.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert c3 is True and third != first       # recurrence opens a fresh incident


def test_pg_append_step_increments_seq_and_persists_jsonb(store):
    inc, _ = store.upsert_incident("gk-1", "A", "svc", "warning")
    s1 = store.append_step(inc, phase="gather", tool_name="query_prometheus",
                           tool_args={"promql": "up"}, tool_result={"series": []}, tokens_in=10)
    s2 = store.append_step(inc, phase="verify", tool_name="query_tempo")
    assert (s1, s2) == (1, 2)
    steps = store.get_steps(inc)
    assert [s["seq"] for s in steps] == [1, 2]
    assert steps[0]["tool_args"] == {"promql": "up"}   # jsonb round-trips to dict


def test_pg_action_lifecycle_and_approvals(store):
    inc, _ = store.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    act = store.create_action(inc, "fix_config", {"service": "payments-service"},
                              "high", False, "awaiting_approval", "evidence text")
    assert [a["id"] for a in store.list_actions(status="awaiting_approval")] == [act]
    assert store.get_approval(act) is None

    store.record_approval(act, "approved", "lawrence", "cli", None)
    assert store.get_approval(act)["decision"] == "approved"
    store.set_action_status(act, "executed", {"rc": 0, "changed": True})
    assert store.get_action(act)["status"] == "executed"
    assert store.list_actions(status="awaiting_approval") == []


def test_pg_diagnosis_postmortem_and_find_active(store):
    inc, _ = store.upsert_incident("gk-1", "HighLatencyP95", "api-gateway", "warning")
    assert store.find_active_incident("gk-1") == inc
    store.set_diagnosis(inc, "payments_latency", 0.9, "runbooks/latency.md")
    store.set_postmortem(inc, "## Postmortem\nroot cause")
    row = store.get_incident(inc)
    assert row["root_cause"] == "payments_latency"
    assert abs(row["confidence"] - 0.9) < 1e-6
    assert row["postmortem_md"].startswith("## Postmortem")


def test_pg_list_deploys_orders_recent_first(store):
    store.add_deploy("payments-service", "v6", "ansible")
    store.add_deploy("payments-service", "v7", "ansible")
    assert [d["tag"] for d in store.list_deploys("payments-service")] == ["v7", "v6"]
