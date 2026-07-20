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
import time
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


# cgroup v2 surfaces the container's memory limit/usage here; None outside a
# limited cgroup-v2 container (e.g. a local run).
CGROUP_MEM_MAX = "/sys/fs/cgroup/memory.max"
CGROUP_MEM_CURRENT = "/sys/fs/cgroup/memory.current"
# Pin the working set here — above the 0.8 ContainerOOMKilled threshold, below
# the OOM line — so the pressure is observable rather than an instant kill.
HOG_TARGET_RATIO = 0.92
LOCAL_HOG_CAP_BYTES = 200 * 1024 * 1024

# Resident buffer for fault F4 (ContainerOOMKilled). Held, not grown to OOM:
# cAdvisor's OOM counter is stuck at 0 on cgroup v2, so we detect memory
# pressure instead — which needs the buffer to *stay* near the limit until
# restart_container (the correct remediation) clears it.
_mem_hog: list[bytes] = []


def _read_cgroup_int(path: str) -> int | None:
    """Read a single-integer cgroup file; None if absent or unlimited ("max")."""
    try:
        with open(path) as f:
            raw = f.read().strip()
    except OSError:
        return None
    return None if raw == "max" else int(raw)


def _hog_memory(chunk_mb: int = 5) -> None:
    """Grow a resident buffer until the container's memory usage sits near its
    cgroup limit (~92%), then hold. Runs in a background thread so the request
    returns before the allocation lands. Chunked with a short sleep so cAdvisor
    scrapes the climb; outside a limited cgroup (local run) it caps the buffer so
    it can't OOM the host."""
    limit = _read_cgroup_int(CGROUP_MEM_MAX)
    base = _read_cgroup_int(CGROUP_MEM_CURRENT) or 0
    buffer_cap = int(limit * HOG_TARGET_RATIO) - base if limit else LOCAL_HOG_CAP_BYTES
    chunk_bytes = chunk_mb * 1024 * 1024
    allocated = 0
    while allocated < buffer_cap:
        _mem_hog.append(b"\0" * chunk_bytes)
        allocated += chunk_bytes
        time.sleep(0.3)
    log.warning(f"mem_hog holding {allocated} bytes (cgroup limit {limit})")


@app.post("/admin/fault", status_code=202)
def admin_fault(req: FaultRequest) -> dict:
    if os.environ.get("FAULT_INJECTION_ENABLED") != "true":
        raise HTTPException(status_code=403, detail="fault injection disabled")
    if req.type == "mem_hog":
        threading.Thread(target=_hog_memory, daemon=True).start()
        return {"type": "mem_hog", "status": "allocating"}
    raise HTTPException(status_code=400, detail=f"unknown fault type: {req.type}")
