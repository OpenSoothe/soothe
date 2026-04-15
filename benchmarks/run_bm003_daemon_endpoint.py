"""Runner for BM-003 AI-driven daemon endpoint benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass
class BenchmarkResult:
    """Single benchmark assertion result."""

    test_case: str
    passed: bool
    latency_s: float
    detail: str


def _check(
    test_case: str,
    *,
    latency_s: float,
    max_latency_s: float,
    condition: bool,
    detail: str,
) -> BenchmarkResult:
    passed = condition and latency_s <= max_latency_s
    if latency_s > max_latency_s:
        detail = f"{detail}; latency {latency_s:.3f}s exceeded {max_latency_s:.3f}s"
    return BenchmarkResult(
        test_case=test_case,
        passed=passed,
        latency_s=latency_s,
        detail=detail,
    )


def _request_json(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any], float]:
    start = time.perf_counter()
    response = client.request(method, path, json=json_payload)
    latency_s = time.perf_counter() - start
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, payload, latency_s


def _wait_for_user_message(
    client: httpx.Client,
    thread_id: str,
    needle: str,
    timeout_s: float,
) -> tuple[bool, list[dict[str, Any]], float]:
    start = time.perf_counter()
    deadline = start + timeout_s
    last_messages: list[dict[str, Any]] = []

    while time.perf_counter() < deadline:
        status, payload, _ = _request_json(
            client,
            "GET",
            f"/api/v1/threads/{thread_id}/messages?limit=50&offset=0",
        )
        if status == 200:
            messages = payload.get("messages", [])
            if isinstance(messages, list):
                last_messages = messages
                for message in messages:
                    if message.get("role") != "user":
                        continue
                    content = message.get("content")
                    if isinstance(content, str) and needle in content:
                        return True, messages, time.perf_counter() - start
                    if isinstance(content, list):
                        flattened = " ".join(
                            str(item.get("text", "")) for item in content if isinstance(item, dict)
                        )
                        if needle in flattened:
                            return True, messages, time.perf_counter() - start
        time.sleep(0.2)

    return False, last_messages, time.perf_counter() - start


def run_benchmark(
    *,
    base_url: str,
    timeout_s: float,
    history_poll_timeout_s: float,
) -> tuple[list[BenchmarkResult], bool]:
    """Execute BM-003 benchmark and return per-test results."""
    results: list[BenchmarkResult] = []
    thread_id = ""
    prompt_message = "Summarize the purpose of this daemon benchmark in one sentence."

    with httpx.Client(base_url=base_url, timeout=timeout_s) as client:
        # TC-001: health
        status, payload, latency_s = _request_json(client, "GET", "/api/v1/health")
        results.append(
            _check(
                "TC-001",
                latency_s=latency_s,
                max_latency_s=1.5,
                condition=status == 200
                and payload.get("status") == "healthy"
                and payload.get("transport") == "http_rest",
                detail=f"health status={status}, payload={payload}",
            )
        )

        # TC-002: status contract
        status, payload, latency_s = _request_json(client, "GET", "/api/v1/status")
        results.append(
            _check(
                "TC-002",
                latency_s=latency_s,
                max_latency_s=1.5,
                condition=status == 200
                and payload.get("status") == "running"
                and payload.get("transport") == "http_rest",
                detail=f"status status={status}, payload={payload}",
            )
        )

        # TC-003: version contract
        status, payload, latency_s = _request_json(client, "GET", "/api/v1/version")
        results.append(
            _check(
                "TC-003",
                latency_s=latency_s,
                max_latency_s=1.5,
                condition=status == 200 and bool(payload.get("protocol")),
                detail=f"version status={status}, payload={payload}",
            )
        )

        # TC-004: create thread
        create_payload = {
            "initial_message": "Benchmark bootstrap message for daemon endpoint validation.",
            "metadata": {"tags": ["benchmark", "bm-003", "ai-driven"], "priority": "normal"},
        }
        status, payload, latency_s = _request_json(
            client, "POST", "/api/v1/threads", json_payload=create_payload
        )
        thread_id = str(payload.get("thread_id", ""))
        results.append(
            _check(
                "TC-004",
                latency_s=latency_s,
                max_latency_s=2.0,
                condition=status == 200 and bool(thread_id),
                detail=f"create thread status={status}, payload={payload}",
            )
        )

        if not thread_id:
            return results, False

        # TC-005: resume thread
        status, payload, latency_s = _request_json(
            client,
            "POST",
            f"/api/v1/threads/{thread_id}/resume",
            json_payload={"message": prompt_message},
        )
        results.append(
            _check(
                "TC-005",
                latency_s=latency_s,
                max_latency_s=2.5,
                condition=status == 200
                and payload.get("status") == "resumed"
                and payload.get("thread_id") == thread_id,
                detail=f"resume status={status}, payload={payload}",
            )
        )

        # TC-006: message persistence check (polling)
        found, messages, latency_s = _wait_for_user_message(
            client=client,
            thread_id=thread_id,
            needle="Summarize the purpose of this daemon benchmark",
            timeout_s=history_poll_timeout_s,
        )
        user_count = sum(1 for message in messages if message.get("role") == "user")
        results.append(
            _check(
                "TC-006",
                latency_s=latency_s,
                max_latency_s=3.0,
                condition=found and user_count >= 1,
                detail=f"history found={found}, user_count={user_count}",
            )
        )

        # TC-007: archive then delete
        cleanup_start = time.perf_counter()
        arch_status, arch_payload, _ = _request_json(
            client, "DELETE", f"/api/v1/threads/{thread_id}?archive=true"
        )
        del_status, del_payload, _ = _request_json(
            client, "DELETE", f"/api/v1/threads/{thread_id}?archive=false"
        )
        cleanup_latency_s = time.perf_counter() - cleanup_start
        results.append(
            _check(
                "TC-007",
                latency_s=cleanup_latency_s,
                max_latency_s=2.0,
                condition=arch_status == 200
                and arch_payload.get("status") == "archived"
                and del_status == 200
                and del_payload.get("status") == "deleted",
                detail=(
                    f"archive status={arch_status}, payload={arch_payload}; "
                    f"delete status={del_status}, payload={del_payload}"
                ),
            )
        )

    all_passed = all(result.passed for result in results)
    return results, all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BM-003 daemon endpoint benchmark.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8766",
        help="Base URL of daemon HTTP REST endpoint.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--history-poll-timeout",
        type=float,
        default=12.0,
        help="Timeout in seconds while polling thread messages.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    args = parser.parse_args()

    try:
        results, all_passed = run_benchmark(
            base_url=args.base_url,
            timeout_s=args.timeout,
            history_poll_timeout_s=args.history_poll_timeout,
        )
    except httpx.HTTPError as exc:
        print(f"Benchmark failed: HTTP error while contacting daemon endpoint: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "base_url": args.base_url,
                    "all_passed": all_passed,
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
    else:
        print(f"BM-003 results for {args.base_url}")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"- {result.test_case}: {status} ({result.latency_s:.3f}s) {result.detail}")
        passed_count = sum(1 for result in results if result.passed)
        print(f"Summary: {passed_count}/{len(results)} test cases passed")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

