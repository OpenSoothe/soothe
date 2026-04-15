"""Python execution session manager (RFC-0016 Phase 3).

Provides session persistence for Python execution, allowing variables and imports
to persist across multiple run_python calls within the same thread.
"""

from __future__ import annotations

import contextlib
import logging
from threading import Lock, RLock
from typing import Any, Self

logger = logging.getLogger(__name__)


class PythonSessionManager:
    """Singleton manager for persistent Python execution sessions.

    Sessions are keyed by session_id (typically thread_id from LangGraph)
    to maintain isolation between different conversation threads.

    Each session maintains an IPython InteractiveShell instance that persists
    across multiple code executions, allowing variables, imports, and definitions
    to be retained.
    """

    _instance: PythonSessionManager | None = None
    _lock: RLock = RLock()

    def __new__(cls) -> Self:
        """Singleton pattern for global session management."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._sessions: dict[str, Any] = {}
                    cls._instance._session_locks: dict[str, RLock] = {}
        return cls._instance

    def get_or_create(self, session_id: str) -> Any:
        """Get existing session or create new one.

        Args:
            session_id: Unique session identifier (typically thread_id)

        Returns:
            IPython InteractiveShell instance for the session
        """
        if session_id not in self._sessions:
            with self._lock:
                if session_id not in self._sessions:
                    try:
                        from IPython.core.interactiveshell import InteractiveShell

                        # Create new IPython shell (NOT using .instance() to avoid singleton)
                        shell = InteractiveShell()
                        self._sessions[session_id] = shell
                        self._session_locks[session_id] = Lock()

                        logger.info("Created new Python session: %s", session_id)

                    except ImportError:
                        logger.warning("IPython not available, sessions will not persist")
                        return None
                    except Exception:
                        logger.exception("Failed to create Python session")
                        return None

        return self._sessions[session_id]

    def execute(self, session_id: str, code: str) -> dict[str, Any]:
        """Execute code in session.

        Args:
            session_id: Session identifier
            code: Python code to execute

        Returns:
            Dict with 'success', 'output', 'result', 'error'
        """
        shell = self.get_or_create(session_id)

        if shell is None:
            # Fallback to stateless execution
            return self._execute_stateless(code)

        # Use session-specific lock for thread safety
        if session_id not in self._session_locks:
            self._session_locks[session_id] = Lock()

        with self._session_locks[session_id]:
            try:
                # Execute code
                result = shell.run_cell(code)

                # Extract output
                output = ""
                if result.success and hasattr(result, "output") and result.output:
                    # Get stdout/stderr
                    output = str(result.output)

                # Get return value
                result_value = None
                if result.result is not None:
                    result_value = str(result.result)

                return {
                    "success": result.success,
                    "output": output,
                    "result": result_value,
                    "error": f"{type(result.error_in_exec).__name__}: {result.error_in_exec}"
                    if result.error_in_exec
                    else None,
                }

            except Exception as e:
                logger.exception("Failed to execute code in session %s", session_id)
                return {"success": False, "output": "", "result": None, "error": str(e)}

    def _execute_stateless(self, code: str) -> dict[str, Any]:
        """Fallback stateless execution when IPython is not available."""
        try:
            # Create a new namespace for execution
            namespace = {}

            # Capture stdout/stderr
            import io
            from contextlib import redirect_stderr, redirect_stdout

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                exec(code, namespace)  # noqa: S102

            # Get result if there's a single expression
            result = None
            if code.strip() and "\n" not in code.strip():
                # Try to evaluate as expression
                with contextlib.suppress(SyntaxError):
                    result = eval(code.strip(), namespace)  # noqa: S307

            return {
                "success": True,
                "output": stdout_capture.getvalue(),
                "result": str(result) if result is not None else None,
                "error": stderr_capture.getvalue() or None,
            }

        except Exception as e:
            return {"success": False, "output": "", "result": None, "error": str(e)}

    def cleanup(self, session_id: str) -> None:
        """Clean up a specific session.

        Args:
            session_id: Session to clean up
        """
        with self._lock:
            if session_id in self._sessions:
                try:
                    shell = self._sessions.pop(session_id)
                    shell.reset()
                    logger.info("Cleaned up Python session: %s", session_id)
                except Exception as e:
                    logger.warning("Error cleaning up session %s: %s", session_id, e)

                if session_id in self._session_locks:
                    del self._session_locks[session_id]

    def cleanup_all(self) -> None:
        """Clean up all sessions."""
        with self._lock:
            for session_id in list(self._sessions.keys()):
                self.cleanup(session_id)

    def get_session_count(self) -> int:
        """Get number of active sessions."""
        return len(self._sessions)

    def list_sessions(self) -> list[str]:
        """List active session IDs."""
        return list(self._sessions.keys())


# Global singleton instance
_session_manager: PythonSessionManager | None = None


def get_session_manager() -> PythonSessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = PythonSessionManager()
    return _session_manager
