"""Audio transcription tool using OpenAI Whisper.

Ported from noesium's audio toolkit. No langchain equivalent.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field


class AudioTranscriptionTool(BaseTool):
    """Transcribe audio files using OpenAI Whisper API."""

    name: str = "transcribe_audio"
    description: str = (
        "Transcribe an audio file to text using OpenAI Whisper. "
        "Provide `audio_path` (local path or URL). "
        "Returns the transcribed text with metadata."
    )
    cache_dir: str = Field(default="")

    def _get_cache_path(self, audio_path: str) -> Path | None:
        if not self.cache_dir:
            return None
        cache = Path(self.cache_dir)
        cache.mkdir(parents=True, exist_ok=True)
        md5 = hashlib.md5(audio_path.encode()).hexdigest()  # noqa: S324
        return cache / f"{md5}.json"

    def _download_if_url(self, audio_path: str) -> str:
        if audio_path.startswith(("http://", "https://")):
            import requests

            resp = requests.get(audio_path, timeout=60)
            resp.raise_for_status()
            suffix = Path(audio_path).suffix or ".mp3"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(resp.content)
            tmp.close()
            return tmp.name
        return audio_path

    def _run(self, audio_path: str) -> dict[str, Any]:
        from openai import OpenAI

        cache_path = self._get_cache_path(audio_path)
        if cache_path and cache_path.exists():
            return json.loads(cache_path.read_text())

        local_path = self._download_if_url(audio_path)
        client = OpenAI()
        with Path(local_path).open("rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
            )

        output = {
            "text": result.text,
            "language": getattr(result, "language", None),
            "duration": getattr(result, "duration", None),
        }

        if cache_path:
            cache_path.write_text(json.dumps(output, ensure_ascii=False))

        return output

    async def _arun(self, audio_path: str) -> dict[str, Any]:
        return self._run(audio_path)


def create_audio_tools() -> list[BaseTool]:
    """Create audio transcription tools.

    Returns:
        List containing the `AudioTranscriptionTool`.
    """
    return [AudioTranscriptionTool()]
