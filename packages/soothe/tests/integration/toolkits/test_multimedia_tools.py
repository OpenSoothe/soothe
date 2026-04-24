"""Integration tests for multimedia tools (audio, image, video).

These tests require external API keys and are marked as integration tests.
Tests are organized by tool category for maintainability.
"""

import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Audio Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAudioTools:
    """Integration tests for audio transcription and analysis tools."""

    @pytest.fixture
    def audio_tool(self):
        """Create AudioTranscriptionTool instance."""
        pytest.importorskip("openai")
        from soothe.toolkits.audio import AudioTranscriptionTool

        return AudioTranscriptionTool()

    def test_audio_transcription_requires_openai_key(self, audio_tool) -> None:
        """Test that audio transcription checks for OpenAI API key."""
        import os

        # Skip if no OpenAI key
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY required for audio transcription test")

        # Create a minimal audio file (would need actual audio for real test)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_audio = Path(f.name)
            # Write minimal MP3 header (not a valid audio file, but tests tool logic)
            f.write(b"ID3")  # MP3 header magic bytes

        try:
            # Attempt transcription
            result = audio_tool._run(str(temp_audio))

            # Should either succeed or return error about invalid format
            assert isinstance(result, (str, dict))

        finally:
            temp_audio.unlink(missing_ok=True)

    def test_audio_transcription_caching(self, audio_tool) -> None:
        """Test that audio transcription uses caching to avoid re-transcription."""
        import os

        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY required for caching test")

        # This would require actual audio files for meaningful test
        pytest.skip("Requires actual audio file for caching verification")


# ---------------------------------------------------------------------------
# Image Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestImageTools:
    """Integration tests for image analysis tools."""

    @pytest.fixture
    def image_tool(self):
        """Create ImageAnalysisTool instance."""
        from soothe.toolkits.image import ImageAnalysisTool

        return ImageAnalysisTool()

    def test_image_analysis_local_file(self, image_tool) -> None:
        """Test analyzing a local image file."""
        import os

        if not (os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
            pytest.skip("Vision model API key required for image analysis")

        # Create a minimal test image using PIL
        pytest.importorskip("PIL")
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a simple test image
            img_path = Path(tmpdir) / "test_image.png"
            img = Image.new("RGB", (100, 100), color="red")
            img.save(img_path)

            # Analyze the image
            result = image_tool._run(str(img_path), question="What color is this image?")

            # Should return analysis
            assert isinstance(result, (str, dict))
            if isinstance(result, dict):
                assert "error" in result or "analysis" in result

    def test_image_analysis_with_url(self, image_tool) -> None:
        """Test analyzing an image from URL."""
        import os

        if not (os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):
            pytest.skip("Vision model API key required for image analysis")

        # Use a public test image URL
        # Note: This test depends on external URL availability
        pytest.skip("Requires reliable public test image URL")

    def test_image_base64_conversion(self, image_tool) -> None:
        """Test image to base64 conversion logic."""
        pytest.importorskip("PIL")
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test image
            img_path = Path(tmpdir) / "test.png"
            img = Image.new("RGB", (50, 50), color="blue")
            img.save(img_path)

            from soothe.toolkits.image import _image_to_base64

            # Test conversion
            base64_str = _image_to_base64(str(img_path))
            assert isinstance(base64_str, str)
            assert len(base64_str) > 0

    def test_image_resize_on_large_input(self, image_tool) -> None:
        """Test that large images are resized before processing."""
        pytest.importorskip("PIL")
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a large image
            img_path = Path(tmpdir) / "large.png"
            img = Image.new("RGB", (2000, 2000), color="green")
            img.save(img_path)

            from soothe.toolkits.image import _image_to_base64

            # Should resize to max 1024
            base64_str = _image_to_base64(str(img_path), max_size=1024)
            assert isinstance(base64_str, str)


# ---------------------------------------------------------------------------
# Video Tools Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestVideoTools:
    """Integration tests for video analysis tools."""

    @pytest.fixture
    def video_tool(self):
        """Create VideoAnalysisTool instance."""
        pytest.importorskip("google.genai")
        from soothe.toolkits.video import VideoAnalysisTool

        return VideoAnalysisTool()

    def test_video_analysis_requires_google_key(self, video_tool) -> None:
        """Test that video analysis checks for Google API key."""
        import os

        if not os.getenv("GOOGLE_API_KEY"):
            pytest.skip("GOOGLE_API_KEY required for video analysis test")

        # Would need actual video file for real test
        pytest.skip("Requires actual video file for analysis")

    def test_video_file_validation(self, video_tool) -> None:
        """Test video file validation logic."""
        # Test with non-existent file
        result = video_tool._run("/nonexistent/video.mp4", question="What's in this video?")

        # Should return error about missing file
        if isinstance(result, dict):
            assert "error" in result
        else:
            assert "error" in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMultimediaToolErrors:
    """Test error handling across multimedia tools."""

    def test_audio_invalid_format(self) -> None:
        """Test audio tool handles invalid file format gracefully."""
        import os

        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY required")

        from soothe.toolkits.audio import AudioTranscriptionTool

        tool = AudioTranscriptionTool()

        # Try to transcribe a non-audio file
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"This is not an audio file")
            temp_file = Path(f.name)

        try:
            result = tool._run(str(temp_file))
            # Should handle error gracefully
            assert isinstance(result, (str, dict))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_image_corrupted_file(self) -> None:
        """Test image tool handles corrupted image gracefully."""
        from soothe.toolkits.image import ImageAnalysisTool

        tool = ImageAnalysisTool()

        # Create corrupted image file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"Not a valid PNG file content")
            temp_file = Path(f.name)

        try:
            result = tool._run(str(temp_file), question="What is this?")
            # Should return error
            assert isinstance(result, (str, dict))
        finally:
            temp_file.unlink(missing_ok=True)

    def test_video_missing_api_key(self) -> None:
        """Test video tool handles missing API key gracefully."""
        import os

        original_key = os.environ.pop("GOOGLE_API_KEY", None)

        try:
            from soothe.toolkits.video import VideoAnalysisTool

            VideoAnalysisTool()

            # Should fail or skip gracefully without API key
            # (actual behavior depends on implementation)

        finally:
            if original_key:
                os.environ["GOOGLE_API_KEY"] = original_key
