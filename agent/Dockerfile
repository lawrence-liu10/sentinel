# Sentinel agent image — a CONTROL-PLANE image, unlike the app services. It bakes
# Ansible + the pinned collections + the remediation playbooks so the loop's
# run_playbook skill can shell `ansible-playbook` from inside the container
# (phase-4 gotcha). Deployed only to ctrl-1, with host networking so boto3 can
# reach IMDS for the instance-profile creds (Bedrock via LiteLLM, SSM lookups
# in group_vars). Build context is the REPO ROOT so it can COPY agent/ + ansible/.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv

# openssh-client: the describe_service skill SSHes to app hosts, and Ansible's
# default connection is ssh. No docker SDK here — community.docker runs its module
# on the remote app host, which already has it (Phase 1 docker role).
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Agent runtime deps — cached until pyproject/uv.lock change (same pattern as the
# app images). package=false, so the venv is deps only; source is copied below.
COPY agent/pyproject.toml agent/uv.lock ./
RUN uv sync --frozen --no-dev

# Ansible + boto3 into the same venv (deploy-time tools, deliberately kept out of
# the agent's pyproject): ansible-core drives the remediation playbooks; boto3
# backs the amazon.aws.aws_ssm lookups in group_vars (pg_password / database_url).
RUN uv pip install --python /app/.venv/bin/python "ansible-core>=2.18,<2.19" boto3

# Pinned collections, baked to /app/.collections (community.docker for the
# docker_container module that runs on app hosts, amazon.aws for the SSM lookups,
# community.postgresql for restart_postgres).
COPY ansible/requirements.yml ./ansible-requirements.yml
RUN /app/.venv/bin/ansible-galaxy collection install \
      -r ansible-requirements.yml -p /app/.collections

# The Ansible the loop executes: playbooks + roles + the group_vars that are the
# single source of truth for service topology/config. The generated inventory
# (per-fleet host IPs) and the SSH key are mounted read-only at runtime, never baked.
COPY ansible/playbooks/ ./ansible/playbooks/
COPY ansible/roles/ ./ansible/roles/
COPY ansible/inventory/group_vars/ ./ansible/inventory/group_vars/

# The agent itself (source + the schema it applies at deploy).
COPY agent/sentinel/ ./sentinel/
COPY agent/sql/ ./sql/

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Ansible config lives in env, not a cfg file, so the mounted inventory + key win
# cleanly. SSH_KEY_PATH is read by the describe_service skill; the ANSIBLE_* vars
# by ansible-playbook. Both point at the same read-only mounted key.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    AWS_REGION=us-east-1 \
    AWS_DEFAULT_REGION=us-east-1 \
    SENTINEL_ANSIBLE_DIR=/app/ansible \
    SSH_KEY_PATH=/keys/id_ed25519 \
    ANSIBLE_COLLECTIONS_PATH=/app/.collections \
    ANSIBLE_ROLES_PATH=/app/ansible/roles \
    ANSIBLE_INVENTORY=/app/ansible/inventory/hosts.yml \
    ANSIBLE_PRIVATE_KEY_FILE=/keys/id_ed25519 \
    ANSIBLE_REMOTE_USER=ubuntu \
    ANSIBLE_HOST_KEY_CHECKING=False \
    ANSIBLE_PIPELINING=True \
    ANSIBLE_BECOME=True \
    ANSIBLE_BECOME_METHOD=sudo

EXPOSE 8080
CMD ["uvicorn", "--factory", "sentinel.runtime:create_application", \
     "--host", "0.0.0.0", "--port", "8080"]
