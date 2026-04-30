"""Runner for BM-004 security verification benchmark."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from soothe.core.persistence.config_policy import ConfigDrivenPolicy
from soothe.protocols.policy import ActionRequest, Permission, PermissionSet, PolicyContext


@dataclass
class BenchmarkResult:
    """Single benchmark assertion result."""

    test_case: str
    passed: bool
    detail: str


def _security_config() -> SimpleNamespace:
    return SimpleNamespace(
        allow_paths_outside_workspace=False,
        require_approval_for_outside_paths=True,
        denied_paths=["~/.ssh/**", "**/.env", "**/secrets.json"],
        allowed_paths=["**"],
        denied_file_types=[],
        require_approval_for_file_types=[".pem", ".key", ".crt"],
    )


def _ctx(workspace: Path) -> PolicyContext:
    return PolicyContext(
        active_permissions=PermissionSet(
            frozenset(
                [
                    Permission("fs", "read", "*"),
                    Permission("fs", "write", "*"),
                    Permission("shell", "execute", "*"),
                ]
            )
        ),
        thread_id="bm004-thread",
        workspace=str(workspace),
    )


def run_benchmark() -> tuple[list[BenchmarkResult], bool]:
    """Execute BM-004 benchmark and return per-test results."""
    results: list[BenchmarkResult] = []

    with TemporaryDirectory(prefix="bm004-") as td:
        workspace = Path(td).resolve()
        policy = ConfigDrivenPolicy(config=SimpleNamespace(security=_security_config()))
        context = _ctx(workspace)

        tc1 = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="read_file",
                tool_args={"path": "/tmp/security-benchmark-outside.txt"},
            ),
            context,
        )
        results.append(
            BenchmarkResult(
                test_case="TC-001",
                passed=tc1.verdict == "deny" and "outside workspace" in tc1.reason,
                detail=f"verdict={tc1.verdict}; reason={tc1.reason}",
            )
        )

        tc2 = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="read_file",
                tool_args={"path": str(Path("~/.ssh/id_rsa").expanduser())},
            ),
            context,
        )
        results.append(
            BenchmarkResult(
                test_case="TC-002",
                passed=tc2.verdict == "deny" and "denied pattern" in tc2.reason,
                detail=f"verdict={tc2.verdict}; reason={tc2.reason}",
            )
        )

        pem_path = workspace / "certs" / "server.pem"
        tc3 = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="read_file",
                tool_args={"path": str(pem_path)},
            ),
            context,
        )
        results.append(
            BenchmarkResult(
                test_case="TC-003",
                passed=tc3.verdict == "need_approval" and "requires approval" in tc3.reason,
                detail=f"verdict={tc3.verdict}; reason={tc3.reason}",
            )
        )

        tc4 = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_command",
                tool_args={"command": "rm -rf /"},
            ),
            context,
        )
        results.append(
            BenchmarkResult(
                test_case="TC-004",
                passed=tc4.verdict == "deny" and "Command blocked" in tc4.reason,
                detail=f"verdict={tc4.verdict}; reason={tc4.reason}",
            )
        )

        tc5 = policy.check(
            ActionRequest(
                action_type="tool_call",
                tool_name="run_background",
                tool_args={"command": "sudo rm -rf /"},
            ),
            context,
        )
        results.append(
            BenchmarkResult(
                test_case="TC-005",
                passed=tc5.verdict == "deny" and "Command blocked" in tc5.reason,
                detail=f"verdict={tc5.verdict}; reason={tc5.reason}",
            )
        )

    all_passed = all(result.passed for result in results)
    return results, all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run BM-004 security verification benchmark.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    results, all_passed = run_benchmark()

    if args.json:
        print(
            json.dumps(
                {
                    "benchmark": "BM-004",
                    "all_passed": all_passed,
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
    else:
        print("BM-004 results")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            print(f"- {result.test_case}: {status} {result.detail}")
        passed_count = sum(1 for result in results if result.passed)
        print(f"Summary: {passed_count}/{len(results)} test cases passed")

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
