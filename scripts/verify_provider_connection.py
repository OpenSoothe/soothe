#!/usr/bin/env python3
"""Verify provider connectivity and explain common connection failures.

This script is focused on OpenAI-compatible providers and defaults to `agnes`.
It performs two checks:
1) GET /models to validate endpoint + credentials.
2) POST /chat/completions with a tiny prompt to verify model access.

Usage:
    uv run python scripts/verify_provider_connection.py
    uv run python scripts/verify_provider_connection.py --provider agnes --timeout 20
    uv run python scripts/verify_provider_connection.py --provider agnes --model agnes-2.0-flash
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from soothe.config.env import _resolve_provider_env
from soothe.config.settings import SootheConfig
from soothe.utils.llm.registry import ProviderRegistry


@dataclass(slots=True)
class ProbeResult:
    """Outcome for one HTTP probe."""

    ok: bool
    stage: str
    message: str
    details: str | None = None
    status_code: int | None = None
    response_body: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Diagnose provider connection issues (defaults to agnes).",
    )
    parser.add_argument(
        "--config",
        default="config/develop/nano.yml",
        help="Path to Soothe config file (default: config/develop/nano.yml).",
    )
    parser.add_argument(
        "--provider",
        default="agnes",
        help="Provider name from config.providers (default: agnes).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model to probe; defaults to first model in provider config.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="HTTP timeout in seconds (default: 15).",
    )
    return parser


def _read_config(config_path: str) -> SootheConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return SootheConfig.from_yaml_file(str(path))


def _normalize_base_url(raw_base_url: str | None, provider_type: str) -> str:
    if raw_base_url:
        return raw_base_url.rstrip("/")
    if provider_type == "openai":
        return "https://api.openai.com/v1"
    return ""


def _truncate_body(body: str, *, limit: int = 400) -> str:
    text = body.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... (truncated)"


def _classify_network_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, socket.timeout):
        return (
            "timeout",
            "Request timed out. Provider may be unreachable or network is slow.",
        )
    if isinstance(exc, ssl.SSLError):
        return (
            "tls_error",
            "TLS/SSL handshake failed. Check certificate chain or HTTPS interception.",
        )
    if isinstance(exc, error.URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return (
                "tls_error",
                "TLS/SSL handshake failed. Check certificate chain or HTTPS interception.",
            )
        if isinstance(reason, socket.gaierror):
            return (
                "dns_error",
                "DNS lookup failed. Verify the provider host in api_base_url.",
            )
        if isinstance(reason, ConnectionRefusedError):
            return (
                "connection_refused",
                "Connection refused. Host/port is reachable but service is not accepting connections.",
            )
        if isinstance(reason, TimeoutError):
            return (
                "timeout",
                "Connection attempt timed out. Provider host may be blocked or down.",
            )
        reason_text = str(reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason_text or "certificate verify failed" in reason_text:
            return (
                "tls_error",
                "TLS certificate verification failed. The server or proxy certificate chain is not trusted.",
            )
        return ("network_error", f"Network error: {reason}")
    return ("network_error", str(exc))


def _classify_http_error(status_code: int, body: str) -> tuple[str, str]:
    lower = body.lower()
    if "not allowed by the default security policy" in lower or "域名拦截" in body:
        return (
            "network_policy_blocked",
            "Outbound domain is blocked by local security policy/proxy allowlist.",
        )
    if status_code == 400:
        return ("bad_request", "Request was rejected (400). Check payload format and model name.")
    if status_code in (401, 403):
        return (
            "auth_error",
            "Authentication failed. API key is invalid, expired, or unauthorized.",
        )
    if status_code == 404:
        return (
            "not_found",
            "Endpoint or model not found. Verify api_base_url includes the correct `/v1` path and model id.",
        )
    if status_code == 408:
        return (
            "timeout",
            "Provider timeout (408). Retry with higher timeout or check service health.",
        )
    if status_code == 409:
        return ("conflict", "Provider reported a conflict (409). Retry later.")
    if status_code == 422:
        if "model" in lower and "not" in lower and "found" in lower:
            return ("model_not_found", "Model is not available for this provider or account.")
        return (
            "validation_error",
            "Request validation failed (422). Check model and payload fields.",
        )
    if status_code == 429:
        return ("rate_limited", "Rate limited (429). Retry after cooldown or increase quota.")
    if 500 <= status_code <= 599:
        return ("provider_unavailable", "Provider server error (5xx). Service may be degraded.")
    return ("http_error", f"Unexpected HTTP status: {status_code}")


def _http_request(
    *,
    url: str,
    method: str,
    timeout: float,
    api_key: str,
    payload: dict[str, Any] | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> ProbeResult:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return ProbeResult(
                ok=True,
                stage=url,
                message=f"HTTP {resp.status}",
                response_body=_truncate_body(body),
                status_code=resp.status,
            )
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        category, message = _classify_http_error(exc.code, body)
        return ProbeResult(
            ok=False,
            stage=url,
            message=message,
            details=f"category={category}",
            status_code=exc.code,
            response_body=_truncate_body(body),
        )
    except Exception as exc:  # noqa: BLE001 - deliberate categorization of runtime/network errors
        category, message = _classify_network_error(exc)
        return ProbeResult(
            ok=False,
            stage=url,
            message=message,
            details=f"category={category}",
        )


def _pick_model(provider: Any, cli_model: str | None) -> str | None:
    if cli_model:
        return cli_model
    models = getattr(provider, "models", None)
    if models:
        return models[0]
    return None


def _build_ssl_context(provider: Any) -> ssl.SSLContext | None:
    """Build SSL context from provider TLS options for urllib probes."""
    verify_ssl = bool(getattr(provider, "verify_ssl", True))
    ca_bundle_path = getattr(provider, "ca_bundle_path", None)

    if not verify_ssl:
        return ssl._create_unverified_context()  # noqa: SLF001

    if not ca_bundle_path:
        return None

    resolved_ca_bundle = _resolve_provider_env(
        ca_bundle_path,
        provider_name=provider.name,
        field_name="ca_bundle_path",
    )
    if not resolved_ca_bundle:
        return None

    return ssl.create_default_context(cafile=resolved_ca_bundle)


def main() -> int:
    args = _build_parser().parse_args()
    try:
        config = _read_config(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] Could not load config: {exc}")
        return 2

    provider = next((p for p in config.providers if p.name == args.provider), None)
    if provider is None:
        names = ", ".join(p.name for p in config.providers) or "(none)"
        print(f"[FAIL] Provider '{args.provider}' not found in config. Available: {names}")
        return 2

    registry = ProviderRegistry(config.providers)
    provider_type, kwargs = registry.get_provider_kwargs(provider.name)
    api_key = kwargs.get("api_key")
    base_url = _normalize_base_url(kwargs.get("base_url"), provider_type)

    print(f"Provider : {provider.name}")
    print(f"Type     : {provider_type}")
    print(f"Base URL : {base_url or '(empty)'}")
    print(f"API key  : {'set' if api_key else 'missing'}")
    print(f"TLS verify: {provider.verify_ssl}")
    if provider.ca_bundle_path:
        print(f"CA bundle: {provider.ca_bundle_path}")

    if not api_key:
        print(
            "[FAIL] API key is missing or unresolved. "
            f"Check providers[].api_key for '{provider.name}' and required env vars."
        )
        return 1
    if not base_url:
        print("[FAIL] Base URL is empty. Configure providers[].api_base_url for this provider.")
        return 1

    models_url = f"{base_url}/models"
    ssl_context = _build_ssl_context(provider)
    print(f"\n[Probe 1] GET {models_url}")
    probe_models = _http_request(
        url=models_url,
        method="GET",
        timeout=args.timeout,
        api_key=api_key,
        ssl_context=ssl_context,
    )
    if probe_models.ok:
        print(f"[OK] {probe_models.message}")
    else:
        print(f"[FAIL] {probe_models.message}")
        if probe_models.details:
            print(f"       {probe_models.details}")
        if probe_models.response_body:
            print(f"       body: {probe_models.response_body}")
        return 1

    model = _pick_model(provider, args.model)
    if not model:
        print(
            "\n[WARN] No model specified and provider has no model list; skipping chat completion probe."
        )
        return 0

    chat_url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "reply with OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    print(f"\n[Probe 2] POST {chat_url}")
    print(f"          model={model}")
    probe_chat = _http_request(
        url=chat_url,
        method="POST",
        timeout=args.timeout,
        api_key=api_key,
        payload=payload,
        ssl_context=ssl_context,
    )
    if probe_chat.ok:
        print(f"[OK] {probe_chat.message}")
        print("\nResult: provider connectivity is healthy for basic chat calls.")
        return 0

    print(f"[FAIL] {probe_chat.message}")
    if probe_chat.details:
        print(f"       {probe_chat.details}")
    if probe_chat.response_body:
        print(f"       body: {probe_chat.response_body}")
    print(
        "\nResult: provider endpoint is reachable but chat call failed; details above show likely cause."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
