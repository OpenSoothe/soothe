"""Audio transcription and analysis with OpenAI Whisper.

Enhanced version with caching and audio Q&A.
Ported from noesium's audio_toolkit.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AudioTranscriptionTool(BaseTool):
    """Audio transcription using OpenAI Whisper.

    Includes MD5-based caching to avoid re-transcribing.
    """

    name: str = "transcribe_audio"
    description: str = (
        "Transcribe audio file to text using OpenAI Whisper. "
        "Provide `audio_path` (local path or URL). "
        "Returns transcription with metadata."
    )

    cache_dir: str = Field(default="")

    def _get_cache_path(self, audio_path: str) -> Path | None:
        """Get cache file path for audio transcription."""
        if not self.cache_dir:
            return None

        cache = Path(self.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        md5 = hashlib.md5(audio_path.encode()).hexdigest()
        return cache / f"{md5}.json"

    def _download_if_url(self, audio_path: str) -> str:
        """Download audio file if URL, return local path."""
        if not audio_path.startswith(("http://", "https://")):
            return audio_path

        try:
            import requests

            resp = requests.get(audio_path, timeout=60)
            resp.raise_for_status()

            suffix = Path(audio_path).suffix or ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            logger.info("Downloaded audio from URL: %s", audio_path)
        except ImportError:
            msg = "requests not installed for URL downloading"
            raise RuntimeError(msg) from None
        else:
            return tmp_path

    def _transcribe_openai(self, audio_path: str) -> dict[str, Any]:
        """Transcribe using OpenAI Whisper."""
        from openai import OpenAI

        client = OpenAI()

        with Path(audio_path).open("rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
            )

        return {
            "text": result.text,
            "language": getattr(result, "language", None),
            "duration": getattr(result, "duration", None),
            "provider": "openai",
        }

    def _run(self, audio_path: str) -> dict[str, Any]:
        """Transcribe audio file.

        Args:
            audio_path: Local path or URL to audio file.

        Returns:
            Dict with 'text', 'provider', and optional metadata or 'error'.
        """
        # Check cache
        cache_path = self._get_cache_path(audio_path)
        if cache_path and cache_path.exists():
            logger.info("Using cached transcription for: %s", audio_path)
            return json.loads(cache_path.read_text())

        # Download if URL
        local_path = audio_path
        _ = audio_path.startswith(("http://", "https://"))  # Check if URL
        try:
            local_path = self._download_if_url(audio_path)
        except Exception as e:
            return {"error": f"Failed to download audio: {e}"}

        # Transcribe
        try:
            result = self._transcribe_openai(local_path)

            # Cache result
            if cache_path and "error" not in result:
                cache_path.write_text(json.dumps(result, ensure_ascii=False))

        except Exception as e:
            logger.exception("Transcription failed")
            return {"error": f"Transcription failed: {e}"}
        else:
            return result

    async def _arun(self, audio_path: str) -> dict[str, Any]:
        return self._run(audio_path)


class AudioQATool(BaseTool):
    """Audio content Q&A using LLM.

    Transcribes audio and answers questions about the content.
    """

    name: str = "audio_qa"
    description: str = (
        "Answer questions about audio content. "
        "Provide `audio_path` (local path or URL) and `question` (question about the audio). "
        "Returns answer based on audio transcription."
    )

    cache_dir: str = Field(default="")
    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    def _run(self, audio_path: str, question: str) -> str:
        """Answer question about audio content.

        Args:
            audio_path: Path to audio file.
            question: Question about the content.

        Returns:
            Answer to the question.
        """
        # Transcribe audio
        transcribe_tool = AudioTranscriptionTool(cache_dir=self.cache_dir)
        transcription = transcribe_tool._run(audio_path)

        if "error" in transcription:
            return f"Failed to transcribe audio: {transcription['error']}"

        text = transcription.get("text", "")
        if not text:
            return "Audio transcription returned empty text"

        # Use LLM to answer question
        try:
            # Use Soothe config if available, otherwise fallback to ChatOpenAI
            if self.config is not None:
                llm = self.config.create_chat_model("fast")
            else:
                from langchain_openai import ChatOpenAI

                logger.warning(
                    "No config provided to AudioQATool, using ChatOpenAI with default model"
                )
                llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

            prompt = f"""Based on the following audio transcription, answer the question.

Transcription:
{text}

Question: {question}

Answer:"""

            response = llm.invoke(prompt)
        except Exception as e:
            logger.exception("Failed to answer question")
            return f"Failed to generate answer: {e}"
        else:
            return response.content

    async def _arun(self, audio_path: str, question: str) -> str:
        return self._run(audio_path, question)


class AudioToolkit:
    """Toolkit for audio transcription and analysis."""

    def __init__(self, *, config: Any = None) -> None:
        """Initialize the toolkit.

        Args:
            config: Optional SootheConfig for model creation.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List containing AudioTranscriptionTool and AudioQATool.
        """
        return [
            AudioTranscriptionTool(),
            AudioQATool(config=self._config),
        ]


@plugin(
    name="audio",
    version="1.0.0",
    description="Audio transcription and analysis",
    trust_level="built-in",
)
class AudioPlugin:
    """Audio transcription and analysis tools plugin.

    Provides transcribe_audio and audio_qa tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with config.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = AudioToolkit(config=context.config)
        self._tools = toolkit.get_tools()

        context.logger.info("Loaded %d audio tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of audio tool instances.
        """
        return self._tools
