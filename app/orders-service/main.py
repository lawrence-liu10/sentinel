"""orders-service — records an order and charges it via payments-service.

Env:
  DATABASE_URL         postgres DSN (default local).
  PAYMENTS_URL         base url of payments-service (default local).
  PAYMENTS_TIMEOUT_MS  client timeout for the charge call, ms (default 2000).
"""

import os

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.telemetry import setup_logging, setup_telemetry

log = setup_logging("orders-service")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel@localhost/sentinel")
PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://localhost:8002")
PAYMENTS_TIMEOUT_MS = int(os.environ.get("PAYMENTS_TIMEOUT_MS", "2000"))

app = FastAPI(title="orders-service")
setup_telemetry(app, "orders-service", instrument_httpx=True, instrument_psycopg=True)


class OrderRequest(BaseModel):
    item: str
    qty: int = 1


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/orders")
def create_order(req: OrderRequest) -> dict:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (item, qty, status, created_at) "
            "VALUES (%s, %s, 'pending', now()) RETURNING id",
            (req.item, req.qty),
        )
        order_id = cur.fetchone()[0]

    try:
        resp = httpx.post(
            f"{PAYMENTS_URL}/charge",
            json={"order_id": order_id, "amount": req.qty * 9.99},
            timeout=PAYMENTS_TIMEOUT_MS / 1000,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        _set_status(order_id, "failed")
        log.error(f"charge failed for order {order_id}: {e}")
        raise HTTPException(status_code=502, detail="payment failed")

    _set_status(order_id, "charged")
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO outbox (order_id, event, processed, created_at) "
            "VALUES (%s, 'order_placed', false, now())",
            (order_id,),
        )
    log.info(f"order {order_id} charged")
    return {"order_id": order_id, "status": "charged"}


def _set_status(order_id: int, status: str) -> None:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))


class FaultRequest(BaseModel):
    type: str


# Connections opened and deliberately never released (fault F2). Module-level so
# they outlive the request and keep occupying Postgres slots until the container
# restarts — which is exactly the correct remediation (restart_container).
_leaked_conns: list = []


@app.post("/admin/fault")
def admin_fault(req: FaultRequest) -> dict:
    if os.environ.get("FAULT_INJECTION_ENABLED") != "true":
        raise HTTPException(status_code=403, detail="fault injection disabled")
    if req.type == "conn_leak":
        return _leak_connections()
    raise HTTPException(status_code=400, detail=f"unknown fault type: {req.type}")


def _leak_connections(max_conns: int = 500) -> dict:
    """Open connections and never close them until Postgres refuses more, driving
    pg_stat_activity to max_connections (PostgresConnExhaustion). The safety cap
    just prevents an infinite loop against a DB with huge headroom; real
    exhaustion trips first."""
    while len(_leaked_conns) < max_conns:
        try:
            _leaked_conns.append(psycopg.connect(DATABASE_URL))
        except psycopg.OperationalError:
            break
    return {"type": "conn_leak", "leaked": len(_leaked_conns)}
