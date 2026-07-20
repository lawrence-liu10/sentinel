from fastapi.testclient import TestClient

import main

# Plain TestClient (no context manager) so the background poll loop stays off.
client = TestClient(main.app)


class _Cur:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._cur = _Cur(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def cursor(self):
        return self._cur


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200


def test_admin_fault_disabled_returns_403():
    r = client.post("/admin/fault", json={"type": "mem_hog"})
    assert r.status_code == 403


def test_admin_fault_unknown_type_returns_400(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    r = client.post("/admin/fault", json={"type": "bogus"})
    assert r.status_code == 400


def test_mem_hog_starts_allocator_and_returns_202(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    # Don't actually allocate until OOM inside the test process; just prove the
    # endpoint accepts the fault and spawns the allocator.
    started = {"hit": False}
    monkeypatch.setattr(main, "_hog_memory", lambda: started.__setitem__("hit", True))

    r = client.post("/admin/fault", json={"type": "mem_hog"})
    assert r.status_code == 202
    assert r.json()["status"] == "allocating"


def test_process_batch_counts_marked_rows(monkeypatch):
    monkeypatch.setattr(main.psycopg, "connect", lambda dsn: _Conn([(1,), (2,), (3,)]))
    assert main.process_batch() == 3
