"""Test that filesystem_middleware.workspace_root with ~ is correctly expanded."""

from pathlib import Path

from soothe_nano.config.settings import SootheConfig
from soothe_nano.utils import expand_path


def test_workspace_root_tilde_expansion():
    """Test that workspace_root with ~ is expanded correctly in config."""
    config_dict = {
        "filesystem_middleware": {
            "workspace_root": "~/.soothe/test",
        },
    }
    config = SootheConfig(**config_dict)

    # Verify the workspace_root is stored correctly
    assert config.filesystem_middleware.workspace_root == "~/.soothe/test"

    # Verify that expand_path resolves it correctly
    expanded = expand_path(config.filesystem_middleware.workspace_root)

    # Should not contain literal tilde
    assert "~" not in str(expanded)

    # Should be an absolute path
    assert expanded.is_absolute()

    # Should be under the user's home directory
    home = Path.home()
    assert str(expanded).startswith(str(home))


def test_workspace_dir_expansion_in_resolver():
    """Test that workspace_root is properly expanded when used in resolver context."""
    config_dict = {
        "filesystem_middleware": {
            "workspace_root": "~/.soothe/test",
        },
    }
    config = SootheConfig(**config_dict)

    # The resolved_cwd should expand the tilde
    # We can't directly test resolve_planner without a model, but we can test the path expansion
    expanded = expand_path(config.filesystem_middleware.workspace_root)

    # Verify it doesn't use the wrong home directory (e.g., /Users/dan instead of /Users/xiamingchen)
    import os

    expected_home = os.path.expanduser("~")
    assert str(expanded).startswith(expected_home)
    assert "/Users/dan" not in str(expanded)  # Should NOT reference wrong user


def test_workspace_dir_absolute_path_unchanged():
    """Test that absolute paths are handled correctly."""
    config_dict = {
        "filesystem_middleware": {
            "workspace_root": "/absolute/path/to/workspace",
        },
    }
    config = SootheConfig(**config_dict)

    expanded = expand_path(config.filesystem_middleware.workspace_root)
    assert expanded == Path("/absolute/path/to/workspace").resolve()


def test_workspace_dir_env_var_expansion():
    """Test that environment variables in workspace_root are expanded."""
    import os

    os.environ["TEST_WORKSPACE"] = "/test/workspace"
    config_dict = {
        "filesystem_middleware": {
            "workspace_root": "$TEST_WORKSPACE/project",
        },
    }
    config = SootheConfig(**config_dict)

    expanded = expand_path(config.filesystem_middleware.workspace_root)
    assert str(expanded).startswith("/test/workspace/project")

    del os.environ["TEST_WORKSPACE"]


def test_workspace_root_property():
    """Test that filesystem_middleware.workspace_root is accessible."""
    config = SootheConfig()

    # Default should be None
    assert config.filesystem_middleware.workspace_root is None

    # Set via filesystem_middleware
    config_dict = {
        "filesystem_middleware": {
            "workspace_root": "/test/workspace",
        },
    }
    config = SootheConfig(**config_dict)
    assert config.filesystem_middleware.workspace_root == "/test/workspace"
