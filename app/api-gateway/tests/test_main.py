from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200


def test_checkout_forwards_to_orders(monkeypatch):
    def fake_post(url, json, timeout):
        assert url.endswith("/orders")
        assert json == {"item": "book", "qty": 2}
        return _Resp({"order_id": 7, "status": "charged"})

    monkeypatch.setattr(main.httpx, "post", fake_post)
    r = client.post("/checkout", json={"item": "book", "qty": 2})
    assert r.status_code == 200
    assert r.json() == {"order_id": 7, "status": "charged"}


def test_admin_fault_is_stubbed_501():
    r = client.post("/admin/fault")
    assert r.status_code == 501
