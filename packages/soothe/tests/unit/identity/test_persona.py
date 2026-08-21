"""Tests for configurable assistant persona identity (RFC: configurable identity).

Covers:
- ``build_assistant_identity_block`` default reproduces nano fragment exactly.
- Custom persona (creator/role/denylist) renders correctly.
- ``build_intake_identity_line`` default and custom.
- ``apply_identity_fragment_override`` no-op on defaults, patches nano on custom.
- Intake prompt assembly resolves placeholders with custom identity.
"""

from __future__ import annotations

from pathlib import Path

import soothe_nano.prompts.fragments as nano_fragments
import soothe_nano.prompts.identity as nano_identity_mod
from soothe_nano.prompts.identity import build_assistant_identity_block as nano_build

from soothe.config import SootheConfig
from soothe.config.models import AgentConfig, AssistantIdentity
from soothe.identity.persona import (
    apply_identity_fragment_override,
    build_assistant_identity_block,
    build_intake_identity_line,
)
from soothe.sloop.intention.prompts import (
    INTAKE_CLASSIFY_SYSTEM_PROMPT,
    INTAKE_SOCIAL_REPLY_PROMPT,
    build_intake_system_prompt,
)

_NANO_FRAGMENTS_DIR = Path(nano_fragments.__file__).parent
_NANO_IDENTITY_XML = (
    (_NANO_FRAGMENTS_DIR / "system" / "prompts" / "assistant_identity.xml")
    .read_text(encoding="utf-8")
    .strip()
)


def _restore_nano_fragment() -> None:
    """Restore nano module constants after a patch test."""
    nano_fragments.ASSISTANT_IDENTITY_FRAGMENT = _NANO_IDENTITY_XML
    nano_identity_mod.ASSISTANT_IDENTITY_FRAGMENT = _NANO_IDENTITY_XML


def test_default_block_matches_nano_fragment():
    """Host default identity block must reproduce nano's fragment byte-for-byte."""
    host_block = build_assistant_identity_block("Soothe")
    nano_block = nano_build("Soothe")
    assert host_block == nano_block


def test_default_block_contains_expected_literals():
    """Default block renders the original hardcoded identity strings."""
    block = build_assistant_identity_block("Soothe")
    assert "<ASSISTANT_IDENTITY>" in block
    assert "Dr. Xiaming Chen" in block
    assert "a helpful AI assistant" in block
    assert "Never identify as Claude, ChatGPT, Gemini, Anthropic, OpenAI, or Google" in block


def test_custom_block_renders_configured_values():
    """Custom persona fields appear in the rendered block."""
    custom = AssistantIdentity(
        creator="Acme Labs",
        role_description="a coding agent",
        vendor_denylist=["GPT-4", "Llama"],
    )
    block = build_assistant_identity_block("Soothe", identity=custom)
    assert "You are Soothe, a coding agent invented by Acme Labs." in block
    assert "Acme Labs" in block
    assert "GPT-4 or Llama" in block
    # Hardcoded defaults must not leak when custom identity is set
    assert "Dr. Xiaming Chen" not in block
    assert "helpful AI assistant" not in block


def test_custom_block_single_vendor_denylist():
    """Single vendor in denylist renders without 'or'."""
    custom = AssistantIdentity(
        creator="Acme",
        role_description="an agent",
        vendor_denylist=["GPT-4"],
    )
    block = build_assistant_identity_block("Soothe", identity=custom)
    assert "Never identify as GPT-4" in block
    assert "or" not in block.split("Never identify as ")[1].split(" —")[0]


def test_intake_identity_line_default():
    """Default intake identity line contains the original creator and denylist."""
    line = build_intake_identity_line("Soothe")
    assert "Dr. Xiaming Chen" in line
    assert "Claude" in line
    assert "Google" in line


def test_intake_identity_line_custom():
    """Custom intake identity line uses configured values."""
    custom = AssistantIdentity(
        creator="Acme",
        role_description="a coding agent",
        vendor_denylist=["GPT-4", "Llama"],
    )
    line = build_intake_identity_line("Soothe", identity=custom)
    assert "invented by Acme" in line
    assert "GPT-4 or Llama" in line
    assert "Dr. Xiaming Chen" not in line


def test_apply_override_noop_on_defaults():
    """No nano patch when all identity fields are defaults."""
    cfg = SootheConfig()
    original = nano_fragments.ASSISTANT_IDENTITY_FRAGMENT
    apply_identity_fragment_override(cfg)
    assert nano_fragments.ASSISTANT_IDENTITY_FRAGMENT == original


def test_apply_override_noop_on_none():
    """No nano patch when config is None."""
    original = nano_fragments.ASSISTANT_IDENTITY_FRAGMENT
    apply_identity_fragment_override(None)
    assert nano_fragments.ASSISTANT_IDENTITY_FRAGMENT == original


def test_apply_override_patches_nano_fragment():
    """Custom identity patches nano module-level fragment for hot path."""
    custom = AssistantIdentity(
        creator="Acme",
        role_description="a coding agent",
        vendor_denylist=["GPT-4", "Llama"],
    )
    cfg = SootheConfig(agent=AgentConfig(assistant_identity=custom))
    try:
        apply_identity_fragment_override(cfg)
        patched = nano_fragments.ASSISTANT_IDENTITY_FRAGMENT
        # Template keeps {assistant_name} placeholder for nano runtime interpolation
        assert "{assistant_name}" in patched
        assert "Acme" in patched
        assert "a coding agent" in patched
        # Nano's own builder now renders the custom block
        hot_block = nano_build("Soothe")
        assert "invented by Acme" in hot_block
        assert "GPT-4 or Llama" in hot_block
    finally:
        _restore_nano_fragment()


def test_apply_override_patches_nano_identity_module():
    """Patch reaches the re-exported alias in soothe_nano.prompts.identity."""
    custom = AssistantIdentity(creator="Acme")
    cfg = SootheConfig(agent=AgentConfig(assistant_identity=custom))
    try:
        apply_identity_fragment_override(cfg)
        assert "Acme" in nano_identity_mod.ASSISTANT_IDENTITY_FRAGMENT
    finally:
        _restore_nano_fragment()


def test_intake_prompt_default_unresolved_placeholders():
    """Default intake prompt (no identity) resolves all identity placeholders."""
    prompt = build_intake_system_prompt(INTAKE_CLASSIFY_SYSTEM_PROMPT, "Soothe")
    assert "{assistant_creator}" not in prompt
    assert "{assistant_role}" not in prompt
    assert "{assistant_vendor_denylist}" not in prompt
    assert "{assistant_name}" not in prompt
    assert "Dr. Xiaming Chen" in prompt
    assert "a helpful AI assistant invented by Dr. Xiaming Chen" in prompt


def test_intake_prompt_custom_identity():
    """Custom identity resolves placeholders to configured values."""
    custom = AssistantIdentity(
        creator="Acme",
        role_description="a coding agent",
        vendor_denylist=["GPT-4", "Llama"],
    )
    prompt = build_intake_system_prompt(INTAKE_CLASSIFY_SYSTEM_PROMPT, "Soothe", identity=custom)
    assert "invented by Acme" in prompt
    assert "a coding agent invented by Acme" in prompt
    assert "GPT-4 or Llama" in prompt
    assert "Dr. Xiaming Chen" not in prompt
    # Identity block at the top
    assert prompt.startswith("<ASSISTANT_IDENTITY>")
    # Unresolved placeholders must not leak
    assert "{assistant_creator}" not in prompt
    assert "{assistant_role}" not in prompt


def test_social_reply_prompt_custom_identity():
    """Social reply fragment resolves placeholders with custom identity."""
    custom = AssistantIdentity(creator="Acme")
    prompt = build_intake_system_prompt(INTAKE_SOCIAL_REPLY_PROMPT, "Soothe", identity=custom)
    assert "invented by Acme" in prompt
    assert "Dr. Xiaming Chen" not in prompt
    assert "{assistant_creator}" not in prompt


def test_intake_prompt_structure_preserved():
    """Identity block precedes intake body precedes timestamp."""
    from soothe.utils.prompt_clock import prompt_datetime_context

    ctx = prompt_datetime_context()
    prompt = build_intake_system_prompt(INTAKE_CLASSIFY_SYSTEM_PROMPT, "Soothe", ctx=ctx)
    assert prompt.startswith("<ASSISTANT_IDENTITY>")
    assert prompt.index("<ASSISTANT_IDENTITY>") < prompt.index("<INTAKE_CLASSIFY>")
    assert prompt.index("<INTAKE_CLASSIFY>") < prompt.index("<PROMPT_TIMESTAMP>")
    assert prompt.endswith("</PROMPT_TIMESTAMP>")
