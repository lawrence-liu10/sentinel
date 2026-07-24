"""Persistence seam (contracts §4).

`Store` is the typed interface the agent depends on — the reasoning trace and the
audit trail live behind it. Two implementations satisfy it: `tests.fakes.InMemoryStore`
(unit tests / replay) and `PgStore` (psycopg; built + integration-tested at Stage B
against the real `sentinel` database, where its ON CONFLICT dedup can be exercised).

Keeping the loop/api coded against this Protocol is what lets the whole agent be
unit-tested with zero infrastructure.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Store(Protocol):
    # incidents — identity/dedup keyed on the Alertmanager groupKey (§7)
    def upsert_incident(self, group_key: str, alertname: str, service: str | None,
                        severity: str | None) -> tuple[int, bool]: ...
    def get_incident(self, incident_id: int) -> dict: ...
    def list_incidents(self) -> list[dict]: ...
    def find_active_incident(self, group_key: str) -> int | None: ...
    def set_status(self, incident_id: int, status: str) -> None: ...
    def set_diagnosis(self, incident_id: int, root_cause: str, confidence: float,
                      runbook_cited: str | None = None) -> None: ...
    def set_postmortem(self, incident_id: int, md: str) -> None: ...
    def resolve(self, incident_id: int) -> None: ...

    # agent_steps — every LLM turn + tool call (the audit log / dashboard data)
    def append_step(self, incident_id: int, phase: str, tool_name: str | None = None,
                    tool_args: dict | None = None, tool_result: dict | None = None,
                    reasoning: str | None = None, tokens_in: int = 0, tokens_out: int = 0,
                    latency_ms: int = 0) -> int: ...
    def get_steps(self, incident_id: int) -> list[dict]: ...

    # actions & approvals — the write path and its human gate
    def create_action(self, incident_id: int, playbook: str, args: dict, risk_tier: str,
                      dry_run: bool, status: str, evidence: str | None = None) -> int: ...
    def get_action(self, action_id: int) -> dict: ...
    def set_action_status(self, action_id: int, status: str,
                          result: dict | None = None) -> None: ...
    def list_actions(self, status: str | None = None) -> list[dict]: ...
    def record_approval(self, action_id: int, decision: str, decided_by: str,
                        channel: str, note: str | None = None) -> None: ...
    def get_approval(self, action_id: int) -> dict | None: ...

    # deploys — read side for the list_recent_deploys skill
    def list_deploys(self, service: str, limit: int = 5) -> list[dict]: ...


_ACTIVE = ("open", "diagnosing", "awaiting_approval", "remediating")


class PgStore:
    """psycopg implementation of `Store` against the `sentinel` database (§4).

    A short-lived autocommit connection per call keeps it thread-safe under the
    loop's background execution without a pool — the agent's incident throughput
    is low. Returns dict rows, matching the in-memory double.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _conn(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self._dsn, autocommit=True, row_factory=dict_row)

    # incidents -------------------------------------------------------------
    def upsert_incident(self, group_key, alertname, service, severity):
        import psycopg
        with self._conn() as c:
            found = c.execute(
                "SELECT id FROM incidents WHERE fingerprint=%s AND status = ANY(%s) "
                "ORDER BY id DESC LIMIT 1", (group_key, list(_ACTIVE))).fetchone()
            if found:
                return found["id"], False
            try:
                row = c.execute(
                    "INSERT INTO incidents (fingerprint, alertname, service, severity, status) "
                    "VALUES (%s,%s,%s,%s,'open') RETURNING id",
                    (group_key, alertname, service, severity)).fetchone()
                return row["id"], True
            except psycopg.errors.UniqueViolation:  # racing webhook won — attach
                row = c.execute(
                    "SELECT id FROM incidents WHERE fingerprint=%s AND status = ANY(%s) "
                    "ORDER BY id DESC LIMIT 1", (group_key, list(_ACTIVE))).fetchone()
                return row["id"], False

    def get_incident(self, incident_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM incidents WHERE id=%s", (incident_id,)).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return row

    def list_incidents(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()

    def find_active_incident(self, group_key):
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM incidents WHERE fingerprint=%s AND status = ANY(%s) "
                "ORDER BY id DESC LIMIT 1", (group_key, list(_ACTIVE))).fetchone()
        return row["id"] if row else None

    def set_status(self, incident_id, status):
        with self._conn() as c:
            c.execute("UPDATE incidents SET status=%s WHERE id=%s", (status, incident_id))

    def set_diagnosis(self, incident_id, root_cause, confidence, runbook_cited=None):
        with self._conn() as c:
            c.execute("UPDATE incidents SET root_cause=%s, confidence=%s, runbook_cited=%s "
                      "WHERE id=%s", (root_cause, confidence, runbook_cited, incident_id))

    def set_postmortem(self, incident_id, md):
        with self._conn() as c:
            c.execute("UPDATE incidents SET postmortem_md=%s WHERE id=%s", (md, incident_id))

    def resolve(self, incident_id):
        with self._conn() as c:
            c.execute("UPDATE incidents SET status='resolved', resolved_at=now() WHERE id=%s",
                      (incident_id,))

    # agent_steps -----------------------------------------------------------
    def append_step(self, incident_id, phase, tool_name=None, tool_args=None,
                    tool_result=None, reasoning=None, tokens_in=0, tokens_out=0, latency_ms=0):
        from psycopg.types.json import Jsonb
        with self._conn() as c:
            row = c.execute(
                "INSERT INTO agent_steps (incident_id, seq, phase, tool_name, tool_args, "
                "tool_result, reasoning, tokens_in, tokens_out, latency_ms) VALUES "
                "(%s, (SELECT COALESCE(MAX(seq),0)+1 FROM agent_steps WHERE incident_id=%s), "
                "%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq",
                (incident_id, incident_id, phase, tool_name,
                 Jsonb(tool_args) if tool_args is not None else None,
                 Jsonb(tool_result) if tool_result is not None else None,
                 reasoning, tokens_in, tokens_out, latency_ms)).fetchone()
        return row["seq"]

    def get_steps(self, incident_id):
        with self._conn() as c:
            return c.execute("SELECT * FROM agent_steps WHERE incident_id=%s ORDER BY seq",
                             (incident_id,)).fetchall()

    # actions & approvals ---------------------------------------------------
    def create_action(self, incident_id, playbook, args, risk_tier, dry_run, status,
                      evidence=None):
        from psycopg.types.json import Jsonb
        with self._conn() as c:
            row = c.execute(
                "INSERT INTO actions (incident_id, playbook, args, risk_tier, dry_run, status, "
                "evidence) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (incident_id, playbook, Jsonb(args), risk_tier, dry_run, status,
                 evidence)).fetchone()
        return row["id"]

    def get_action(self, action_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM actions WHERE id=%s", (action_id,)).fetchone()
        if row is None:
            raise KeyError(action_id)
        return row

    def set_action_status(self, action_id, status, result=None):
        from psycopg.types.json import Jsonb
        payload = Jsonb(result) if result is not None else None
        with self._conn() as c:
            if status == "executed":
                c.execute("UPDATE actions SET status=%s, result=%s, executed_at=now() WHERE id=%s",
                          (status, payload, action_id))
            else:
                c.execute("UPDATE actions SET status=%s, result=COALESCE(%s, result) WHERE id=%s",
                          (status, payload, action_id))

    def list_actions(self, status=None):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM actions WHERE (%s::text IS NULL OR status=%s) ORDER BY id",
                (status, status)).fetchall()

    def record_approval(self, action_id, decision, decided_by, channel, note=None):
        with self._conn() as c:
            c.execute("INSERT INTO approvals (action_id, decision, decided_by, channel, note) "
                      "VALUES (%s,%s,%s,%s,%s)", (action_id, decision, decided_by, channel, note))

    def get_approval(self, action_id):
        with self._conn() as c:
            return c.execute("SELECT * FROM approvals WHERE action_id=%s ORDER BY id DESC LIMIT 1",
                             (action_id,)).fetchone()

    # deploys ---------------------------------------------------------------
    def add_deploy(self, service, tag, actor):
        with self._conn() as c:
            c.execute("INSERT INTO deploys (service, tag, actor) VALUES (%s,%s,%s)",
                      (service, tag, actor))

    def list_deploys(self, service, limit=5):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM deploys WHERE service=%s ORDER BY deployed_at DESC, id DESC LIMIT %s",
                (service, limit)).fetchall()
