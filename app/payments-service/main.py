"""payments-service — charges an order. The leaf of the checkout chain.

Env:
  REQUIRED_SETTING   must be set or the process exits 1 on boot (fodder for fault F3).
  FAULT_LATENCY_MS   artificial delay before responding, ms (default 0; fault F1 sets 3000).
"""

import asyncio
import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from common.telemetry import setup_logging, setup_telemetry

log = setup_logging("payments-service")

# F3: a bad deploy ships without this env. Fail fast and loudly on boot so the
# container crash-loops (that's the observable signal the agent must diagnose).
# Empty counts as missing so the `-bad` image can be produced via a build arg.
if not os.environ.get("REQUIRED_SETTING"):
    log.critical("REQUIRED_SETTING is unset; refusing to start")
    sys.exit(1)

FAULT_LATENCY_MS = int(os.environ.get("FAULT_LATENCY_MS", "0"))

app = FastAPI(title="payments-service")
setup_telemetry(app, "payments-service")


class ChargeRequest(BaseModel):
    order_id: int
    amount: float


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/charge")
async def charge(req: ChargeRequest) -> dict:
    if FAULT_LATENCY_MS:
        await asyncio.sleep(FAULT_LATENCY_MS / 1000)
    log.info(f"charged order {req.order_id} amount {req.amount}")
    return {"status": "charged", "order_id": req.order_id}


@app.post("/admin/fault")
def admin_fault() -> None:
    raise HTTPException(status_code=501, detail="fault injection lands in Phase 3")
