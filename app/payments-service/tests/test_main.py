from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_charge_returns_charged():
    r = client.post("/charge", json={"order_id": 1, "amount": 9.99})
    assert r.status_code == 200
    assert r.json() == {"status": "charged", "order_id": 1}


def test_admin_fault_is_stubbed_501():
    r = client.post("/admin/fault")
    assert r.status_code == 501
