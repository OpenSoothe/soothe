"""Tests for tool error handler decorator."""

from soothe.utils.tool_error_handler import _simplify_error, tool_error_handler


class TestToolErrorHandler:
    """Test the tool error handler decorator."""

    def test_sync_function_success(self):
        """Successful sync function should return result unchanged."""

        @tool_error_handler("test_tool", return_type="dict")
        def sync_func():
            return {"data": "success"}

        result = sync_func()
        assert result == {"data": "success"}

    def test_sync_function_exception_dict_return(self):
        """Sync function exception should return error dict."""

        @tool_error_handler("test_tool", return_type="dict")
        def sync_func():
            raise ValueError("Test error")

        result = sync_func()
        assert "error" in result
        assert "ValueError" in result["error"]
        assert "Test error" in result["error"]

    def test_sync_function_exception_str_return(self):
        """Sync function exception should return error string."""

        @tool_error_handler("test_tool", return_type="str")
        def sync_func():
            raise ValueError("Test error")

        result = sync_func()
        assert result.startswith("Error:")
        assert "ValueError" in result

    def test_async_function_success(self):
        """Successful async function should return result unchanged."""

        @tool_error_handler("test_tool", return_type="dict")
        async def async_func():
            return {"data": "success"}

        import asyncio

        result = asyncio.run(async_func())
        assert result == {"data": "success"}

    def test_async_function_exception_dict_return(self):
        """Async function exception should return error dict."""

        @tool_error_handler("test_tool", return_type="dict")
        async def async_func():
            raise ValueError("Test async error")

        import asyncio

        result = asyncio.run(async_func())
        assert "error" in result
        assert "ValueError" in result["error"]
        assert "Test async error" in result["error"]

    def test_async_function_exception_str_return(self):
        """Async function exception should return error string."""

        @tool_error_handler("test_tool", return_type="str")
        async def async_func():
            raise ValueError("Test async error")

        import asyncio

        result = asyncio.run(async_func())
        assert result.startswith("Error:")
        assert "ValueError" in result

    def test_preserves_function_metadata(self):
        """Decorator should preserve function name and docstring."""

        @tool_error_handler("test_tool", return_type="dict")
        def my_function():
            """My docstring."""
            return {"data": "test"}

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestSimplifyError:
    """Test error message simplification."""

    def test_dns_resolution_error(self):
        """DNS errors should be simplified."""
        exc = Exception("nodename nor servname provided, or not known")
        msg = _simplify_error(exc)
        assert "DNS resolution failed" in msg
        assert "invalid domain" in msg.lower()

    def test_connection_refused_error(self):
        """Connection refused should be identified."""
        exc = ConnectionError("Connection refused")
        msg = _simplify_error(exc)
        assert "Connection refused" in msg
        assert "service may not be running" in msg

    def test_connection_error(self):
        """Generic connection errors should be simplified."""
        exc = ConnectionError("Network is unreachable")
        msg = _simplify_error(exc)
        assert "Connection failed" in msg

    def test_timeout_error(self):
        """Timeout errors should be identified."""
        exc = TimeoutError("Operation timed out")
        msg = _simplify_error(exc)
        assert "timed out" in msg.lower()

    def test_generic_exception(self):
        """Generic exceptions should show type and message."""
        exc = ValueError("Something went wrong")
        msg = _simplify_error(exc)
        assert "ValueError" in msg
        assert "Something went wrong" in msg
