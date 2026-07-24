-- Sentinel agent-core tables (contracts §4). Applied to the `sentinel` database
-- at deploy (Ansible) and to a throwaway db in tests/CI. Idempotent.
-- documents/chunks (RAG, Phase 5) and eval_runs (Phase 6) are created by their
-- own phases. deploys is written by the app deploy playbook (Phase 1).

CREATE TABLE IF NOT EXISTS incidents (
    id            SERIAL PRIMARY KEY,
    fingerprint   TEXT NOT NULL,             -- Alertmanager groupKey
    alertname     TEXT NOT NULL,
    service       TEXT,
    severity      TEXT,
    status        TEXT NOT NULL DEFAULT 'open',
    root_cause    TEXT,
    confidence    REAL,
    runbook_cited TEXT,
    postmortem_md TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ
);

-- At most one ACTIVE incident per fingerprint (idempotency, §7). Resolved and
-- failed incidents are excluded, so a recurrence can open a fresh one.
CREATE UNIQUE INDEX IF NOT EXISTS incidents_active_fingerprint
    ON incidents (fingerprint)
    WHERE status IN ('open', 'diagnosing', 'awaiting_approval', 'remediating');

CREATE TABLE IF NOT EXISTS agent_steps (
    id          SERIAL PRIMARY KEY,
    incident_id INT NOT NULL REFERENCES incidents(id),
    seq         INT NOT NULL,
    phase       TEXT NOT NULL,
    tool_name   TEXT,
    tool_args   JSONB,
    tool_result JSONB,
    reasoning   TEXT,
    tokens_in   INT NOT NULL DEFAULT 0,
    tokens_out  INT NOT NULL DEFAULT 0,
    latency_ms  INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (incident_id, seq)
);

CREATE TABLE IF NOT EXISTS actions (
    id           SERIAL PRIMARY KEY,
    incident_id  INT NOT NULL REFERENCES incidents(id),
    playbook     TEXT NOT NULL,
    args         JSONB NOT NULL DEFAULT '{}',
    risk_tier    TEXT NOT NULL,
    dry_run      BOOLEAN NOT NULL,
    status       TEXT NOT NULL,
    evidence     TEXT,
    result       JSONB,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS approvals (
    id         SERIAL PRIMARY KEY,
    action_id  INT NOT NULL REFERENCES actions(id),
    decision   TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    channel    TEXT NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deploys (
    id          SERIAL PRIMARY KEY,
    service     TEXT NOT NULL,
    tag         TEXT NOT NULL,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT
);
