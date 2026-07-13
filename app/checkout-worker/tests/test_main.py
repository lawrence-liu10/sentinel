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


def test_admin_fault_is_stubbed_501():
    r = client.post("/admin/fault")
    assert r.status_code == 501


def test_process_batch_counts_marked_rows(monkeypatch):
    monkeypatch.setattr(main.psycopg, "connect", lambda dsn: _Conn([(1,), (2,), (3,)]))
    assert main.process_batch() == 3
