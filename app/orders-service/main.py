"""orders-service — records an order and charges it via payments-service.

Env:
  DATABASE_URL         postgres DSN (default local).
  PAYMENTS_URL         base url of payments-service (default local).
  PAYMENTS_TIMEOUT_MS  client timeout for the charge call, ms (default 2000).
"""

import json
import logging
import os
import sys

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "service": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging(name: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return logging.getLogger(name)


log = setup_logging("orders-service")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel@localhost/sentinel")
PAYMENTS_URL = os.environ.get("PAYMENTS_URL", "http://localhost:8002")
PAYMENTS_TIMEOUT_MS = int(os.environ.get("PAYMENTS_TIMEOUT_MS", "2000"))

app = FastAPI(title="orders-service")


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


@app.post("/admin/fault")
def admin_fault() -> None:
    raise HTTPException(status_code=501, detail="fault injection lands in Phase 3")
