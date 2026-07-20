"""Unit tests for MCP budget formatter (RFC-412)."""

from soothe_nano.mcp.mcp_utils import (
    MCPToolDescriptor,
    format_mcp_tools_within_budget,
)


def make_descriptor(
    name: str,
    description: str,
    server: str = "test",
    is_essential: bool = False,
) -> MCPToolDescriptor:
    """Helper to create MCPToolDescriptor."""
    return MCPToolDescriptor(
        name=name,
        bare_name=name.split("__")[-1] if "__" in name else name,
        description=description,
        server=server,
        is_essential=is_essential,
    )


class TestFormatMcpToolsWithinBudget:
    """Tests for format_mcp_tools_within_budget."""

    def test_empty_entries(self) -> None:
        """Empty entries produce empty output."""
        text, tel = format_mcp_tools_within_budget([], budget_chars=1000)
        assert text == ""
        assert tel["included_count"] == 0
        assert tel["mode"] == "full"

    def test_under_budget_full_mode(self) -> None:
        """Under budget: full descriptions."""
        entries = [
            make_descriptor("mcp__github__create_issue", "Create a new GitHub issue"),
            make_descriptor("mcp__github__list_repos", "List repositories"),
        ]
        text, tel = format_mcp_tools_within_budget(entries, budget_chars=1000)

        assert "mcp__github__create_issue" in text
        assert "Create a new GitHub issue" in text
        assert tel["mode"] == "full"
        assert tel["truncated_count"] == 0

    def test_over_budget_truncated_mode(self) -> None:
        """Over budget: non-essential truncated, essential full."""
        entries = [
            make_descriptor("mcp__essential__tool", "Essential tool", is_essential=True),
            make_descriptor(
                "mcp__other__tool",
                "This is a very long description that should be truncated",
                is_essential=False,
            ),
        ]
        text, tel = format_mcp_tools_within_budget(
            entries,
            budget_chars=100,  # enough for essential + truncated non-essential
            per_entry_cap_chars=30,
        )

        assert tel["mode"] == "truncated"
        # Essential keeps full description
        assert "Essential tool" in text
        # Non-essential truncated
        assert tel["truncated_count"] >= 1

    def test_extreme_budget_names_only_mode(self) -> None:
        """Extreme budget: non-essential become names-only."""
        entries = [
            make_descriptor("mcp__essential__tool", "Essential", is_essential=True),
            make_descriptor("mcp__other1__tool", "Description 1", is_essential=False),
            make_descriptor("mcp__other2__tool", "Description 2", is_essential=False),
        ]
        text, tel = format_mcp_tools_within_budget(
            entries,
            budget_chars=20,  # extreme: can't fit descriptions
            min_per_entry_chars=50,  # force names-only
        )

        assert tel["mode"] == "names_only"
        # Essential still has description
        assert "Essential" in text
        # Non-essential are names-only
        assert "mcp__other1__tool" in text
        assert "Description 1" not in text
        assert tel["truncated_count"] == 2

    def test_all_essential(self) -> None:
        """All essential tools keep full descriptions."""
        entries = [
            make_descriptor("mcp__a__tool", "Tool A", is_essential=True),
            make_descriptor("mcp__b__tool", "Tool B", is_essential=True),
        ]
        text, tel = format_mcp_tools_within_budget(entries, budget_chars=100)

        # All are essential, no truncation even if budget is tight
        assert "Tool A" in text
        assert "Tool B" in text

    def test_budget_telemetry(self) -> None:
        """Telemetry dict contains expected fields."""
        entries = [make_descriptor("mcp__test__tool", "Test")]
        text, tel = format_mcp_tools_within_budget(entries, budget_chars=500)

        assert "included_count" in tel
        assert "truncated_count" in tel
        assert "mode" in tel
        assert "budget_chars" in tel
        assert "actual_chars" in tel
        assert tel["budget_chars"] == 500
        assert tel["actual_chars"] == len(text)

    def test_long_description_truncated_to_cap(self) -> None:
        """Long description truncated to per_entry_cap_chars."""
        entries = [
            make_descriptor(
                "mcp__test__tool",
                "This is a very long description that goes way beyond the cap",
                is_essential=False,
            ),
        ]
        text, tel = format_mcp_tools_within_budget(
            entries,
            budget_chars=1000,
            per_entry_cap_chars=50,
        )

        # Description truncated to 50 chars + ellipsis
        assert len(text) < 100  # roughly 50 for desc + name prefix
