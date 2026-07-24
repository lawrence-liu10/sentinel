"""Runtime composition-root tests. Wiring only — PgStore and the LLM connect
lazily, so this runs with no database or gateway. Confirms env is parsed into the
components the CLI and the API entrypoint use."""

import pytest


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv("PROM_URL", "http://m:9090")
    monkeypatch.setenv("LOKI_URL", "http://m:3100")
    monkeypatch.setenv("TEMPO_URL", "http://m:3200")
    monkeypatch.setenv("SENTINEL_SERVICE_HOSTS", '{"payments-service": "app-2"}')
    monkeypatch.setenv("SSH_KEY_PATH", "/keys/id")


def test_build_wires_components_from_env(env):
    from sentinel import runtime
    from sentinel.loop import Loop
    from sentinel.store import PgStore

    store, skills, loop = runtime.build()
    assert isinstance(store, PgStore)
    assert isinstance(loop, Loop)
    assert skills.cfg.service_hosts == {"payments-service": "app-2"}
    assert skills.cfg.ssh_user == "ubuntu"          # default
    assert skills.cfg.prom_url == "http://m:9090"


def test_build_approval_runtime_returns_store_and_loop(env):
    from sentinel import runtime
    from sentinel.loop import Loop
    from sentinel.store import PgStore

    store, loop = runtime.build_approval_runtime()
    assert isinstance(store, PgStore)
    assert isinstance(loop, Loop)


def test_create_application_builds_fastapi_app(env):
    from fastapi import FastAPI

    from sentinel import runtime
    assert isinstance(runtime.create_application(), FastAPI)


def test_build_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from sentinel import runtime
    with pytest.raises(KeyError):
        runtime.build()
