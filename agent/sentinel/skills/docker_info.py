"""describe_service — `docker inspect` over SSH, returning env variable *names*
only (contracts §10). Values are never read out, so a secret in the container's
environment can't leak into the LLM context or the audit log.
"""

import json

from sentinel import schemas


def describe(run_ssh, service_hosts: dict[str, str], p: schemas.DescribeServiceParams) -> dict:
    host = service_hosts.get(p.name)
    container = f"sentinel-{p.name}"
    info = json.loads(run_ssh(host, ["docker", "inspect", container]))[0]

    cfg = info.get("Config", {})
    image = cfg.get("Image", "")
    state = info.get("State", {})
    mem = info.get("HostConfig", {}).get("Memory") or 0
    return {
        "host": host,
        "image": image,
        "tag": image.rsplit(":", 1)[-1] if ":" in image else "",
        "status": state.get("Status"),
        "restart_count": state.get("RestartCount"),
        "started_at": state.get("StartedAt"),
        "ports": list(info.get("NetworkSettings", {}).get("Ports", {}).keys()),
        "memory_limit_mb": mem // (1024 * 1024) if mem else None,
        # NAMES ONLY — split each "KEY=value" and keep the key.
        "env_names": [e.split("=", 1)[0] for e in cfg.get("Env", [])],
    }
