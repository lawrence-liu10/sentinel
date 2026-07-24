"""LLM client tests — the parsing seam: normalize a LiteLLM/OpenAI response into
tool calls (with JSON args decoded), token counts, and the model that actually
served the call (the measured-failover signal). The completion function is
injected so no network/litellm is touched."""

from types import SimpleNamespace

from sentinel.llm import LLM


def _response(content, tool_calls, model, pt=100, ct=20):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
        model=model,
    )


def test_complete_parses_tool_calls_usage_and_model():
    tc = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="query_prometheus", arguments='{"promql": "up"}'),
    )
    seen = {}

    def fake_completion(**kw):
        seen.update(kw)
        return _response("looking", [tc], "bedrock/claude-sonnet-5")

    out = LLM(completion_fn=fake_completion).complete(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "query_prometheus"}}],
    )
    assert seen["model"] == "sentinel-agent"
    assert out.content == "looking"
    assert out.tool_calls[0].name == "query_prometheus"
    assert out.tool_calls[0].arguments == {"promql": "up"}
    assert (out.tokens_in, out.tokens_out) == (100, 20)
    assert out.model == "bedrock/claude-sonnet-5"
    assert out.latency_ms >= 0


def test_complete_handles_no_tool_calls():
    out = LLM(completion_fn=lambda **kw: _response("final", None, "anthropic/claude-sonnet-5")).complete(
        messages=[{"role": "user", "content": "x"}]
    )
    assert out.tool_calls == []
    assert out.content == "final"
