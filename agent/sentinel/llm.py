"""LiteLLM client — the agent's single call into the model gateway.

The agent only ever names the `sentinel-agent` alias; the gateway (litellm/config.yaml)
decides Bedrock-vs-Anthropic, so a provider switch is a config change, not a code
change. Every call is normalized to an `LLMResponse` carrying token counts, latency,
and the model that actually served it — the numbers that land in `agent_steps` and
prove the failover happened.
"""

import json
import time
from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str


def _litellm_completion(**kwargs):
    import litellm  # lazy — keeps import light and tests litellm-free

    return litellm.completion(**{k: v for k, v in kwargs.items() if v is not None})


class LLM:
    def __init__(self, model: str = "sentinel-agent", *, base_url: str | None = None,
                 api_key: str | None = None, completion_fn=None) -> None:
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self._completion = completion_fn or _litellm_completion

    def complete(self, messages: list[dict], tools: list[dict] | None = None,
                 tool_choice: str = "auto") -> LLMResponse:
        t0 = time.monotonic()
        resp = self._completion(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice if tools else None,
            base_url=self.base_url,
            api_key=self.api_key,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        return _parse(resp, latency_ms)


def _parse(resp, latency_ms: int) -> LLMResponse:
    message = resp.choices[0].message
    calls = []
    for tc in getattr(message, "tool_calls", None) or []:
        args = tc.function.arguments
        calls.append(ToolCall(
            id=tc.id,
            name=tc.function.name,
            arguments=json.loads(args) if isinstance(args, str) else (args or {}),
        ))
    usage = resp.usage
    return LLMResponse(
        content=message.content,
        tool_calls=calls,
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.completion_tokens,
        latency_ms=latency_ms,
        model=resp.model,
    )
