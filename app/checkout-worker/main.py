"""checkout-worker — drains the outbox table.

A background loop marks unprocessed outbox rows as processed. A small FastAPI
sidecar (:8003) exposes health/admin so the fleet treats it like the others.

Env:
  DATABASE_URL     postgres DSN (default local).
  POLL_INTERVAL_S  seconds between outbox polls (default 5).
"""

import asyncio
import os
import threading
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter
from pydantic import BaseModel

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


class FaultRequest(BaseModel):
    type: str


# Ever-growing buffer that drives the worker past its 256m container limit so the
# cgroup OOM-kills the process (fault F4 / ContainerOOMKilled). A restart clears
# it — the correct remediation (restart_container).
_mem_hog: list[bytes] = []


def _hog_memory(chunk_mb: int = 50) -> None:
    """Allocate until the container's memory limit kills the process. Runs in a
    background thread so the request returns before the OOM lands."""
    while True:
        _mem_hog.append(b"\0" * (chunk_mb * 1024 * 1024))


@app.post("/admin/fault", status_code=202)
def admin_fault(req: FaultRequest) -> dict:
    if os.environ.get("FAULT_INJECTION_ENABLED") != "true":
        raise HTTPException(status_code=403, detail="fault injection disabled")
    if req.type == "mem_hog":
        threading.Thread(target=_hog_memory, daemon=True).start()
        return {"type": "mem_hog", "status": "allocating"}
    raise HTTPException(status_code=400, detail=f"unknown fault type: {req.type}")
