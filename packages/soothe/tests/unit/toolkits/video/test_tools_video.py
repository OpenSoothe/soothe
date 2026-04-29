"""Tests for Video tools functionality."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.toolkits.video import VideoAnalysisTool, VideoInfoTool


class TestVideoAnalysisTool:
    """Test VideoAnalysisTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = VideoAnalysisTool()

        assert tool.name == "analyze_video"
        assert "analyze" in tool.description.lower()
        assert "video" in tool.description.lower()

    def test_default_configuration(self) -> None:
        """Test default configuration."""
        tool = VideoAnalysisTool()

        assert tool.model_name == "gemini-1.5-pro"
        assert tool.max_file_size == 2 * 1024 * 1024 * 1024  # 2GB
        assert tool.google_api_key is None

    def test_custom_configuration(self) -> None:
        """Test custom configuration."""
        tool = VideoAnalysisTool(
            google_api_key="test_key",
            model_name="gemini-1.5-flash",
            max_file_size=1024 * 1024 * 1024,  # 1GB
        )

        assert tool.google_api_key == "test_key"
        assert tool.model_name == "gemini-1.5-flash"
        assert tool.max_file_size == 1024 * 1024 * 1024

    def test_get_api_key_from_instance(self) -> None:
        """Test getting API key from instance."""
        tool = VideoAnalysisTool(google_api_key="test_key")

        result = tool._get_api_key()

        assert result == "test_key"

    def test_get_api_key_from_environment(self) -> None:
        """Test getting API key from environment."""
        tool = VideoAnalysisTool()

        with patch.dict("os.environ", {"GOOGLE_API_KEY": "env_key"}):
            result = tool._get_api_key()

            assert result == "env_key"


class TestVideoAnalysisToolValidation:
    """Test video file validation."""

    def test_validate_nonexistent_file(self) -> None:
        """Test validation of non-existent file."""
        tool = VideoAnalysisTool()

        _path, error = tool._validate_file("/nonexistent/video.mp4")

        assert error is not None
        assert "not found" in error.lower()

    def test_validate_directory(self) -> None:
        """Test validation of directory path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = VideoAnalysisTool()

            _path, error = tool._validate_file(temp_dir)

            assert error is not None
            assert "not a file" in error.lower()

    def test_validate_oversized_file(self) -> None:
        """Test validation of oversized file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a file that's too large (simulated)
            file_path = Path(temp_dir) / "large.mp4"
            file_path.write_bytes(b"x" * 100)

            tool = VideoAnalysisTool(max_file_size=10)  # Very small limit

            _path, error = tool._validate_file(str(file_path))

            assert error is not None
            assert "too large" in error.lower()

    def test_validate_valid_file(self) -> None:
        """Test validation of valid file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "video.mp4"
            file_path.write_bytes(b"video content")

            tool = VideoAnalysisTool()

            path, error = tool._validate_file(str(file_path))

            assert error is None
            # macOS: tmp under /var/folders often resolves to /private/var/... via backend
            assert path == Path(os.path.realpath(file_path))


class TestVideoAnalysisToolExecution:
    """Test video analysis execution."""

    def test_run_without_api_key(self) -> None:
        """Test execution without API key."""
        tool = VideoAnalysisTool()

        with patch.object(tool, "_get_api_key", return_value=None):
            result = tool._run("video.mp4")

            assert "Error" in result
            assert "API key required" in result

    def test_run_with_nonexistent_file(self) -> None:
        """Test execution with non-existent file."""
        tool = VideoAnalysisTool(google_api_key="test_key")

        result = tool._run("/nonexistent/video.mp4")

        assert "Error" in result

    def test_run_without_google_genai(self) -> None:
        """Test execution without google-genai library."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "video.mp4"
            file_path.write_bytes(b"video content")

            tool = VideoAnalysisTool(google_api_key="test_key")

            with patch.dict("sys.modules", {"google.genai": None, "google": None}):
                result = tool._run(str(file_path))

                assert "Error" in result
                assert "google-genai not installed" in result


class TestVideoInfoTool:
    """Test VideoInfoTool functionality."""

    def test_tool_metadata(self) -> None:
        """Test tool metadata."""
        tool = VideoInfoTool()

        assert tool.name == "get_video_info"
        assert "info" in tool.description.lower() or "metadata" in tool.description.lower()

    def test_get_info_nonexistent_file(self) -> None:
        """Test getting info for non-existent file."""
        tool = VideoInfoTool()

        result = tool._run("/nonexistent/video.mp4")

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_info_valid_file(self) -> None:
        """Test getting info for valid file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "video.mp4"
            file_path.write_bytes(b"video content")

            tool = VideoInfoTool()

            result = tool._run(str(file_path))

            assert result["path"] == os.path.realpath(str(file_path))
            assert result["name"] == "video.mp4"
            assert result["suffix"] == ".mp4"
            assert "size_bytes" in result
            assert "size_mb" in result

    def test_get_info_directory(self) -> None:
        """Test getting info for directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            tool = VideoInfoTool()

            result = tool._run(temp_dir)

            assert "error" in result
            assert "not a file" in result["error"].lower()


class TestVideoToolIntegration:
    """Integration tests for Video tools."""

    @pytest.mark.skipif(
        not pytest.importorskip("google.genai", reason="google-genai not installed"),
        reason="Google API key required for integration test",
    )
    def test_real_video_analysis(self) -> None:
        """Test real video analysis (requires Google API key)."""
        # This test would require an actual video file and API key
        # Skip if not available
        pytest.skip("Integration test requires video file and Google API key")

    def test_video_analysis_workflow(self) -> None:
        """Test complete video analysis workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "video.mp4"
            file_path.write_bytes(b"video content")

            tool = VideoAnalysisTool(google_api_key="test_key")

            # Mock the entire Google Gemini workflow
            with patch("google.genai") as mock_genai:
                # Mock client
                mock_client = MagicMock()

                # Mock file upload
                mock_video_file = MagicMock()
                mock_video_file.state.name = "ACTIVE"
                mock_video_file.name = "uploaded_file"
                mock_client.files.upload.return_value = mock_video_file
                mock_client.files.get.return_value = mock_video_file

                # Mock model
                mock_model = MagicMock()
                mock_response = MagicMock()
                mock_response.text = "This video shows a test scene."
                mock_model.generate_content.return_value = mock_response
                mock_client.get_model.return_value = mock_model

                mock_genai.Client.return_value = mock_client

                result = tool._run(str(file_path), "Describe this video")

                assert "test scene" in result

    def test_video_info_workflow(self) -> None:
        """Test complete video info workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test video file
            file_path = Path(temp_dir) / "test.mp4"
            file_path.write_bytes(b"x" * 1024)

            tool = VideoInfoTool()

            result = tool._run(str(file_path))

            assert result["name"] == "test.mp4"
            assert result["suffix"] == ".mp4"
            assert result["size_bytes"] == 1024
