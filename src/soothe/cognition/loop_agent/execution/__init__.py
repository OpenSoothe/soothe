"""Execution layer for LoopAgent logic.

This module implements the core execution logic:
- judge: LLM-based judgment with structured output
- failure_detector: Guardrails and failure modes
"""

__all__ = [
    "FailureDetector",
    "JudgeEngine",
]
