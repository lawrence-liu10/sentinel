"""checkout-worker — drains the outbox table.

A background loop marks unprocessed outbox rows as processed. A small FastAPI
sidecar (:8003) exposes health/admin so the fleet treats it like the others.

Env:
  DATABASE_URL     postgres DSN (default local).
  POLL_INTERVAL_S  seconds between outbox polls (default 5).
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException


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


log = setup_logging("checkout-worker")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel@localhost/sentinel")
POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "5"))


def process_batch() -> int:
    """Mark all unprocessed outbox rows processed; return how many."""
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("UPDATE outbox SET processed = true WHERE processed = false RETURNING id")
        return len(cur.fetchall())


async def _poll_loop() -> None:
    while True:
        try:
            n = process_batch()
            if n:
                log.info(f"processed {n} outbox rows")
        except Exception as e:
            log.error(f"outbox poll failed: {e}")
        await asyncio.sleep(POLL_INTERVAL_S)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_loop())
    yield
    task.cancel()


app = FastAPI(title="checkout-worker", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/admin/fault")
def admin_fault() -> None:
    raise HTTPException(status_code=501, detail="fault injection lands in Phase 3")
