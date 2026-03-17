#!/usr/bin/env python3
"""Check external API connectivity.

Validates:
- OpenAI API connectivity
- Google API connectivity
- Tavily API connectivity
- Serper API connectivity
- Jina API connectivity
- MCP server connectivity
- Browser runtime (Chrome/chromedriver)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))


def check_api_connectivity(
    name: str,
    url: str,
    api_key_env: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Check connectivity to an external API."""
    try:
        import requests
    except ImportError:
        return {
            "name": name,
            "status": "warning",
            "message": "requests not installed, cannot check API connectivity",
        }

    # Check if API key is set (if required)
    api_key = None
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            return {
                "name": name,
                "status": "info",
                "message": f"{api_key_env} not set (optional service)",
            }

    # Make minimal request to check connectivity
    try:
        if headers:
            resp = requests.head(url, headers=headers, timeout=5)
        else:
            resp = requests.head(url, timeout=5)

        # Even 401/403 means we can reach the API
        if resp.status_code in (401, 403):
            return {
                "name": name,
                "status": "warning",
                "message": f"API reachable but authentication failed (check {api_key_env})",
            }
        elif resp.status_code >= 500:
            return {
                "name": name,
                "status": "warning",
                "message": f"API returned error {resp.status_code}",
            }

        return {
            "name": name,
            "status": "ok",
            "message": f"API reachable (status {resp.status_code})",
        }
    except requests.exceptions.Timeout:
        return {
            "name": name,
            "status": "warning",
            "message": "API request timed out",
        }
    except requests.exceptions.ConnectionError:
        return {
            "name": name,
            "status": "warning",
            "message": "Could not connect to API (network issue)",
        }
    except Exception as e:
        return {
            "name": name,
            "status": "warning",
            "message": f"API check failed: {e}",
        }


def check_openai() -> dict[str, Any]:
    """Check OpenAI API connectivity."""
    return check_api_connectivity(
        "openai",
        "https://api.openai.com/v1/models",
        "OPENAI_API_KEY",
    )


def check_google() -> dict[str, Any]:
    """Check Google API connectivity."""
    return check_api_connectivity(
        "google",
        "https://generativelanguage.googleapis.com/v1beta/models",
        "GOOGLE_API_KEY",
    )


def check_tavily() -> dict[str, Any]:
    """Check Tavily API connectivity."""
    return check_api_connectivity(
        "tavily",
        "https://api.tavily.com",
        "TAVILY_API_KEY",
    )


def check_serper() -> dict[str, Any]:
    """Check Serper API connectivity."""
    return check_api_connectivity(
        "serper",
        "https://google.serper.dev",
        "SERPER_API_KEY",
    )


def check_jina() -> dict[str, Any]:
    """Check Jina API connectivity."""
    return check_api_connectivity(
        "jina",
        "https://api.jina.ai/v1/embeddings",
        "JINA_API_KEY",
    )


def check_mcp_servers() -> dict[str, Any]:
    """Check MCP server connectivity."""
    # Note: MCP servers are configured dynamically
    # This is a placeholder check
    return {
        "name": "mcp_servers",
        "status": "info",
        "message": "MCP server check requires config (skipped in standalone mode)",
    }


def check_browser_runtime() -> dict[str, Any]:
    """Check Chrome/chromedriver availability and version match."""
    # Try to run the check_chrome.sh script
    script_path = (
        Path(__file__).parent.parent.parent.parent / "scripts" / "check_chrome.sh"
    )

    if not script_path.exists():
        return {
            "name": "browser_runtime",
            "status": "info",
            "message": "check_chrome.sh script not found (browser automation optional)",
        }

    try:
        result = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return {
                "name": "browser_runtime",
                "status": "ok",
                "message": "Chrome and chromedriver versions match",
            }
        else:
            return {
                "name": "browser_runtime",
                "status": "warning",
                "message": f"Chrome/chromedriver issue: {result.stderr.strip()}",
            }
    except subprocess.TimeoutExpired:
        return {
            "name": "browser_runtime",
            "status": "warning",
            "message": "Browser check timed out",
        }
    except Exception as e:
        return {
            "name": "browser_runtime",
            "status": "warning",
            "message": f"Browser check failed: {e}",
        }


def run_checks() -> dict[str, Any]:
    """Run all external integration checks."""
    checks = [
        check_openai(),
        check_google(),
        check_tavily(),
        check_serper(),
        check_jina(),
        check_mcp_servers(),
        check_browser_runtime(),
    ]

    # Determine overall status
    # External API failures are warnings, not critical
    status = "healthy"
    for check in checks:
        if check["status"] == "error":
            status = "warning"  # Downgrade to warning for external services
            break

    return {
        "category": "external_integrations",
        "status": status,
        "checks": checks,
    }


def main() -> int:
    """Run checks and output JSON."""
    result = run_checks()
    print(json.dumps(result, indent=2))

    # External integration issues are always warnings (exit 1)
    # Never critical (exit 2)
    if result["status"] == "healthy":
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
