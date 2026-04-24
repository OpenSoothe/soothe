"""Data inspection tools for tabular and document files (RFC-0016).

Provides single-purpose tools for data/document inspection following RFC-0016:
- inspect_data: Inspect data file structure
- summarize_data: Get statistical summary
- check_data_quality: Validate data quality
- extract_text: Extract text from documents
- get_data_info: Get file metadata
- ask_about_file: Answer questions about file content

Routes to tabular or document backends based on file extension.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

logger = logging.getLogger(__name__)

_TABULAR_EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"})
_DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".rst", ".log"})


def _detect_domain(file_path: str) -> str:
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


class InspectDataTool(BaseTool):
    """Inspect data file structure - columns, types, samples.

    For tabular files (CSV, Excel, JSON, Parquet), returns column listing
    with types and sample values.
    For documents (PDF, DOCX, TXT), returns document summary.
    """

    name: str = "inspect_data"
    description: str = (
        "Inspect data file structure. "
        "Use for: understanding CSV/Excel columns, types, samples. "
        "Parameters: file_path (required). "
        "Returns: column listing with types and sample values (tabular) or document summary."
    )

    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    def _run(self, file_path: str) -> str:
        """Inspect data file structure.

        Args:
            file_path: Path to the data or document file.

        Returns:
            Inspection result or error message.
        """
        domain = _detect_domain(file_path)

        if domain == "tabular":
            try:
                from soothe.toolkits._internal.tabular import get_tabular_columns

                result = get_tabular_columns(file_path)
            except Exception as exc:
                logger.exception("Tabular inspection failed")
                return f"Error inspecting tabular file: {exc}"
            else:
                return result

        if domain == "document":
            try:
                from soothe.toolkits._internal.document import document_qa

                result = document_qa(file_path, config=self.config)
            except Exception as exc:
                logger.exception("Document inspection failed")
                return f"Error inspecting document: {exc}"
            else:
                return result

        return (
            f"Error: Unsupported file format '{Path(file_path).suffix}'. "
            f"Supported: {', '.join(sorted(_TABULAR_EXTENSIONS | _DOCUMENT_EXTENSIONS))}"
        )

    async def _arun(self, file_path: str) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path)


class SummarizeDataTool(BaseTool):
    """Get statistical summary of data file.

    For tabular files, returns statistical summary (mean, median, std, etc.).
    For documents, returns document summary.
    """

    name: str = "summarize_data"
    description: str = (
        "Get statistical summary of data. "
        "Use for: understanding distributions, statistics. "
        "Parameters: file_path (required). "
        "Returns: statistical summary (tabular) or document summary."
    )

    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    def _run(self, file_path: str) -> str:
        """Get statistical summary.

        Args:
            file_path: Path to the data or document file.

        Returns:
            Summary result or error message.
        """
        domain = _detect_domain(file_path)

        if domain == "tabular":
            try:
                from soothe.toolkits._internal.tabular import get_data_summary

                return get_data_summary(file_path)
            except Exception as exc:
                logger.exception("Tabular summary failed")
                return f"Error summarizing tabular file: {exc}"

        if domain == "document":
            try:
                from soothe.toolkits._internal.document import document_qa

                return document_qa(file_path, config=self.config)
            except Exception as exc:
                logger.exception("Document summary failed")
                return f"Error summarizing document: {exc}"

        return (
            f"Error: Unsupported file format '{Path(file_path).suffix}'. "
            f"Supported: {', '.join(sorted(_TABULAR_EXTENSIONS | _DOCUMENT_EXTENSIONS))}"
        )

    async def _arun(self, file_path: str) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path)


class CheckDataQualityTool(BaseTool):
    """Validate data quality and identify issues.

    For tabular files only (CSV, Excel, JSON, Parquet).
    Checks for missing values, duplicates, and data anomalies.
    """

    name: str = "check_data_quality"
    description: str = (
        "Check data quality. "
        "Use for: finding missing values, duplicates, anomalies. "
        "Parameters: file_path (required). "
        "Returns: quality report. "
        "Tabular files only (CSV, Excel, JSON, Parquet)."
    )

    def _run(self, file_path: str) -> str:
        """Check data quality.

        Args:
            file_path: Path to the data file.

        Returns:
            Quality report or error message.
        """
        domain = _detect_domain(file_path)

        if domain == "tabular":
            try:
                from soothe.toolkits._internal.tabular import validate_data_quality

                result = validate_data_quality(file_path)
            except Exception as exc:
                logger.exception("Data quality check failed")
                return f"Error checking data quality: {exc}"
            else:
                return result

        if domain == "document":
            return "Error: Quality check is not supported for document files. Use inspect_data or summarize_data instead."

        return (
            f"Error: Unsupported file format '{Path(file_path).suffix}'. "
            f"Supported: {', '.join(sorted(_TABULAR_EXTENSIONS))}"
        )

    async def _arun(self, file_path: str) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path)


class ExtractTextTool(BaseTool):
    """Extract raw text from document files.

    For documents (PDF, DOCX, TXT, MD).
    Returns clean text content without metadata or formatting.
    """

    name: str = "extract_text"
    description: str = (
        "Extract text from documents. "
        "Use for: PDF/DOCX text extraction. "
        "Parameters: file_path (required). "
        "Returns: raw text content. "
        "Document files only (PDF, DOCX, TXT, MD)."
    )

    def _run(self, file_path: str) -> str:
        """Extract text from document.

        Args:
            file_path: Path to the document file.

        Returns:
            Extracted text or error message.
        """
        try:
            from soothe.toolkits._internal.document import extract_text

            result = extract_text(file_path)
        except Exception as exc:
            logger.exception("Text extraction failed")
            return f"Error extracting text: {exc}"
        else:
            return result

    async def _arun(self, file_path: str) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path)


class GetDataInfoTool(BaseTool):
    """Get file metadata and format information.

    Returns file size, format, modification time, and other metadata.
    For documents, includes page count.
    """

    name: str = "get_data_info"
    description: str = (
        "Get file metadata. "
        "Use for: file size, format, page count. "
        "Parameters: file_path (required). "
        "Returns: file metadata."
    )

    def _run(self, file_path: str) -> str:
        """Get file metadata.

        Args:
            file_path: Path to the file.

        Returns:
            File metadata or error message.
        """
        domain = _detect_domain(file_path)

        try:
            if domain == "document":
                from soothe.toolkits._internal.document import get_document_info

                result = get_document_info(file_path)
                if isinstance(result, dict):
                    return "\n".join(f"{k}: {v}" for k, v in result.items())
                return str(result)

            # For tabular and unknown files, use simple file metadata retrieval
            from datetime import UTC, datetime

            from soothe.utils import expand_path

            resolved_path = expand_path(file_path)
            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            stat = resolved_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            atime = datetime.fromtimestamp(stat.st_atime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

            info = [
                f"Path: {resolved_path}",
                f"Size: {stat.st_size} bytes ({stat.st_size / 1024:.2f} KB)",
                f"Modified: {mtime}",
                f"Accessed: {atime}",
                f"Is File: {resolved_path.is_file()}",
                f"Is Directory: {resolved_path.is_dir()}",
            ]

            return "\n".join(info)

        except Exception as exc:
            logger.exception("File info retrieval failed")
            return f"Error getting file info: {exc}"

    async def _arun(self, file_path: str) -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path)


class AskAboutFileTool(BaseTool):
    """Answer questions about a data or document file.

    For tabular files, returns schema information and suggests using run_python
    for detailed analysis.
    For documents, uses AI to answer questions about the content.
    """

    name: str = "ask_about_file"
    description: str = (
        "Ask question about file. "
        "Use for: querying data/document content. "
        "Parameters: file_path (required), question (required). "
        "Returns: answer based on file content."
    )

    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    def _run(self, file_path: str, question: str = "") -> str:
        """Answer question about file.

        Args:
            file_path: Path to the file.
            question: Question to answer.

        Returns:
            Answer or error message.
        """
        if not question:
            return "Error: 'question' parameter is required."

        domain = _detect_domain(file_path)

        if domain == "tabular":
            try:
                from soothe.toolkits._internal.tabular import get_tabular_columns

                columns_info = get_tabular_columns(file_path)
            except Exception as exc:
                logger.exception("Tabular question answering failed")
                return f"Error answering question: {exc}"
            else:
                return (
                    f"Data schema:\n{columns_info}\n\n"
                    f"For detailed analysis, use the `run_python` tool "
                    f"to execute pandas code."
                )

        if domain == "document":
            try:
                from soothe.toolkits._internal.document import document_qa

                return document_qa(file_path, question=question, config=self.config)
            except Exception as exc:
                logger.exception("Document question answering failed")
                return f"Error answering question: {exc}"

        return (
            f"Error: Unsupported file format '{Path(file_path).suffix}'. "
            f"Supported: {', '.join(sorted(_TABULAR_EXTENSIONS | _DOCUMENT_EXTENSIONS))}"
        )

    async def _arun(self, file_path: str, question: str = "") -> str:
        """Async dispatch (delegates to sync)."""
        return self._run(file_path, question)


class DataToolkit:
    """Toolkit for data inspection and analysis."""

    def __init__(self, *, config: Any = None) -> None:
        """Initialize the toolkit.

        Args:
            config: Optional SootheConfig for model creation.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of 6 data inspection BaseTool instances.
        """
        return [
            InspectDataTool(config=self._config),
            SummarizeDataTool(config=self._config),
            CheckDataQualityTool(),
            ExtractTextTool(),
            GetDataInfoTool(),
            AskAboutFileTool(config=self._config),
        ]


@plugin(
    name="data", version="1.0.0", description="Data inspection and analysis", trust_level="built-in"
)
class DataPlugin:
    """Data inspection and analysis tools plugin.

    Provides inspect_data, summarize_data, check_data_quality, extract_text,
    get_data_info, and ask_about_file tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with config.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = DataToolkit(config=context.config)
        self._tools = toolkit.get_tools()

        context.logger.info("Loaded %d data tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of data tool instances.
        """
        return self._tools
