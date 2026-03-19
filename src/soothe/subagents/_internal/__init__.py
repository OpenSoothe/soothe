"""Internal subagent implementations not directly exposed in prompt guidance.

The research and scout subagents are consumed internally by the
``research`` tool (InquiryEngine) and the resolver.  They remain
registered in SUBAGENT_FACTORIES for backward compatibility but are
no longer surfaced in the LLM's tool orchestration prompt.
"""
