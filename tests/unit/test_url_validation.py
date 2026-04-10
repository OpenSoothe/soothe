"""Tests for URL validation utility."""

from soothe.utils.url_validation import validate_url


class TestValidateUrl:
    """Test URL validation and sanitization."""

    def test_url_with_spaces(self):
        """URL with spaces should be sanitized by encoding spaces."""
        url = "https://ir.we ride.ai/"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == "https://ir.we%20ride.ai/"

    def test_url_with_multiple_spaces(self):
        """URL with multiple spaces should encode all of them."""
        url = "https://example.com/path with spaces/page"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == "https://example.com/path%20with%20spaces/page"

    def test_url_missing_scheme(self):
        """URL without scheme should return error."""
        url = "example.com"
        sanitized, error = validate_url(url)
        assert error is not None
        assert "missing scheme" in error.lower()

    def test_url_missing_domain(self):
        """URL without domain should return error."""
        url = "https://"
        sanitized, error = validate_url(url)
        assert error is not None
        assert "missing domain" in error.lower()

    def test_valid_url(self):
        """Valid URL should pass validation."""
        url = "https://example.com/path"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == url

    def test_url_with_leading_trailing_whitespace(self):
        """URL with whitespace should be trimmed."""
        url = "  https://example.com/path  "
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == "https://example.com/path"

    def test_url_with_invalid_characters(self):
        """URL with invalid characters should return error."""
        url = 'https://example.com/path?<script>"test"</script>'
        sanitized, error = validate_url(url)
        assert error is not None
        assert "invalid characters" in error.lower()

    def test_http_url(self):
        """HTTP URLs should be valid."""
        url = "http://example.com/path"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == url

    def test_url_with_query_params(self):
        """URL with query parameters should be valid."""
        url = "https://example.com/path?key=value&other=123"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == url

    def test_url_with_fragment(self):
        """URL with fragment should be valid."""
        url = "https://example.com/path#section"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == url

    def test_url_with_port(self):
        """URL with port should be valid."""
        url = "https://example.com:8080/path"
        sanitized, error = validate_url(url)
        assert error is None
        assert sanitized == url
