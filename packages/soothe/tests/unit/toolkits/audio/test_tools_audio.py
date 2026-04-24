"""Tests for Audio tools functionality."""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.toolkits.audio import AudioToolkit, AudioQATool, AudioTranscriptionTool


class TestAudioTranscriptionTool:
    """Test AudioTranscriptionTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = AudioTranscriptionTool()

        assert tool.name == "transcribe_audio"
        assert "transcribe" in tool.description.lower()
        assert "audio" in tool.description.lower()

    def test_create_audio_tools(self) -> None:
        """Test factory function creates all tools."""
        tools = create_audio_tools()

        assert len(tools) == 2
        assert isinstance(tools[0], AudioTranscriptionTool)
        assert isinstance(tools[1], AudioQATool)

    def test_get_cache_path_disabled(self) -> None:
        """Test cache path when caching disabled."""
        tool = AudioTranscriptionTool(cache_dir="")

        result = tool._get_cache_path("/path/to/audio.mp3")

        assert result is None

    def test_get_cache_path_enabled(self) -> None:
        """Test cache path when caching enabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = AudioTranscriptionTool(cache_dir=temp_dir)

            result = tool._get_cache_path("/path/to/audio.mp3")

            assert result is not None
            assert result.parent == Path(temp_dir)
            assert result.suffix == ".json"

    def test_cache_key_is_md5(self) -> None:
        """Test that cache key is MD5 hash."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = AudioTranscriptionTool(cache_dir=temp_dir)

            cache_path = tool._get_cache_path("/path/to/audio.mp3")
            expected_md5 = hashlib.md5(b"/path/to/audio.mp3").hexdigest()

            assert cache_path.name == f"{expected_md5}.json"


class TestAudioTranscriptionToolDownload:
    """Test URL downloading functionality."""

    def test_download_if_url_with_local_path(self) -> None:
        """Test that local paths are returned as-is."""
        tool = AudioTranscriptionTool()

        result = tool._download_if_url("/path/to/audio.mp3")

        assert result == "/path/to/audio.mp3"

    def test_download_if_url_with_url(self) -> None:
        """Test URL downloading."""
        tool = AudioTranscriptionTool()

        # Mock requests
        with patch("requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.content = b"audio content"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = tool._download_if_url("https://example.com/audio.mp3")

            assert result.endswith(".mp3")
            assert Path(result).exists()

            # Cleanup
            Path(result).unlink()

    def test_download_if_url_without_requests(self) -> None:
        """Test URL downloading without requests library."""
        tool = AudioTranscriptionTool()

        with patch.dict("sys.modules", {"requests": None}):
            with pytest.raises(RuntimeError, match="requests not installed"):
                tool._download_if_url("https://example.com/audio.mp3")


class TestAudioTranscriptionToolTranscription:
    """Test transcription functionality."""

    def test_transcribe_openai(self) -> None:
        """Test OpenAI Whisper transcription."""
        tool = AudioTranscriptionTool()

        with patch("openai.OpenAI") as mock_openai:
            # Mock OpenAI client and response
            mock_client = MagicMock()
            mock_result = MagicMock()
            mock_result.text = "Hello, World!"
            mock_result.language = "en"
            mock_result.duration = 10.0
            mock_client.audio.transcriptions.create.return_value = mock_result
            mock_openai.return_value = mock_client

            # Create a real temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(b"audio content")
            tmp.flush()
            tmp.close()

            try:
                result = tool._transcribe_openai(tmp.name)

                assert result["text"] == "Hello, World!"
                assert result["language"] == "en"
                assert result["duration"] == 10.0
                assert result["provider"] == "openai"
            finally:
                Path(tmp.name).unlink()

    def test_transcribe_with_cache(self) -> None:
        """Test transcription with caching."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = AudioTranscriptionTool(cache_dir=temp_dir)

            # Create cached transcription
            import json

            cache_path = tool._get_cache_path("/path/to/audio.mp3")
            cached_data = {"text": "Cached transcription", "provider": "openai"}
            cache_path.write_text(json.dumps(cached_data))

            result = tool._run("/path/to/audio.mp3")

            assert result["text"] == "Cached transcription"


class TestAudioQATool:
    """Test AudioQATool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = AudioQATool()

        assert tool.name == "audio_qa"
        assert "question" in tool.description.lower()
        assert "audio" in tool.description.lower()

    def test_audio_qa_with_transcription(self) -> None:
        """Test audio Q&A with successful transcription."""
        tool = AudioQATool()

        with patch.object(AudioTranscriptionTool, "_run") as mock_transcribe:
            mock_transcribe.return_value = {"text": "This is an audio about Python programming."}

            with patch("langchain_openai.ChatOpenAI") as mock_llm:
                # Mock LLM response
                mock_response = MagicMock()
                mock_response.content = "The audio is about Python programming."
                mock_llm.return_value.invoke.return_value = mock_response

                result = tool._run("/path/to/audio.mp3", "What is this audio about?")

                assert "Python programming" in result

    def test_audio_qa_with_transcription_error(self) -> None:
        """Test audio Q&A with transcription error."""
        tool = AudioQATool()

        with patch.object(AudioTranscriptionTool, "_run") as mock_transcribe:
            mock_transcribe.return_value = {"error": "Transcription failed"}

            result = tool._run("/path/to/audio.mp3", "What is this about?")

            assert "Failed to transcribe" in result

    def test_audio_qa_with_empty_transcription(self) -> None:
        """Test audio Q&A with empty transcription."""
        tool = AudioQATool()

        with patch.object(AudioTranscriptionTool, "_run") as mock_transcribe:
            mock_transcribe.return_value = {"text": ""}

            result = tool._run("/path/to/audio.mp3", "What is this about?")

            assert "empty text" in result.lower()
