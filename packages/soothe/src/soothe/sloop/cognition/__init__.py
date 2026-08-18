"""StrangeLoop plan cognition — LLM assess/generate, wire coerce, keep/safety.

Owns plan-phase *reasoning* only (assess, gap, generate, structural keep,
trivial plan). Step plan *state* lives in ``soothe.context``.

Execute deliverable gating and step-completion display live in
``soothe.sloop.engine``. Prompt assembly helpers (step anchor registry) live in
``soothe.sloop.prompts``. Ledger compaction lives in ``soothe.sloop.utils``.
"""
