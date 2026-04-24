"""Integration tests for Python session persistence (RFC-0016 Phase 3)."""

import pytest

from soothe.toolkits._internal.python_session_manager import get_session_manager
from soothe.toolkits.execution import RunPythonTool

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestPythonSessionPersistence:
    """Test session persistence across calls."""

    def test_variable_persistence(self):
        """Test that variables persist across calls."""
        tool = RunPythonTool()
        session_id = "test_session_1"

        # Call 1: Create variable
        result1 = tool._run(code="x = 42", session_id=session_id)
        assert result1["success"]

        # Call 2: Use variable
        result2 = tool._run(code="x * 2", session_id=session_id)
        assert result2["success"]
        assert "84" in str(result2["result"])

        # Cleanup
        manager = get_session_manager()
        manager.cleanup(session_id)

    def test_import_persistence(self):
        """Test that imports persist across calls."""
        tool = RunPythonTool()
        session_id = "test_session_2"

        # Call 1: Import module
        result1 = tool._run(code="import math", session_id=session_id)
        assert result1["success"]

        # Call 2: Use imported module
        result2 = tool._run(code="math.sqrt(16)", session_id=session_id)
        assert result2["success"]
        assert "4" in str(result2["result"])

        # Cleanup
        manager = get_session_manager()
        manager.cleanup(session_id)

    def test_dataframe_workflow(self):
        """Test realistic pandas workflow."""
        tool = RunPythonTool()
        session_id = "test_session_3"

        # Step 1: Import pandas
        result = tool._run(code="import pandas as pd", session_id=session_id)
        assert result["success"]

        # Step 2: Create DataFrame
        result = tool._run(
            code="df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})",
            session_id=session_id,
        )
        assert result["success"]

        # Step 3: Use DataFrame
        result = tool._run(code="df['a'].sum()", session_id=session_id)
        assert result["success"]
        assert "6" in str(result["result"])

        # Step 4: Continue analysis
        result = tool._run(code="df['c'] = df['a'] + df['b']", session_id=session_id)
        assert result["success"]

        result = tool._run(code="df['c'].mean()", session_id=session_id)
        assert result["success"]

        # Cleanup
        manager = get_session_manager()
        manager.cleanup(session_id)

    def test_session_isolation(self):
        """Test that sessions are isolated from each other."""
        tool = RunPythonTool()

        # Session 1: Create variable x
        session1 = "isolated_session_1"
        tool._run(code="x = 100", session_id=session1)

        # Session 2: Try to access x (should not exist)
        session2 = "isolated_session_2"
        result = tool._run(code="x", session_id=session2)
        assert not result["success"]
        assert "NameError" in str(result["error"])

        # Cleanup
        manager = get_session_manager()
        manager.cleanup(session1)
        manager.cleanup(session2)

    def test_session_cleanup(self):
        """Test that session cleanup works."""
        tool = RunPythonTool()
        manager = get_session_manager()
        session_id = "cleanup_test_session"

        # Create session
        tool._run(code="x = 42", session_id=session_id)
        assert session_id in manager.list_sessions()

        # Cleanup
        manager.cleanup(session_id)
        assert session_id not in manager.list_sessions()

    def test_error_recovery(self):
        """Test that errors don't break session."""
        tool = RunPythonTool()
        session_id = "error_recovery_session"

        # Create variable
        tool._run(code="x = 10", session_id=session_id)

        # Execute code with error
        result = tool._run(code="1 / 0", session_id=session_id)
        assert not result["success"]
        assert "ZeroDivisionError" in str(result["error"])

        # Session should still work
        result = tool._run(code="x * 2", session_id=session_id)
        assert result["success"]
        assert "20" in str(result["result"])

        # Cleanup
        manager = get_session_manager()
        manager.cleanup(session_id)


class TestSessionManager:
    """Test session manager directly."""

    def test_singleton_pattern(self):
        """Test that get_session_manager returns singleton."""
        manager1 = get_session_manager()
        manager2 = get_session_manager()
        assert manager1 is manager2

    def test_session_count(self):
        """Test session counting."""
        manager = get_session_manager()
        initial_count = manager.get_session_count()

        # Create sessions
        manager.get_or_create("count_test_1")
        manager.get_or_create("count_test_2")
        assert manager.get_session_count() == initial_count + 2

        # Cleanup
        manager.cleanup_all()
        assert manager.get_session_count() == 0

    def test_list_sessions(self):
        """Test listing sessions."""
        manager = get_session_manager()

        # Create sessions
        manager.get_or_create("list_test_1")
        manager.get_or_create("list_test_2")

        sessions = manager.list_sessions()
        assert "list_test_1" in sessions
        assert "list_test_2" in sessions

        # Cleanup
        manager.cleanup_all()
