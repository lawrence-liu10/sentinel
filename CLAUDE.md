# Sentinel — Project Context

Autonomous SRE incident-response agent: watches a Dockerized microservices app on EC2 through a
self-hosted Prometheus/Grafana/Loki/Tempo stack, diagnoses injected faults via a hand-rolled
tool-use loop (LiteLLM → Bedrock/Anthropic), retrieves runbooks from pgvector, and remediates via
Ansible under **tiered autonomy** (read-only → low-risk auto → high-risk human approval).

## Phase tracker

| Phase | Scope | Status |
|---|---|---|
| 0 | Foundations (state backend, budget, CI) | ✅ done |
| 1 | Terraform fleet + app deploy | not started |
| 2 | LGTM observability | not started |
| 3 | Faults + remediation playbooks | not started |
| 4 | Agent core | not started |
| 5 | RAG | not started |
| 6 | Evals | not started |
| 7 | Dashboard + Slack HITL | not started |
| 8 | Ship | not started |

Update this table when a phase's acceptance criteria pass. Work one phase at a time.

## Session protocol

1. Read `docs/plans/00-overview.md` + the current phase file before touching anything.
2. Contract changes go to `docs/plans/01-contracts.md` **first**, then code.
3. `make up` only when live infra is needed; **always `make down` before ending a session** (budget cap $25/mo).
4. Verify: acceptance criteria in the phase file are the definition of done — run them, don't assume.

## Git workflow (hard rules)

- Claude **stages only**; the user runs all `git commit` / `git push`.
- **Never stage documentation** — no `docs/`, no `runbooks/`, no generated reports. The only doc
  allowed in commits is this `CLAUDE.md`. (README in Phase 8: ask first.)
- Verify `git rev-parse --show-toplevel` ends in `/sentinel` before staging (a stray repo exists at `~`).

## Monorepo layout

```
infra/       Terraform (remote state: S3 + DynamoDB lock; bootstrap stack separate)
ansible/     roles + playbooks: app deploy, LGTM stack, remediation actions
app/         4 FastAPI services: api-gateway, orders-service, payments-service, checkout-worker
agent/       Sentinel: loop, skills, risk classifier, approvals, FastAPI API (:8080)
faults/      injection harness (5-fault catalog — ground truth for evals)
evals/       live + replay harness, scoring, fixtures (fixtures gitignored)
dashboard/   TypeScript (Vite + React) system-of-record UI (:3001)
runbooks/    RAG corpus: runbooks, postmortems, service docs (data, kept untracked)
litellm/     gateway config (Bedrock primary, Anthropic failover) (:4000)
docs/        plans + writeups — local-only
```

## Commands

```bash
make up / make down        # start/stop EC2 fleet by Project=sentinel tag — down after EVERY session
make fault F=<label>       # inject fault
make evals-replay          # full eval suite, no AWS needed (what CI runs)
make evals-live            # eval against the live fleet, records fixtures
make demo                  # scripted chaos demo
uv run pytest              # in agent/ or evals/
npm run build && npm test  # in dashboard/
terraform plan             # in infra/ (state in S3, never local)
```

## Safety invariants (non-negotiable — the project's core claim)

1. Risk tier is **computed in code** (`agent/sentinel/risk.py` lookup), never taken from LLM output; unknown playbook ⇒ `high`.
2. High-risk actions **never** execute without an `approvals` row; the gate is unbypassable by prompt content — keep the adversarial tests proving this.
3. `run_playbook` defaults `dry_run=True`; every action reversible or gated.
4. Every LLM turn and tool call lands in `agent_steps` (audit trail = dashboard's reasoning trace).
5. Confidence < 0.7 ⇒ escalate to human, never act.
6. Secrets live only in SSM `/sentinel/*`; never in code, tfvars, logs, or tool output (`describe_service` returns env *names* only).

## Conventions

- Python 3.12 + FastAPI + `uv` + pytest (agent, services, evals); ruff for lint. TDD per superpowers.
- TypeScript dashboard is a pure client of the agent API (`docs/plans/01-contracts.md` §5) — no private backend paths.
- Terraform: AWS provider ~>5.x, `default_tags Project=sentinel`, us-east-1; no NAT (locked cost decision).
- Ansible: collections pinned in `ansible/requirements.yml`; inventory generated from Terraform output — never hand-edited.
- Pin LGTM/LiteLLM/model versions at the phase that installs them; record pins in `group_vars`.
- Alert names, fault labels, playbook names, and DB schema are **contracts** — change `01-contracts.md` first.
