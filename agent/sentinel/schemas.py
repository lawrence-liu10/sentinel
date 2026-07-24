"""Pydantic models for Sentinel's system boundaries.

Three groups: the inbound Alertmanager webhook (§7), the validated LLM diagnosis
(§8), and the six tool-call parameter sets (§2). Validating here means malformed
Alertmanager payloads and bad LLM tool args are rejected at the edge, never acted
on. Tool *return* shapes are validated in the skills that build them.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Alertmanager webhook (contracts §7) ------------------------------------
# Alertmanager sends more fields than we use (receiver, externalURL, ...); ignore
# the extras rather than fail the ingest.


class AlertLabels(BaseModel):
    model_config = ConfigDict(extra="ignore")
    alertname: str
    service: str | None = None
    severity: str | None = None


class AlertAnnotations(BaseModel):
    model_config = ConfigDict(extra="ignore")
    summary: str | None = None
    description: str | None = None


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fingerprint: str
    status: str | None = None
    labels: AlertLabels
    annotations: AlertAnnotations = AlertAnnotations()
    startsAt: str | None = None


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")
    version: str | None = None
    groupKey: str
    status: str
    alerts: list[Alert]


# --- Structured diagnosis (contracts §8) ------------------------------------


class ProposedAction(BaseModel):
    playbook: str
    args: dict = Field(default_factory=dict)
    # LLM's claim is advisory only — code recomputes the tier (risk.py).
    risk_tier: str


class Diagnosis(BaseModel):
    fault_label: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    runbook_cited: str | None = None
    proposed_action: ProposedAction | None = None


# --- Tool call parameters (contracts §2) ------------------------------------


class QueryPrometheusParams(BaseModel):
    promql: str
    window: str = "15m"
    step: str = "1m"


class QueryLokiParams(BaseModel):
    logql: str
    window: str = "15m"
    limit: int = 100


class QueryTempoParams(BaseModel):
    trace_id: str | None = None
    service: str | None = None
    min_duration: str | None = None

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> "QueryTempoParams":
        if bool(self.trace_id) == bool(self.service):
            raise ValueError("provide exactly one of trace_id / service")
        return self


class DescribeServiceParams(BaseModel):
    name: str


class ListRecentDeploysParams(BaseModel):
    service: str
    limit: int = 5


class RunPlaybookParams(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)
    dry_run: bool = True
