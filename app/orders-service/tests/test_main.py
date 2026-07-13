from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200


def test_admin_fault_is_stubbed_501():
    r = client.post("/admin/fault")
    assert r.status_code == 501


# The /orders happy path needs Postgres + payments-service, so it is covered by
# the Phase 1 live acceptance criteria (real cross-service call), not a unit test.
