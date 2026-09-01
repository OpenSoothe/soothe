"""Tests for the path validation utilities (S1: path traversal protection)."""

from __future__ import annotations

import pytest

from soothe.workspace.sync.paths import validate_path_component, validate_relative_path


class TestValidatePathComponent:
    """Tests for ``validate_path_component`` — server-generated IDs."""

    @pytest.mark.parametrize(
        "value",
        [
            "abc123",
            "run-123",
            "a" * 64,  # sha256 hex digest
            "a" * 128,  # max length
            "run-abc-123",
            "abc.def",
            "abc_def",
        ],
    )
    def test_valid_components(self, value: str) -> None:
        assert validate_path_component(value, name="test") == value

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "abc/def",  # path separator
            "abc..def",  # double dots (contains ..)
            "abc def",  # space
            "abc\x00def",  # null byte
            "a" * 129,  # too long
            "abc|def",  # special char
            "abc;def",  # special char
            "../etc/passwd",  # traversal
            "/etc/passwd",  # absolute
        ],
    )
    def test_invalid_components(self, value: str) -> None:
        with pytest.raises(ValueError, match="invalid test"):
            validate_path_component(value, name="test")


class TestValidateRelativePath:
    """Tests for ``validate_relative_path`` — artifact paths."""

    @pytest.mark.parametrize(
        "value",
        [
            "output/report.md",
            "input/paper.pdf",
            "working/chunks/abc.bin",
            "report.md",
            "a/b/c/d/e.txt",
            "./report.md",  # normalized to report.md
            "output/../output/report.md",  # normalized
        ],
    )
    def test_valid_paths(self, value: str) -> None:
        result = validate_relative_path(value, name="artifact_path")
        assert ".." not in result.split("/")
        assert not result.startswith("/")

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "/etc/passwd",  # absolute
            "../etc/passwd",  # traversal
            "output/../../../etc/passwd",  # deep traversal
            "abc\x00def",  # null byte
            "a" * 4097,  # too long
            "..",  # just dots
            "../",
        ],
    )
    def test_invalid_paths(self, value: str) -> None:
        with pytest.raises(ValueError):
            validate_relative_path(value, name="artifact_path")
