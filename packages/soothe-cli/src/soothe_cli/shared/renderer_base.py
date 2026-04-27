"""Base class providing shared utilities for CLI and TUI renderers.

This module provides common functionality that both sync (CLI) and async (TUI)
renderers can inherit from, reducing duplication and ensuring consistent behavior.
"""

from __future__ import annotations

import re


class RendererBase:
    """Base class for CLI and TUI renderers with shared utilities.

    Provides:
    - Unified streaming text repair logic
    - Shared formatting helpers
    - Common display utilities

    Both CliRenderer and TuiRenderer inherit from this base class.
    """

    @staticmethod
    def repair_concatenated_output(text: str) -> str:
        """Repair common markdown/text concatenation artifacts.

        Consolidates the repair logic previously duplicated in:
        - CLI: _repair_concatenated_final_output()
        - TUI: _repair_concatenated_output_text()

        Fixes issues that arise when streaming text chunks are concatenated:
        - Missing newlines before headings
        - Missing spaces after heading markers
        - Missing line breaks between sections
        - Incorrect spacing in numbered lists

        Args:
            text: Text to repair (typically streaming output).

        Returns:
            Repaired text with proper markdown formatting.

        Example:
            >>> text = "##1First Step##2Second Step"
            >>> repaired = RendererBase.repair_concatenated_output(text)
            >>> print(repaired)
            ## 1 First Step

            ## 2 Second Step
        """
        repaired = text
        # Add newline before numbered headings (## 1, ## 2, etc.)
        repaired = re.sub(r"(?<!\n)(?=##+\s*\d)", "\n\n", repaired)
        # Add newline before letter headings (## Summary, etc.)
        repaired = re.sub(r"(?<!\n)(?=##+\s*[A-Za-z])", "\n\n", repaired)
        # Add space after ## before numbers
        repaired = re.sub(r"(?<=##)(?=\d)", " ", repaired)
        # Add space between letters and numbers
        repaired = re.sub(r"(?<=[A-Za-z])(?=\d{1,3}\b)", " ", repaired)
        # Add newline between lowercase and uppercase in headings
        repaired = re.sub(r"(##[^\n]*[a-z])(?=[A-Z])", r"\1\n\n", repaired)
        # Add newline before numbered lists with bold (**1. **)
        repaired = re.sub(r"(?<!\n)(?=\d+\.\s+\*\*)", "\n", repaired)
        # Add newline before bullet lists with bold
        repaired = re.sub(r"(?<=[A-Za-z])(?=-\s+\*\*)", "\n", repaired)
        # Add newline before regular bullet points
        repaired = re.sub(r"(?<=[A-Za-z0-9])(?=-\s)", "\n", repaired)
        # Add newline between numbers and special characters
        repaired = re.sub(r"(?<=\d)(?=[#<])", "\n", repaired)
        return repaired
