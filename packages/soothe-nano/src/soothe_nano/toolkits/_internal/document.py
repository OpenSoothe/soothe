"""Document parsing and Q&A with multi-format support.

Ported from noesium's document_toolkit.py.
Uses PyMuPDF for PDF parsing and docx2txt for DOCX.

IG-405: Uses backend_ops for virtual mode file operations.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.toolkits._internal.backend_ops import (
    backend_file_exists,
    backend_file_stat,
    backend_mkdir,
    backend_read_file,
    backend_write_file,
)
from soothe_nano.utils.text_preview import preview_first

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SOOTHE_INSTALL_HINT = "pip install -U soothe"


def _get_cache_path(document_path: str, cache_dir: str = "", config: Any = None) -> Path | None:
    """Get cache file path for parsed document (IG-405: virtual-aware)."""
    if not cache_dir:
        return None

    cache = Path(cache_dir)
    backend_mkdir(cache, config=config)
    md5 = hashlib.md5(document_path.encode()).hexdigest()
    return cache / f"{md5}.txt"


def _download_if_url(document_path: str) -> str:
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
    except Exception as exc:
        msg = f"Failed to download document from URL: {exc}"
        raise RuntimeError(msg) from exc
    else:
        return tmp_path


def _parse_pdf_pymupdf(file_path: str) -> str:
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
        msg = f"PyMuPDF not installed. Install with: {_SOOTHE_INSTALL_HINT}"
        raise ImportError(msg) from None


def _parse_docx(file_path: str) -> str:
    """Parse DOCX using docx2txt.

    Args:
        file_path: Path to DOCX file.

    Returns:
        Extracted text.

    Raises:
        ImportError: If docx2txt is not installed.
    """
    try:
        import docx2txt

        text = docx2txt.process(file_path)
    except ImportError:
        msg = f"docx2txt not installed. Install with: {_SOOTHE_INSTALL_HINT}"
        raise ImportError(msg) from None
    else:
        return text or ""


def _parse_document(document_path: str) -> str:
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
        return _parse_pdf_pymupdf(document_path)

    # Word documents
    if suffix == ".docx":
        return _parse_docx(document_path)

    # Text files
    if suffix in {".txt", ".md", ".rst", ".log"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    # JSON
    if suffix == ".json":
        import json

        return json.dumps(json.loads(path.read_text()), indent=2)

    # Unsupported format
    msg = f"Unsupported document format: {suffix}. Supported: PDF, DOCX, TXT, MD, RST, JSON"
    raise ValueError(msg)


def _summarize_text(text: str, config: Any = None, text_limit: int = 100000) -> str:
    """Summarize text using LLM.

    Args:
        text: Text to summarize.
        config: Optional SootheConfig for model creation.
        text_limit: Max characters to process.

    Returns:
        Summary.
    """
    try:
        # Use Soothe config if available, otherwise fallback to ChatOpenAI
        if config is not None:
            llm = config.create_chat_model("fast")
        else:
            from langchain_openai import ChatOpenAI

            logger.warning("No config provided, using ChatOpenAI with default model")
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        # Truncate if too long
        if len(text) > text_limit:
            text = text[:text_limit] + "\n\n... (text truncated)"

        prompt = f"""Summarize the following document content:

{preview_first(text, 5000)}

Provide a concise summary highlighting the key points:"""

        response = llm.invoke(prompt)
    except Exception as e:
        logger.exception("Failed to summarize")
        return f"Failed to generate summary: {e}"
    else:
        return response.content


def _answer_question(text: str, question: str, config: Any = None, text_limit: int = 100000) -> str:
    """Answer question about text using LLM.

    Args:
        text: Document text.
        question: Question to answer.
        config: Optional SootheConfig for model creation.
        text_limit: Max characters to process.

    Returns:
        Answer to question.
    """
    try:
        # Use Soothe config if available, otherwise fallback to ChatOpenAI
        if config is not None:
            llm = config.create_chat_model("fast")
        else:
            from langchain_openai import ChatOpenAI

            logger.warning("No config provided, using ChatOpenAI with default model")
            llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        # Truncate if too long
        if len(text) > text_limit:
            text = text[:text_limit] + "\n\n... (text truncated)"

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


def document_qa(
    document_path: str,
    question: str | None = None,
    config: Any = None,
    parser: str = "pymupdf",
    text_limit: int = 100000,
    cache_dir: str = "",
) -> str:
    """Answer questions about document content.

    Parses PDF, Office documents, and text files.
    Supports PyMuPDF (default) for fast extraction.

    IG-405: Uses backend file operations for cache when virtual mode.

    Args:
        document_path: Path or URL to document.
        question: Optional question about document. If None, returns summary.
        config: Optional SootheConfig for model creation and virtual mode.
        parser: Parser to use (default: pymupdf).
        text_limit: Max characters to extract.
        cache_dir: Optional cache directory for parsed documents.

    Returns:
        Summary or answer to question.
    """
    # Check cache (IG-405: pass config for virtual-aware path)
    cache_path = _get_cache_path(document_path, cache_dir, config=config)
    if cache_path and backend_file_exists(cache_path, config=config):
        logger.info("Using cached document: %s", document_path)
        text = backend_read_file(cache_path, config=config)
    else:
        # Download if URL
        local_path = document_path
        try:
            local_path = _download_if_url(document_path)
        except Exception as e:
            return f"Error: Failed to download document: {e}"

        # Parse document
        try:
            text = _parse_document(local_path)

            # Cache parsed text (IG-405: use backend write)
            if cache_path:
                backend_write_file(cache_path, text, config=config)

        except ImportError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to parse document")
            return f"Error parsing document: {e}"

    # Truncate text
    if len(text) > text_limit:
        text = text[:text_limit] + "\n\n... (document truncated)"

    # Generate summary or answer question
    if question:
        return _answer_question(text, question, config, text_limit)
    return _summarize_text(text, config, text_limit)


def extract_text(document_path: str, text_limit: int = 100000) -> str:
    """Extract raw text from a document.

    Args:
        document_path: Path or URL to document.
        text_limit: Max characters to extract.

    Returns:
        Extracted text.
    """
    try:
        # Parse without LLM
        local_path = _download_if_url(document_path)
        text = _parse_document(local_path)

        if len(text) > text_limit:
            text = text[:text_limit] + "\n\n... (document truncated)"

    except Exception as e:
        logger.exception("Failed to extract text")
        return f"Error extracting text: {e}"
    else:
        return text


def get_document_info(document_path: str, config: Any = None) -> dict[str, Any]:
    """Get metadata about a document.

    IG-405: Uses backend file operations when virtual mode.

    Args:
        document_path: Path to document.
        config: Optional SootheConfig for virtual mode detection.

    Returns:
        Dict with metadata including file size, format, page count (for PDF), etc.
    """
    path = Path(document_path)

    if not backend_file_exists(path, config=config):
        return {"error": f"Document not found: {document_path}"}

    # IG-405: Use backend for stat when virtual mode
    stat_info = backend_file_stat(path, config=config)
    if not stat_info.get("is_file", True):
        return {"error": f"Not a file: {document_path}"}

    suffix = path.suffix.lower()

    info = {
        "path": str(path),
        "name": path.name,
        "format": suffix,
        "size_bytes": stat_info["size_bytes"],
        "size_kb": round(stat_info["size_bytes"] / 1024, 2),
        "modified": stat_info["mtime"],
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
