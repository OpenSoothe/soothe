"""URL validation and sanitization utilities."""

import re
from urllib.parse import urlparse


def validate_url(url: str) -> tuple[str, str | None]:
    """Validate and sanitize URL.

    Returns:
        Tuple of (sanitized_url, error_message)
        If error_message is not None, the URL is invalid.
    """
    # Remove leading/trailing whitespace
    url = url.strip()

    # Check for spaces (common error: 'https://ir.we ride.ai/')
    if " " in url:
        # Try to fix by encoding spaces
        url = url.replace(" ", "%20")

    # Basic validation
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            return url, f"URL missing scheme (http:// or https://): {url}"
        if not parsed.netloc:
            return url, f"URL missing domain: {url}"
        # Check for other invalid characters
        if re.search(r'[<>"\']', url):
            return url, f"URL contains invalid characters: {url}"
    except Exception as e:
        return url, f"Invalid URL format: {e}"
    else:
        return url, None
