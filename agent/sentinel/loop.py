"""The incident loop (contracts §8).

gather → hypothesize → verify → classify → act|ask → confirm → postmortem.

The LLM is given the READ tools only; it diagnoses and *proposes* a remediation in
its JSON output. The loop — code, not the model — then executes that proposal, so
the code-computed risk tier (risk.py, inside run_playbook) always governs whether
it runs or parks for approval. High-risk parks and returns; resumption after a
human approval is a separate entry point that re-reads state from the store, so it
survives an agent restart. Every LLM turn and tool call is written to agent_steps.
"""

import json
import time

from sentinel import prompts, schemas
from sentinel.llm import LLM
from sentinel.store import Store

_READ_PARAM_MODELS = {
    "query_prometheus": schemas.QueryPrometheusParams,
    "query_loki": schemas.QueryLokiParams,
    "query_tempo": schemas.QueryTempoParams,
    "describe_service": schemas.DescribeServiceParams,
    "list_recent_deploys": schemas.ListRecentDeploysParams,
}


class Loop:
    def __init__(self, llm: LLM, skills, store: Store, *, max_tool_calls: int = 15,
                 max_input_tokens: int = 150_000, confidence_threshold: float = 0.7,
                 confirm_timeout_s: int = 600, confirm_interval_s: int = 15,
                 sleep=time.sleep) -> None:
        self.llm = llm
        self.skills = skills
        self.store = store
        self.max_tool_calls = max_tool_calls
        self.max_input_tokens = max_input_tokens
        self.confidence_threshold = confidence_threshold
        self.confirm_timeout_s = confirm_timeout_s
        self.confirm_interval_s = confirm_interval_s
        self._sleep = sleep
        self._read_tools = [t for t in prompts.tool_specs()
                            if t["function"]["name"] in _READ_PARAM_MODELS]

    # --- entry points --------------------------------------------------------
    def run_incident(self, incident_id: int) -> None:
        self.store.set_status(incident_id, "diagnosing")
        inc = self.store.get_incident(incident_id)
        messages = [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.initial_user_message(
                inc["alertname"], inc["service"], None, None)},
        ]
        diagnosis = self._diagnose(incident_id, messages)
        if diagnosis is None:
            return self._escalate(incident_id, "diagnosis did not complete within budget",
                                  phase="hypothesize")
        self.store.set_diagnosis(incident_id, diagnosis.fault_label, diagnosis.confidence,
                                 diagnosis.runbook_cited)
        if (diagnosis.confidence < self.confidence_threshold
                or diagnosis.fault_label == "unknown"
                or diagnosis.proposed_action is None):
            return self._escalate(incident_id, "low confidence or no actionable diagnosis")
        self._act(incident_id, diagnosis)

    def resume_after_approval(self, incident_id: int, action_id: int) -> None:
        """Called after a human approval row is written. Executes the approved
        action (execute_approved refuses without the row) then confirms + closes."""
        result = self.skills.execute_approved(action_id)
        self.store.append_step(incident_id, phase="act", tool_name="run_playbook",
                               tool_args={"action_id": action_id, "approved": True},
                               tool_result=result)
        if result["status"] != "executed":
            return self._escalate(incident_id, "approved remediation failed")
        self.store.set_status(incident_id, "remediating")
        self._confirm_and_close(incident_id)

    # --- phases --------------------------------------------------------------
    def _diagnose(self, incident_id: int, messages: list[dict]) -> schemas.Diagnosis | None:
        used = 0
        input_tokens = 0
        while True:
            resp = self.llm.complete(messages, tools=self._read_tools)
            input_tokens += resp.tokens_in
            self.store.append_step(incident_id, phase="hypothesize", reasoning=resp.content,
                                   tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
                                   latency_ms=resp.latency_ms)
            if not resp.tool_calls:
                return self._parse_diagnosis(resp.content)
            messages.append(self._assistant_msg(resp))
            for tc in resp.tool_calls:
                if used >= self.max_tool_calls or input_tokens >= self.max_input_tokens:
                    return None
                result = self._exec_tool(incident_id, tc)
                used += 1
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result, default=str)})

    def _exec_tool(self, incident_id: int, tc) -> dict:
        model = _READ_PARAM_MODELS.get(tc.name)
        if model is None:
            result = {"error": f"unknown or non-read tool: {tc.name}"}
        else:
            try:
                params = model(**tc.arguments)
                result = getattr(self.skills, tc.name)(params)
            except Exception as e:  # bad args or skill failure — feed back, don't crash
                result = {"error": str(e)}
        self.store.append_step(incident_id, phase="gather", tool_name=tc.name,
                               tool_args=tc.arguments, tool_result=result)
        return result

    def _act(self, incident_id: int, diagnosis: schemas.Diagnosis) -> None:
        pa = diagnosis.proposed_action
        params = schemas.RunPlaybookParams(name=pa.playbook, args=pa.args, dry_run=False)
        result = self.skills.run_playbook(incident_id, params, evidence=diagnosis.summary)
        self.store.append_step(incident_id, phase="act", tool_name="run_playbook",
                               tool_args={"name": pa.playbook, "args": pa.args, "dry_run": False},
                               tool_result=result)
        if result["status"] == "awaiting_approval":
            self.store.set_status(incident_id, "awaiting_approval")  # park; wait for a human
            return
        if result["status"] != "executed":
            return self._escalate(incident_id, f"remediation did not execute: {result['status']}")
        self.store.set_status(incident_id, "remediating")
        self._confirm_and_close(incident_id)

    def _confirm_and_close(self, incident_id: int) -> None:
        if not self._confirm(incident_id):
            return self._escalate(incident_id, "remediation ran but the alert did not clear",
                                  phase="confirm")
        self._postmortem(incident_id)
        self.store.resolve(incident_id)

    def _confirm(self, incident_id: int) -> bool:
        # Recovery is verified, not trusted: poll Prometheus's own ALERTS series
        # for this alert until it stops firing (≤ confirm_timeout_s).
        alertname = self.store.get_incident(incident_id)["alertname"]
        q = schemas.QueryPrometheusParams(
            promql=f'ALERTS{{alertname="{alertname}",alertstate="firing"}}',
            window="1m", step="15s")
        for _ in range(max(1, self.confirm_timeout_s // self.confirm_interval_s)):
            res = self.skills.query_prometheus(q)
            firing = res.get("series", [])
            self.store.append_step(incident_id, phase="confirm", tool_name="query_prometheus",
                                   tool_args={"promql": q.promql},
                                   tool_result={"firing_series": len(firing)})
            if not firing:
                return True
            self._sleep(self.confirm_interval_s)
        return False

    def _postmortem(self, incident_id: int) -> None:
        inc = self.store.get_incident(incident_id)
        resp = self.llm.complete([
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content":
                f"Incident on '{inc['service']}' ({inc['alertname']}) is resolved. Root cause: "
                f"{inc['root_cause']} (confidence {inc['confidence']}). Write a concise postmortem "
                "in markdown: what happened, root cause, remediation taken, prevention."},
        ])
        self.store.append_step(incident_id, phase="postmortem", reasoning=resp.content,
                               tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
                               latency_ms=resp.latency_ms)
        self.store.set_postmortem(incident_id, resp.content or "")

    def _escalate(self, incident_id: int, reason: str, phase: str = "classify") -> None:
        self.store.append_step(incident_id, phase=phase, reasoning=f"ESCALATE to human: {reason}")
        self.store.set_status(incident_id, "failed")

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _assistant_msg(resp) -> dict:
        return {
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in resp.tool_calls
            ],
        }

    @staticmethod
    def _parse_diagnosis(content: str | None) -> schemas.Diagnosis | None:
        if not content:
            return None
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            return None
        try:
            return schemas.Diagnosis.model_validate(json.loads(content[start:end + 1]))
        except Exception:
            return None
