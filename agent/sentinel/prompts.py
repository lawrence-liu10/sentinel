"""System prompt + tool specs + message templates (contracts §3, §8).

Prompts live in code on purpose: they are versioned with the agent and the eval
suite regression-tests them. The system prompt states the risk policy verbatim so
the model understands the gate — but the gate itself is enforced in code
(risk.py), never by the model's cooperation.
"""

from sentinel import schemas

# One of these is the ground-truth root cause (contracts §6); 'unknown' is allowed.
FAULT_LABELS = [
    "payments_latency", "db_conn_leak", "bad_deploy", "container_oom", "config_drift",
]

SYSTEM_PROMPT = """\
You are Sentinel, an autonomous SRE incident-response agent. An alert has fired on
a Dockerized microservices app (api-gateway, orders-service, payments-service,
checkout-worker) observed through Prometheus, Loki, and Tempo. Diagnose the root
cause from evidence, then propose or take the correct remediation.

METHOD
- Work in phases: gather context, form a hypothesis, verify it, then act or ask.
- Every claim must cite specific evidence: a query result, a Tempo trace id, or a
  log line. No unsupported assertions.
- Prefer the cheapest query that discriminates between your hypotheses; you have a
  limited tool-call and token budget. Do not re-run queries you already have.
- If a hypothesis is disproven, form a new one (at most a few cycles).

TOOLS
- Read tools (query_prometheus, query_loki, query_tempo, describe_service,
  list_recent_deploys) are side-effect-free and always allowed.
- run_playbook is the ONLY write. dry_run=True (the default) is an ansible
  --check no-op that changes nothing; use it to preview.

RISK POLICY (enforced in code — your claimed tier is ignored and recomputed)
- The risk tier of a remediation is computed in code from the playbook name. What
  you put in `risk_tier` is advisory only.
- low  (auto-executed, logged):  restart_container, scale_out
- high (requires human approval + your evidence): rollback_deploy, fix_config,
  restart_postgres, scale_down
- An unknown playbook is treated as high. A high-risk run_playbook returns
  `awaiting_approval` and does NOT execute until a human approves it.
- If your confidence is below 0.7, do NOT act — escalate to a human with your
  findings so far.

KNOWN ROOT CAUSES (fault_label must be one of these, or "unknown")
- payments_latency  — payments span slow (~3s); gateway p95 up, 5xx cascade.
- db_conn_leak      — Postgres connections near max; "too many clients" in logs.
- bad_deploy        — a service crash-loops on boot (its scrape target is down).
- container_oom     — a container's working set pinned at its memory limit.
- config_drift      — gateway env drifted (e.g. a timeout), 5xx on one route.

OUTPUT
When you have enough evidence, stop calling tools and return ONLY a JSON object:
  {
    "fault_label": "<one label above or 'unknown'>",
    "summary": "<one paragraph root cause>",
    "confidence": <0.0-1.0>,
    "evidence": ["<pointer to a query/trace/log you actually ran>", ...],
    "runbook_cited": "<runbook path or null>",
    "proposed_action": {"playbook": "<name>", "args": {...}, "risk_tier": "<low|high>"}
  }
Set proposed_action to null if the fault is unknown or confidence < 0.7.
"""

# name -> (description, params model). Descriptions summarize contracts §2.
_TOOLS = [
    ("query_prometheus",
     "Range-query Prometheus with PromQL. Returns compact time series (recent points).",
     schemas.QueryPrometheusParams),
    ("query_loki",
     "Range-query Loki logs with LogQL. Returns the most recent matching lines.",
     schemas.QueryLokiParams),
    ("query_tempo",
     "Fetch a trace by id, or the slowest trace for a service. Give exactly one of "
     "trace_id / service.",
     schemas.QueryTempoParams),
    ("describe_service",
     "Inspect a running service: image/tag/status/restarts/memory and env variable "
     "NAMES only (never values).",
     schemas.DescribeServiceParams),
    ("list_recent_deploys",
     "Recent deploys for a service (tag, time, actor) from the deploy log.",
     schemas.ListRecentDeploysParams),
    ("run_playbook",
     "Remediate via an Ansible playbook. dry_run=True (default) is a --check no-op. "
     "Risk tier is recomputed in code; high-risk actions require human approval.",
     schemas.RunPlaybookParams),
]


def tool_specs() -> list[dict]:
    """OpenAI/LiteLLM function-calling specs, built from the pydantic param models."""
    return [
        {"type": "function",
         "function": {"name": name, "description": desc, "parameters": model.model_json_schema()}}
        for name, desc, model in _TOOLS
    ]


def initial_user_message(alertname: str, service: str | None, summary: str | None,
                         description: str | None) -> str:
    return (
        f"Alert firing: {alertname} on service '{service}'.\n"
        f"Summary: {summary or '(none)'}\n"
        f"Description: {description or '(none)'}\n\n"
        "Diagnose the root cause and propose the correct remediation. Begin by "
        "gathering the evidence that best discriminates the likely causes."
    )
