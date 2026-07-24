"""The agent's tools. `Skills` is the facade the loop calls; the per-tool logic
lives in sibling modules. External effects (HTTP to the LGTM stack, SSH for
docker inspect, ansible for playbooks) are injectable so the whole agent is
unit-testable with zero infrastructure.
"""

import json
import os
import subprocess
from dataclasses import dataclass

import httpx

from sentinel import schemas
from sentinel.store import Store

from . import deploys, docker_info, loki, playbook, prometheus, tempo

_ANSIBLE_DIR = os.environ.get("SENTINEL_ANSIBLE_DIR", "ansible")


@dataclass
class SkillConfig:
    prom_url: str
    loki_url: str
    tempo_url: str
    service_hosts: dict[str, str]  # service name -> host (from the deploy topology)
    ssh_user: str
    ssh_key_path: str


def _default_ansible(name: str, args: dict, check: bool) -> tuple[int, bool, str]:
    cmd = ["ansible-playbook", f"playbooks/{name}.yml", "-e", json.dumps(args)]
    if check:
        cmd.append("--check")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=_ANSIBLE_DIR)
    out = r.stdout + r.stderr
    changed = " changed=0" not in out and "changed=" in out
    return r.returncode, changed, out


class Skills:
    def __init__(self, cfg: SkillConfig, store: Store, *, http: httpx.Client | None = None,
                 run_ssh=None, run_ansible=None) -> None:
        self.cfg = cfg
        self.store = store
        self.http = http or httpx.Client(timeout=15)
        self._run_ssh = run_ssh or self._default_ssh
        self._run_ansible = run_ansible or _default_ansible

    def _default_ssh(self, host: str, argv: list[str]) -> str:
        cmd = ["ssh", "-i", self.cfg.ssh_key_path, "-o", "StrictHostKeyChecking=no",
               f"{self.cfg.ssh_user}@{host}", *argv]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    # read tools (contracts §2) — side-effect-free
    def query_prometheus(self, p: schemas.QueryPrometheusParams) -> dict:
        return prometheus.query(self.http, self.cfg.prom_url, p)

    def query_loki(self, p: schemas.QueryLokiParams) -> dict:
        return loki.query(self.http, self.cfg.loki_url, p)

    def query_tempo(self, p: schemas.QueryTempoParams) -> dict:
        return tempo.query(self.http, self.cfg.tempo_url, p)

    def describe_service(self, p: schemas.DescribeServiceParams) -> dict:
        return docker_info.describe(self._run_ssh, self.cfg.service_hosts, p)

    def list_recent_deploys(self, p: schemas.ListRecentDeploysParams) -> dict:
        return deploys.list_recent(self.store, p)

    # the one write tool — risk-gated (contracts §3)
    def run_playbook(self, incident_id: int, p: schemas.RunPlaybookParams,
                     evidence: str | None = None) -> dict:
        return playbook.run(self._run_ansible, self.store, incident_id, p, evidence)

    def execute_approved(self, action_id: int) -> dict:
        return playbook.execute_approved(self._run_ansible, self.store, action_id)
