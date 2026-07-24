"""Sentinel — autonomous SRE incident-response agent.

A hand-rolled tool-use loop (LiteLLM → Bedrock/Anthropic) that diagnoses injected
faults from the LGTM stack and remediates via Ansible under tiered autonomy. Risk
tier is computed in code (never taken from the LLM); high-risk actions gate on a
human approval. See docs/plans/01-contracts.md.
"""
