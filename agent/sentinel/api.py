"""Agent HTTP API (contracts §5). Alertmanager posts alerts here; the dashboard
and (Phase 7) Slack are clients of these same endpoints — no private paths.

Idempotency (§7): an incident is keyed on the Alertmanager groupKey. A duplicate
webhook while the incident is active attaches a step; it never spawns a second
incident or re-launches the loop. The loop runs in the background so the webhook
returns immediately; the runner is injectable so tests observe it synchronously.
"""

import threading

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel

from sentinel import approvals, schemas

INCIDENTS_CREATED = Counter("sentinel_incidents_total", "Incidents created by Sentinel.")


class ApproveBody(BaseModel):
    decided_by: str
    channel: str = "dashboard"
    note: str | None = None


def _default_background(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def create_app(store, loop, *, background=None) -> FastAPI:
    bg = background or _default_background
    app = FastAPI(title="sentinel-agent")

    @app.post("/alerts")
    def ingest(wh: schemas.AlertmanagerWebhook):
        labels = wh.alerts[0].labels
        if wh.status == "resolved":
            # Recorded, not trusted: recovery is confirmed by the agent's own
            # metric re-query (the loop's confirm phase), not by this webhook.
            existing = store.find_active_incident(wh.groupKey)
            if existing is not None:
                store.append_step(existing, phase="confirm",
                                  reasoning="Alertmanager reports resolved; agent confirms via re-query")
            return {"status": "ok", "resolved": True}

        incident_id, created = store.upsert_incident(
            wh.groupKey, labels.alertname, labels.service, labels.severity)
        if created:
            INCIDENTS_CREATED.inc()
            bg(loop.run_incident, incident_id)
        else:
            store.append_step(incident_id, phase="gather",
                              reasoning="duplicate alert webhook attached to active incident")
        return {"incident_id": incident_id, "created": created}

    @app.get("/incidents")
    def list_incidents():
        return store.list_incidents()

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: int):
        try:
            return store.get_incident(incident_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="incident not found") from None

    @app.get("/incidents/{incident_id}/steps")
    def get_steps(incident_id: int):
        try:
            store.get_incident(incident_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="incident not found") from None
        return store.get_steps(incident_id)

    @app.get("/actions")
    def list_actions(status: str | None = None):
        return store.list_actions(status=status)

    @app.post("/actions/{action_id}/approve")
    def approve(action_id: int, body: ApproveBody):
        return _decide(action_id, "approved", body)

    @app.post("/actions/{action_id}/reject")
    def reject(action_id: int, body: ApproveBody):
        return _decide(action_id, "rejected", body)

    def _decide(action_id: int, decision: str, body: ApproveBody):
        try:
            action = store.get_action(action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="action not found") from None
        if action["status"] != "awaiting_approval":
            raise HTTPException(
                status_code=409,
                detail=f"action is {action['status']}, not awaiting approval")
        bg(lambda: approvals.decide(store, loop, action_id, decision=decision,
                                    decided_by=body.decided_by, channel=body.channel,
                                    note=body.note))
        return {"status": "accepted", "decision": decision}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app
