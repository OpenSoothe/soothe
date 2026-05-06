"""Integration tests for Video tools functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soothe.toolkits.video import VideoAnalysisTool, VideoInfoTool


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

                # Mock file retrieval (polling for active state)
                mock_client.files.get.return_value = mock_video_file

                # Mock model and response
                mock_model = MagicMock()
                mock_response = MagicMock()
                mock_response.text = "This is a test video analysis result."
                mock_model.generate_content.return_value = mock_response
                mock_client.models.get.return_value = mock_model

                # Mock genai.Client constructor
                mock_genai.Client.return_value = mock_client

                # Run tool
                result = tool._run(str(file_path))

                # Verify result
                assert "test video analysis result" in result
                assert "Error" not in result

                # Verify workflow
                mock_client.files.upload.assert_called_once()
                mock_client.files.get.assert_called()
                mock_model.generate_content.assert_called_once()

                # Verify cleanup
                mock_client.files.delete.assert_called_once_with(name="uploaded_file")

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
