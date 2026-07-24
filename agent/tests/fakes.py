"""Test doubles. InMemoryStore is a faithful, dependency-injected stand-in for
PgStore — it stores real state (not a mock), so loop/api tests exercise real
control flow without a Postgres. PgStore must honor the same contract; its
ON CONFLICT dedup is covered by the DATABASE_URL-gated integration test.
"""

from datetime import datetime, timezone

from sentinel.llm import LLMResponse, ToolCall

# Incident statuses during which a repeat webhook attaches instead of spawning a
# new incident (contracts §7).
ACTIVE_STATUSES = {"open", "diagnosing", "awaiting_approval", "remediating"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryStore:
    def __init__(self) -> None:
        self._incidents: dict[int, dict] = {}
        self._steps: dict[int, list[dict]] = {}
        self._actions: dict[int, dict] = {}
        self._approvals: list[dict] = []
        self._deploys: list[dict] = []
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    # --- incidents -----------------------------------------------------------
    def upsert_incident(self, group_key: str, alertname: str, service: str | None,
                        severity: str | None) -> tuple[int, bool]:
        for inc in self._incidents.values():
            if inc["fingerprint"] == group_key and inc["status"] in ACTIVE_STATUSES:
                return inc["id"], False
        inc_id = self._next()
        self._incidents[inc_id] = {
            "id": inc_id, "fingerprint": group_key, "alertname": alertname,
            "service": service, "severity": severity, "status": "open",
            "root_cause": None, "confidence": None, "runbook_cited": None,
            "postmortem_md": None, "created_at": _now(), "resolved_at": None,
        }
        self._steps[inc_id] = []
        return inc_id, True

    def get_incident(self, incident_id: int) -> dict:
        return self._incidents[incident_id]

    def list_incidents(self) -> list[dict]:
        return sorted(self._incidents.values(), key=lambda i: i["id"], reverse=True)

    def find_active_incident(self, group_key: str) -> int | None:
        for inc in self._incidents.values():
            if inc["fingerprint"] == group_key and inc["status"] in ACTIVE_STATUSES:
                return inc["id"]
        return None

    def set_status(self, incident_id: int, status: str) -> None:
        self._incidents[incident_id]["status"] = status

    def set_diagnosis(self, incident_id: int, root_cause: str, confidence: float,
                      runbook_cited: str | None = None) -> None:
        inc = self._incidents[incident_id]
        inc.update(root_cause=root_cause, confidence=confidence, runbook_cited=runbook_cited)

    def set_postmortem(self, incident_id: int, md: str) -> None:
        self._incidents[incident_id]["postmortem_md"] = md

    def resolve(self, incident_id: int) -> None:
        inc = self._incidents[incident_id]
        inc.update(status="resolved", resolved_at=_now())

    # --- agent_steps ---------------------------------------------------------
    def append_step(self, incident_id: int, phase: str, tool_name: str | None = None,
                    tool_args: dict | None = None, tool_result: dict | None = None,
                    reasoning: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
                    latency_ms: int = 0) -> int:
        steps = self._steps[incident_id]
        seq = len(steps) + 1
        steps.append({
            "id": self._next(), "incident_id": incident_id, "seq": seq, "phase": phase,
            "tool_name": tool_name, "tool_args": tool_args, "tool_result": tool_result,
            "reasoning": reasoning, "tokens_in": tokens_in, "tokens_out": tokens_out,
            "latency_ms": latency_ms, "created_at": _now(),
        })
        return seq

    def get_steps(self, incident_id: int) -> list[dict]:
        return sorted(self._steps[incident_id], key=lambda s: s["seq"])

    # --- actions & approvals -------------------------------------------------
    def create_action(self, incident_id: int, playbook: str, args: dict, risk_tier: str,
                      dry_run: bool, status: str, evidence: str | None = None) -> int:
        act_id = self._next()
        self._actions[act_id] = {
            "id": act_id, "incident_id": incident_id, "playbook": playbook, "args": args,
            "risk_tier": risk_tier, "dry_run": dry_run, "status": status,
            "evidence": evidence, "result": None,
            "requested_at": _now(), "executed_at": None,
        }
        return act_id

    def get_action(self, action_id: int) -> dict:
        return self._actions[action_id]

    def set_action_status(self, action_id: int, status: str, result: dict | None = None) -> None:
        act = self._actions[action_id]
        act["status"] = status
        if result is not None:
            act["result"] = result
        if status == "executed":
            act["executed_at"] = _now()

    def list_actions(self, status: str | None = None) -> list[dict]:
        acts = sorted(self._actions.values(), key=lambda a: a["id"])
        return [a for a in acts if status is None or a["status"] == status]

    def record_approval(self, action_id: int, decision: str, decided_by: str,
                        channel: str, note: str | None = None) -> None:
        self._approvals.append({
            "id": self._next(), "action_id": action_id, "decision": decision,
            "decided_by": decided_by, "channel": channel, "note": note, "created_at": _now(),
        })

    def get_approval(self, action_id: int) -> dict | None:
        for ap in self._approvals:
            if ap["action_id"] == action_id:
                return ap
        return None

    # --- deploys (read for the list_recent_deploys skill) --------------------
    def add_deploy(self, service: str, tag: str, actor: str) -> None:
        self._deploys.append({"service": service, "tag": tag, "actor": actor,
                              "deployed_at": _now()})

    def list_deploys(self, service: str, limit: int = 5) -> list[dict]:
        rows = [d for d in self._deploys if d["service"] == service]
        return sorted(rows, key=lambda d: d["deployed_at"], reverse=True)[:limit]


# --- LLM + HTTP doubles for loop tests --------------------------------------


class FakeLLM:
    """Returns a scripted sequence of LLMResponses (tool calls, then a final
    diagnosis, then a postmortem). Ignores the messages — the loop's control flow
    is what's under test, not the prompt content."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.i = 0
        self.seen: list[list[dict]] = []

    def complete(self, messages, tools=None, tool_choice="auto") -> LLMResponse:
        self.seen.append(messages)
        resp = self.script[self.i]
        self.i += 1
        return resp


def llm_tool_call(name: str, args: dict, call_id: str = "c1") -> LLMResponse:
    return LLMResponse(content=None, tool_calls=[ToolCall(call_id, name, args)],
                       tokens_in=100, tokens_out=10, latency_ms=1, model="test")


def llm_text(content: str) -> LLMResponse:
    """A turn with no tool calls — a final diagnosis JSON or a postmortem."""
    return LLMResponse(content=content, tool_calls=[], tokens_in=100, tokens_out=20,
                       latency_ms=1, model="test")


class _Resp:
    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return self._data

    def raise_for_status(self) -> None:
        pass


class FakeHttp:
    """Stub for the LGTM HTTP endpoints. Prometheus range queries return a canned
    matrix, except an ALERTS query (used by the loop's confirm step) returns empty
    — i.e. the alert has cleared."""

    def __init__(self, prom_result: list | None = None, alert_firing: bool = False) -> None:
        self.prom_result = prom_result if prom_result is not None else [
            {"metric": {"service": "x"}, "values": [[1, "1"]]}]
        self.alert_firing = alert_firing

    def get(self, url: str, params: dict | None = None) -> _Resp:
        params = params or {}
        if "query_range" in url:
            q = str(params.get("query", ""))
            if "ALERTS" in q:
                result = self.prom_result if self.alert_firing else []
            else:
                result = self.prom_result
            return _Resp({"status": "success", "data": {"resultType": "matrix", "result": result}})
        if "loki" in url:
            return _Resp({"status": "success", "data": {"result": []}})
        if "/api/search" in url:
            return _Resp({"traces": []})
        if "/api/traces/" in url:
            return _Resp({"batches": []})
        return _Resp({})
