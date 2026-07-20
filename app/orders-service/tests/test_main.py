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


def test_conn_leak_holds_most_of_the_pool_leaving_headroom(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    main._leaked_conns.clear()

    # One fake connection type: it answers `SHOW max_connections` (for the sizing
    # query) and is otherwise just held. Every connect succeeds, so the loop stops
    # at the headroom target, not on refusal.
    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def cursor(self):
            return self

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return ("20",)  # max_connections

    monkeypatch.setattr(main.psycopg, "connect", lambda dsn: _FakeConn())

    r = client.post("/admin/fault", json={"type": "conn_leak"})
    assert r.status_code == 200
    body = r.json()
    assert body["max_conns"] == 20
    # Holds max - headroom so the DB is near exhaustion but the exporter can still
    # scrape it (otherwise the metric vanishes exactly when the alert needs it).
    assert body["leaked"] == 20 - main.CONN_LEAK_HEADROOM
    assert len(main._leaked_conns) == 20 - main.CONN_LEAK_HEADROOM


# The /orders happy path needs Postgres + payments-service, so it is covered by
# the Phase 1 live acceptance criteria (real cross-service call), not a unit test.
