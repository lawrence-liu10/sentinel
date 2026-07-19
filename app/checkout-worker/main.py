"""checkout-worker — drains the outbox table.

A background loop marks unprocessed outbox rows as processed. A small FastAPI
sidecar (:8003) exposes health/admin so the fleet treats it like the others.

Env:
  DATABASE_URL     postgres DSN (default local).
  POLL_INTERVAL_S  seconds between outbox polls (default 5).
"""

import asyncio
import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter

from common.telemetry import setup_logging, setup_telemetry

log = setup_logging("checkout-worker")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://sentinel@localhost/sentinel")
POLL_INTERVAL_S = int(os.environ.get("POLL_INTERVAL_S", "5"))

# Outbox rows drained by the worker loop. Unlike the request-scoped metrics in
# common.telemetry, this counts background work, so it lives with the worker.
WORKER_JOBS = Counter(
    "worker_jobs_processed_total",
    "Total outbox rows processed by the worker loop.",
    ["service"],
)


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
                WORKER_JOBS.labels("checkout-worker").inc(n)
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
setup_telemetry(app, "checkout-worker", instrument_psycopg=True)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/admin/fault")
def admin_fault() -> None:
    raise HTTPException(status_code=501, detail="fault injection lands in Phase 3")
