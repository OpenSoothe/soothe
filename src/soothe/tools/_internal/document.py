"""Document parsing and Q&A with multi-format support.

Ported from noesium's document_toolkit.py.
Uses PyMuPDF for PDF parsing with optional Chunkr API support.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from soothe.utils.text_preview import preview_first
from pydantic import Field

logger = logging.getLogger(__name__)


class DocumentQATool(BaseTool):
    """Document Q&A with multi-format support.

    Parses PDF, Office documents, and text files.
    Supports PyMuPDF (default) for fast extraction.
    """

    name: str = "document_qa"
    description: str = (
        "Answer questions about document content. "
        "Provide `document_path` (local path or URL to document). "
        "Optional `question` about the document (if omitted, returns summary). "
        "Supports PDF, DOCX, TXT, and other formats. "
        "Returns answer or summary."
    )

    parser: str = Field(default="pymupdf")
    text_limit: int = Field(default=100000)  # Max characters to extract
    cache_dir: str = Field(default="")
    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    def _get_cache_path(self, document_path: str) -> Path | None:
        """Get cache file path for parsed document."""
        if not self.cache_dir:
            return None

        cache = Path(self.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        md5 = hashlib.md5(document_path.encode()).hexdigest()
        return cache / f"{md5}.txt"

    def _download_if_url(self, document_path: str) -> str:
        """Download document if URL, return local path."""
        if not document_path.startswith(("http://", "https://")):
            return document_path

        try:
            import requests

            resp = requests.get(document_path, timeout=60)
            resp.raise_for_status()

            suffix = Path(document_path).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            logger.info("Downloaded document from URL: %s", document_path)
        except ImportError:
            msg = "requests not installed for URL downloading"
            raise RuntimeError(msg) from None
        else:
            return tmp_path

    def _parse_pdf_pymupdf(self, file_path: str) -> str:
        """Parse PDF using PyMuPDF.

        Args:
            file_path: Path to PDF file.

        Returns:
            Extracted text.

        Raises:
            ImportError: If PyMuPDF not installed.
        """
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            pages = []

            for page_num in range(doc.page_count):
                page = doc[page_num]
                text = page.get_text()
                pages.append(f"## Page {page_num + 1}\n\n{text}")

            doc.close()
            return "\n\n".join(pages)

        except ImportError:
            msg = "PyMuPDF not installed. Install with: pip install PyMuPDF"
            raise ImportError(msg) from None

    def _parse_document(self, document_path: str) -> str:
        """Parse document and extract text.

        Args:
            document_path: Path to document.

        Returns:
            Extracted text.

        Raises:
            ValueError: If format not supported.
        """
        path = Path(document_path)
        suffix = path.suffix.lower()

        # PDF
        if suffix == ".pdf":
            if self.parser == "pymupdf":
                return self._parse_pdf_pymupdf(document_path)
            # Future: Chunkr API support
            return self._parse_pdf_pymupdf(document_path)

        # Text files
        if suffix in {".txt", ".md", ".rst", ".log"}:
            return path.read_text(encoding="utf-8", errors="ignore")

        # JSON
        if suffix == ".json":
            import json

            return json.dumps(json.loads(path.read_text()), indent=2)

        # Unsupported format
        msg = f"Unsupported document format: {suffix}. Supported: PDF, TXT, MD, RST, JSON"
        raise ValueError(msg)

    def _summarize_text(self, text: str) -> str:
        """Summarize text using LLM.

        Args:
            text: Text to summarize.

        Returns:
            Summary.
        """
        try:
            # Use Soothe config if available, otherwise fallback to ChatOpenAI
            if self.config is not None:
                llm = self.config.create_chat_model("fast")
            else:
                from langchain_openai import ChatOpenAI

                logger.warning("No config provided to DocumentQATool, using ChatOpenAI with default model")
                llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

            # Truncate if too long
            if len(text) > self.text_limit:
                text = text[: self.text_limit] + "\n\n... (text truncated)"

            prompt = f"""Summarize the following document content:

{preview_first(text, 5000)}

Provide a concise summary highlighting the key points:"""

            response = llm.invoke(prompt)
        except Exception as e:
            logger.exception("Failed to summarize")
            return f"Failed to generate summary: {e}"
        else:
            return response.content

    def _answer_question(self, text: str, question: str) -> str:
        """Answer question about text using LLM.

        Args:
            text: Document text.
            question: Question to answer.

        Returns:
            Answer to question.
        """
        try:
            # Use Soothe config if available, otherwise fallback to ChatOpenAI
            if self.config is not None:
                llm = self.config.create_chat_model("fast")
            else:
                from langchain_openai import ChatOpenAI

                logger.warning("No config provided to DocumentQATool, using ChatOpenAI with default model")
                llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

            # Truncate if too long
            if len(text) > self.text_limit:
                text = text[: self.text_limit] + "\n\n... (text truncated)"

            prompt = f"""Based on the following document content, answer the question.

Document content:
{preview_first(text, 10000)}

Question: {question}

Answer:"""

            response = llm.invoke(prompt)
        except Exception as e:
            logger.exception("Failed to answer question")
            return f"Failed to generate answer: {e}"
        else:
            return response.content

    def _run(self, document_path: str, question: str | None = None) -> str:
        """Analyze document and answer questions.

        Args:
            document_path: Path or URL to document.
            question: Optional question about document.

        Returns:
            Summary or answer to question.
        """
        # Check cache
        cache_path = self._get_cache_path(document_path)
        if cache_path and cache_path.exists():
            logger.info("Using cached document: %s", document_path)
            text = cache_path.read_text()
        else:
            # Download if URL
            local_path = document_path
            try:
                local_path = self._download_if_url(document_path)
            except Exception as e:
                return f"Error: Failed to download document: {e}"

            # Parse document
            try:
                text = self._parse_document(local_path)

                # Cache parsed text
                if cache_path:
                    cache_path.write_text(text)

            except ImportError as e:
                return f"Error: {e}"
            except Exception as e:
                logger.exception("Failed to parse document")
                return f"Error parsing document: {e}"

        # Truncate text
        if len(text) > self.text_limit:
            text = text[: self.text_limit] + "\n\n... (document truncated)"

        # Generate summary or answer question
        if question:
            return self._answer_question(text, question)
        return self._summarize_text(text)

    async def _arun(self, document_path: str, question: str | None = None) -> str:
        return self._run(document_path, question)


class ExtractTextTool(BaseTool):
    """Extract raw text from document."""

    name: str = "extract_text"
    description: str = (
        "Extract raw text from a document. "
        "Provide `document_path` (local path or URL). "
        "Returns extracted text without processing."
    )

    text_limit: int = Field(default=100000)

    def _run(self, document_path: str) -> str:
        """Extract text from document.

        Args:
            document_path: Path to document.

        Returns:
            Extracted text.
        """
        try:
            qa_tool = DocumentQATool(text_limit=self.text_limit)
            # Parse without LLM
            local_path = qa_tool._download_if_url(document_path)
            text = qa_tool._parse_document(local_path)

            if len(text) > self.text_limit:
                text = text[: self.text_limit] + "\n\n... (document truncated)"

        except Exception as e:
            logger.exception("Failed to extract text")
            return f"Error extracting text: {e}"
        else:
            return text

    async def _arun(self, document_path: str) -> str:
        return self._run(document_path)


class GetDocumentInfoTool(BaseTool):
    """Get document metadata."""

    name: str = "get_document_info"
    description: str = (
        "Get metadata about a document. "
        "Provide `document_path` (local path or URL). "
        "Returns file size, format, page count (for PDF), etc."
    )

    def _run(self, document_path: str) -> dict[str, Any]:
        """Get document metadata.

        Args:
            document_path: Path to document.

        Returns:
            Dict with metadata.
        """
        path = Path(document_path)

        if not path.exists():
            return {"error": f"Document not found: {document_path}"}

        if not path.is_file():
            return {"error": f"Not a file: {document_path}"}

        stat = path.stat()
        suffix = path.suffix.lower()

        info = {
            "path": str(path),
            "name": path.name,
            "format": suffix,
            "size_bytes": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 2),
            "modified": stat.st_mtime,
        }

        # PDF-specific info
        if suffix == ".pdf":
            try:
                import fitz

                doc = fitz.open(document_path)
                info["page_count"] = doc.page_count
                info["pdf_version"] = doc.metadata.get("format", "Unknown")
                info["title"] = doc.metadata.get("title", "")
                info["author"] = doc.metadata.get("author", "")
                doc.close()

            except ImportError:
                info["pdf_info_error"] = "PyMuPDF not installed"
            except Exception as e:
                info["pdf_info_error"] = str(e)

        return info

    async def _arun(self, document_path: str) -> dict[str, Any]:
        return self._run(document_path)


def create_document_tools(config: Any = None) -> list[BaseTool]:
    """Create document parsing tools.

    Args:
        config: Optional SootheConfig for model creation.

    Returns:
        List containing DocumentQATool, ExtractTextTool, and GetDocumentInfoTool.
    """
    return [
        DocumentQATool(config=config),
        ExtractTextTool(),
        GetDocumentInfoTool(),
    ]
