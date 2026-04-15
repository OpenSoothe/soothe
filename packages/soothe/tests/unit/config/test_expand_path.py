"""Test expand_path utility function."""

from pathlib import Path

from soothe.utils import expand_path


def test_expand_path_home_directory():
    """Test that ~ is expanded to the user's home directory."""
    result = expand_path("~/.soothe")
    # Should not contain literal tilde
    assert "~" not in str(result)
    # Should be an absolute path
    assert result.is_absolute()


def test_expand_path_env_variable():
    """Test that environment variables are expanded."""
    import os

    os.environ["TEST_VAR"] = "/test/path"
    result = expand_path("$TEST_VAR/project")
    assert str(result) == "/test/path/project"
    del os.environ["TEST_VAR"]


def test_expand_path_already_absolute():
    """Test that absolute paths remain absolute."""
    result = expand_path("/absolute/path/to/file")
    assert result == Path("/absolute/path/to/file").resolve()


def test_expand_path_relative():
    """Test that relative paths are resolved to absolute."""
    result = expand_path("./relative/path")
    assert result.is_absolute()
    assert "relative/path" in str(result) or "relative" in str(result)


def test_expand_path_with_path_object():
    """Test that Path objects are handled correctly."""
    path_obj = Path("~/.soothe")
    result = expand_path(path_obj)
    assert "~" not in str(result)
    assert result.is_absolute()
