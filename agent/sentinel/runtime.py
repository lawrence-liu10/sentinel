"""Composition root — assembles the agent from environment config (Stage B deploy).

Everything above this module is dependency-injected and infra-free; this is the
one place that reads env and constructs the real PgStore, LiteLLM client, Skills,
and Loop. The Ansible `agent` role sets these vars and runs the API via
`uvicorn --factory sentinel.runtime:create_application`.

Env: DATABASE_URL, PROM_URL, LOKI_URL, TEMPO_URL, SENTINEL_SERVICE_HOSTS (JSON
service→host), SSH_USER (default ubuntu), SSH_KEY_PATH, LITELLM_BASE_URL,
LITELLM_API_KEY, SENTINEL_MODEL (default sentinel-agent).
"""

import json
import os

from sentinel.api import create_app
from sentinel.llm import LLM
from sentinel.loop import Loop
from sentinel.skills import SkillConfig, Skills
from sentinel.store import PgStore


def _skill_config() -> SkillConfig:
    return SkillConfig(
        prom_url=os.environ["PROM_URL"],
        loki_url=os.environ["LOKI_URL"],
        tempo_url=os.environ["TEMPO_URL"],
        service_hosts=json.loads(os.environ["SENTINEL_SERVICE_HOSTS"]),
        ssh_user=os.environ.get("SSH_USER", "ubuntu"),
        ssh_key_path=os.environ["SSH_KEY_PATH"],
    )


def _llm() -> LLM:
    return LLM(
        model=os.environ.get("SENTINEL_MODEL", "sentinel-agent"),
        base_url=os.environ.get("LITELLM_BASE_URL"),
        api_key=os.environ.get("LITELLM_API_KEY"),
    )


def build() -> tuple[PgStore, Skills, Loop]:
    store = PgStore(os.environ["DATABASE_URL"])
    skills = Skills(_skill_config(), store)
    return store, skills, Loop(_llm(), skills, store)


def build_approval_runtime() -> tuple[PgStore, Loop]:
    """(store, loop) for the approve CLI — resumes the parked loop on approval."""
    store, _, loop = build()
    return store, loop


def create_application():
    """FastAPI app factory for uvicorn --factory."""
    store, _, loop = build()
    return create_app(store, loop)
