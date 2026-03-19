"""Unified data inspection tool for tabular and document files (RFC-0014).

Routes to tabular or document tools based on file extension, providing
a single entry point for all data/document inspection tasks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_TABULAR_EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"})
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".rst", ".log"})


class DataTool(BaseTool):
    """Inspect data files and documents.

    Supports CSV, Excel, JSON, Parquet, PDF, DOCX, TXT, and more.
    Routes to the appropriate backend based on file extension.
    """

    name: str = "data"
    description: str = (
        "Inspect data files and documents. "
        "Provide `file_path` and optionally `operation` and `question`.\n"
        "Operations:\n"
        "- 'inspect': Column listing with types and samples (tabular) "
        "or document summary.\n"
        "- 'summary': Statistical summary (tabular) or document summary.\n"
        "- 'quality': Data quality validation (tabular only).\n"
        "- 'extract': Extract raw text content from document.\n"
        "- 'info': File metadata (size, format, page count).\n"
        "- 'ask': Answer a question about the file. Requires `question`.\n"
        "Supported formats: CSV, TSV, Excel, JSON, Parquet, PDF, DOCX, TXT, MD."
    )

    def _detect_domain(self, file_path: str) -> str:
        """Determine whether the file is tabular or document.

        Returns:
            'tabular', 'document', or 'unknown'.
        """
        suffix = Path(file_path).suffix.lower()
        if suffix in _TABULAR_EXTENSIONS:
            return "tabular"
        if suffix in _DOCUMENT_EXTENSIONS:
            return "document"
        return "unknown"

    def _run(
        self,
        file_path: str,
        operation: str = "inspect",
        question: str = "",
        **_kwargs: Any,
    ) -> str:
        """Inspect or query a data file.

        Args:
            file_path: Path to the data or document file.
            operation: One of 'inspect', 'summary', 'quality', 'extract', 'info', 'ask'.
            question: Question about the file (for 'ask' operation).

        Returns:
            Inspection result or error message.
        """
        operation = operation.strip().lower()
        domain = self._detect_domain(file_path)

        if operation == "ask":
            return self._do_ask(file_path, question, domain)
        if operation == "info":
            return self._do_info(file_path, domain)
        if operation == "extract":
            return self._do_extract(file_path)

        if domain == "tabular":
            return self._do_tabular(file_path, operation)
        if domain == "document":
            return self._do_document(file_path, operation)

        return (
            f"Error: Unsupported file format '{Path(file_path).suffix}'. "
            f"Supported: {', '.join(sorted(_TABULAR_EXTENSIONS | _DOCUMENT_EXTENSIONS))}"
        )

    async def _arun(self, file_path: str, **kwargs: Any) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path, **kwargs)

    # ------------------------------------------------------------------
    # Tabular operations
    # ------------------------------------------------------------------

    def _do_tabular(self, file_path: str, operation: str) -> str:
        try:
            if operation in ("inspect", "columns"):
                from soothe.tools._internal.tabular import TabularColumnsTool

                result = TabularColumnsTool()._run(file_path)
            elif operation == "summary":
                from soothe.tools._internal.tabular import TabularSummaryTool

                result = TabularSummaryTool()._run(file_path)
            elif operation == "quality":
                from soothe.tools._internal.tabular import TabularQualityTool

                result = TabularQualityTool()._run(file_path)
            else:
                return f"Error: Unknown operation '{operation}' for tabular data. Use: inspect, summary, quality."
        except Exception as exc:
            logger.exception("Tabular inspection failed")
            return f"Error inspecting tabular file: {exc}"
        else:
            return result

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------

    def _do_document(self, file_path: str, operation: str) -> str:
        try:
            if operation in ("inspect", "summary"):
                from soothe.tools._internal.document import DocumentQATool

                result = DocumentQATool()._run(file_path)
            else:
                return (
                    f"Error: Unknown operation '{operation}' for document. Use: inspect, summary, extract, info, ask."
                )
        except Exception as exc:
            logger.exception("Document inspection failed")
            return f"Error inspecting document: {exc}"
        else:
            return result

    def _do_extract(self, file_path: str) -> str:
        try:
            from soothe.tools._internal.document import ExtractTextTool

            return ExtractTextTool()._run(file_path)
        except Exception as exc:
            logger.exception("Text extraction failed")
            return f"Error extracting text: {exc}"

    def _do_info(self, file_path: str, domain: str) -> str:
        try:
            if domain == "document":
                from soothe.tools._internal.document import GetDocumentInfoTool

                result = GetDocumentInfoTool()._run(file_path)
                if isinstance(result, dict):
                    return "\n".join(f"{k}: {v}" for k, v in result.items())
                return str(result)

            from soothe.tools._internal.file_edit.tools import GetFileInfoTool

            return GetFileInfoTool()._run(file_path)
        except Exception as exc:
            logger.exception("File info retrieval failed")
            return f"Error getting file info: {exc}"

    def _do_ask(self, file_path: str, question: str, domain: str) -> str:
        if not question:
            return "Error: 'question' is required for 'ask' operation."
        try:
            if domain == "tabular":
                from soothe.tools._internal.tabular import TabularColumnsTool

                columns_info = TabularColumnsTool()._run(file_path)
                return (
                    f"Data schema:\n{columns_info}\n\n"
                    f"For detailed analysis, use the `execute` tool "
                    f"with mode='python' to run pandas code."
                )

            from soothe.tools._internal.document import DocumentQATool

            return DocumentQATool()._run(file_path, question=question)
        except Exception as exc:
            logger.exception("Question answering failed")
            return f"Error answering question: {exc}"


def create_data_tools() -> list[BaseTool]:
    """Create the unified data inspection tool.

    Returns:
        List containing a single DataTool.
    """
    return [DataTool()]
