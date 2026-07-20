from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200


def test_admin_fault_disabled_returns_403():
    r = client.post("/admin/fault", json={"type": "conn_leak"})
    assert r.status_code == 403


def test_admin_fault_unknown_type_returns_400(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    r = client.post("/admin/fault", json={"type": "bogus"})
    assert r.status_code == 400


def test_conn_leak_holds_connections_until_postgres_refuses(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    main._leaked_conns.clear()

    opened = {"n": 0}

    def fake_connect(dsn):
        opened["n"] += 1
        if opened["n"] > 3:
            raise main.psycopg.OperationalError("FATAL: sorry, too many clients already")
        return object()

    monkeypatch.setattr(main.psycopg, "connect", fake_connect)

    r = client.post("/admin/fault", json={"type": "conn_leak"})
    assert r.status_code == 200
    assert r.json()["leaked"] == 3
    # The point of the fault: connections are held, never released.
    assert len(main._leaked_conns) == 3


# The /orders happy path needs Postgres + payments-service, so it is covered by
# the Phase 1 live acceptance criteria (real cross-service call), not a unit test.
