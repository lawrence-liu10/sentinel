"""api-gateway — public entry point. Fronts the checkout flow.

Env:
  ORDERS_URL           base url of orders-service (default local).
  PAYMENTS_TIMEOUT_MS  client timeout for the downstream call, ms
                       (default 2000; fault F5 drifts this to 1 to force timeouts).
"""

import json
import logging
import os
import sys

import httpx
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


log = setup_logging("api-gateway")

ORDERS_URL = os.environ.get("ORDERS_URL", "http://localhost:8001")
PAYMENTS_TIMEOUT_MS = int(os.environ.get("PAYMENTS_TIMEOUT_MS", "2000"))

app = FastAPI(title="api-gateway")


class CheckoutRequest(BaseModel):
    item: str
    qty: int = 1


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/checkout")
def checkout(req: CheckoutRequest) -> dict:
    try:
        resp = httpx.post(
            f"{ORDERS_URL}/orders",
            json=req.model_dump(),
            timeout=PAYMENTS_TIMEOUT_MS / 1000,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.error(f"checkout failed: {e}")
        raise HTTPException(status_code=502, detail="checkout failed")
    return resp.json()


@app.post("/admin/fault")
def admin_fault() -> None:
    raise HTTPException(status_code=501, detail="fault injection lands in Phase 3")
