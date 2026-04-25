#!/usr/bin/env python3
"""Soothe Daemon End-to-End Concurrent Query Benchmark (IG-258).

Real production-like benchmark that tests against a running Soothe daemon:
1. Requires daemon running on ws://127.0.0.1:8765
2. Connects multiple WebSocket clients concurrently
3. Sends real agent queries simultaneously
4. Measures actual latency, throughput, and resource usage
5. Tests Phase 1 + Phase 2 optimizations under real concurrent load

Prerequisites:
    soothed start

Usage:
    python scripts/benchmark_e2e_concurrent_queries.py --clients 50 --queries 100

Output:
    - Real query latency measurements (time from query to first response)
    - Actual throughput under concurrent load
    - Memory and resource usage during execution
    - Queue depths and task counts during load
    - Comprehensive end-to-end performance report
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class E2EBenchmarkMetrics:
    """End-to-end benchmark metrics for concurrent queries."""

    # Query latency (from send to first response)
    query_latencies: list[float] = field(default_factory=list)

    # Throughput
    queries_per_second: list[float] = field(default_factory=list)

    # Resource monitoring
    queue_depth_samples: list[int] = field(default_factory=list)
    task_count_samples: list[int] = field(default_factory=list)
    client_count_samples: list[int] = field(default_factory=list)

    # Errors
    connection_errors: list[str] = field(default_factory=list)
    query_errors: list[str] = field(default_factory=list)

    # Timing
    total_duration: float = 0.0
    warmup_duration: float = 0.0

    def to_report(self) -> dict[str, Any]:
        """Generate comprehensive end-to-end benchmark report."""
        import statistics

        if not self.query_latencies:
            return {"error": "No successful queries completed"}

        return {
            "summary": {
                "total_queries": len(self.query_latencies),
                "successful_queries": len(self.query_latencies) - len(self.query_errors),
                "failed_queries": len(self.query_errors),
                "connection_errors": len(self.connection_errors),
                "total_duration_sec": self.total_duration,
                "warmup_duration_sec": self.warmup_duration,
            },
            "latency": {
                "query_latency_ms": {
                    "min": min(self.query_latencies),
                    "avg": statistics.mean(self.query_latencies),
                    "max": max(self.query_latencies),
                    "p50": statistics.median(self.query_latencies),
                    "p95": statistics.quantiles(self.query_latencies, n=100)[94] if len(self.query_latencies) > 10 else max(self.query_latencies),
                    "p99": statistics.quantiles(self.query_latencies, n=100)[98] if len(self.query_latencies) > 10 else max(self.query_latencies),
                },
            },
            "throughput": {
                "queries_per_second": {
                    "min": min(self.queries_per_second) if self.queries_per_second else 0,
                    "avg": statistics.mean(self.queries_per_second) if self.queries_per_second else 0,
                    "max": max(self.queries_per_second) if self.queries_per_second else 0,
                },
            },
            "resources": {
                "queue_depth": {
                    "avg": statistics.mean(self.queue_depth_samples) if self.queue_depth_samples else 0,
                    "max": max(self.queue_depth_samples) if self.queue_depth_samples else 0,
                },
                "task_count": {
                    "avg": statistics.mean(self.task_count_samples) if self.task_count_samples else 0,
                    "max": max(self.task_count_samples) if self.task_count_samples else 0,
                },
                "client_count": {
                    "avg": statistics.mean(self.client_count_samples) if self.client_count_samples else 0,
                    "max": max(self.client_count_samples) if self.client_count_samples else 0,
                },
            },
            "errors": {
                "connection_errors": self.connection_errors[:5],
                "query_errors": self.query_errors[:5],
            },
        }


class ConcurrentQueryBenchmark:
    """End-to-end concurrent query benchmark runner.

    Expects a running Soothe daemon on ws://127.0.0.1:8765.
    """

    def __init__(self, num_clients: int, num_queries: int, warmup_queries: int = 5):
        """Initialize benchmark.

        Args:
            num_clients: Number of concurrent WebSocket clients
            num_queries: Total number of queries to send
            warmup_queries: Number of warmup queries before measurement
        """
        self.num_clients = num_clients
        self.num_queries = num_queries
        self.warmup_queries = warmup_queries
        self.metrics = E2EBenchmarkMetrics()

    async def check_daemon_connection(self) -> bool:
        """Check if daemon is running and accessible.

        Returns:
            True if daemon is available, False otherwise
        """
        from soothe_sdk.client.websocket import WebSocketClient

        logger.info("Checking if daemon is running on ws://127.0.0.1:8765...")

        try:
            # Try to connect to daemon
            client = WebSocketClient(url="ws://127.0.0.1:8765")
            await asyncio.wait_for(client.connect(), timeout=2.0)
            await client.close()
            logger.info("✅ Daemon is running and accessible")
            return True
        except Exception as e:
            logger.error(f"❌ Cannot connect to daemon: {e}")
            logger.error("Make sure daemon is running: soothed start")
            return False

    async def create_websocket_clients(self) -> list[Any]:
        """Create multiple WebSocket client connections.

        Returns:
            List of WebSocket client instances
        """
        from soothe_sdk.client.websocket import WebSocketClient

        logger.info(f"Creating {self.num_clients} WebSocket clients...")

        clients = []
        connection_errors = []

        # Connect clients concurrently
        async def connect_client(client_id: int):
            try:
                client = WebSocketClient(url="ws://127.0.0.1:8765")
                await asyncio.wait_for(client.connect(), timeout=5.0)
                clients.append(client)
                logger.debug(f"Client {client_id} connected")
            except Exception as e:
                connection_errors.append(f"Client {client_id}: {str(e)}")
                logger.warning(f"Failed to connect client {client_id}: {e}")

        # Connect all clients in parallel
        connect_tasks = [connect_client(i) for i in range(self.num_clients)]
        await asyncio.gather(*connect_tasks)

        self.metrics.connection_errors = connection_errors

        logger.info(f"Connected {len(clients)}/{self.num_clients} clients")
        self.metrics.client_count_samples.append(len(clients))

        return clients

    async def send_concurrent_queries(self, initial_clients: list[Any]) -> None:
        """Send concurrent queries through dedicated clients and measure performance.

        Args:
            initial_clients: List of initially connected WebSocket clients (for warmup)
        """
        if not initial_clients:
            logger.error("No clients connected, cannot run benchmark")
            return

        logger.info(f"Starting concurrent query benchmark ({self.num_queries} queries)")

        # Warmup phase: Use initial clients (one query per client to avoid concurrency issues)
        logger.info(f"Warmup phase: sending {self.warmup_queries} queries...")
        warmup_start = time.perf_counter()

        warmup_tasks = []
        for i in range(min(self.warmup_queries, len(initial_clients))):
            # Use one client per query (no reuse)
            client = initial_clients[i]
            warmup_tasks.append(self._send_single_query(client, i, is_warmup=True))

        await asyncio.gather(*warmup_tasks, return_exceptions=True)

        warmup_duration = time.perf_counter() - warmup_start
        self.metrics.warmup_duration = warmup_duration
        logger.info(f"Warmup completed in {warmup_duration:.2f}s")

        # Main benchmark phase: Create fresh clients for each query
        # This avoids WebSocket concurrency issues and matches real concurrent load
        logger.info(f"Benchmark phase: sending {self.num_queries} queries...")
        benchmark_start = time.perf_counter()

        # Create fresh clients and send queries concurrently
        query_tasks = []
        for i in range(self.num_queries):
            query_tasks.append(self._send_single_query_with_new_client(i))

        # Send all queries concurrently
        results = await asyncio.gather(*query_tasks, return_exceptions=True)

        benchmark_duration = time.perf_counter() - benchmark_start
        self.metrics.total_duration = benchmark_duration

        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.metrics.query_errors.append(f"Query {i}: {str(result)}")
            elif isinstance(result, float):
                self.metrics.query_latencies.append(result)

        # Calculate throughput
        successful_queries = len(self.metrics.query_latencies)
        throughput = 0.0  # Initialize to default value
        if benchmark_duration > 0 and successful_queries > 0:
            throughput = successful_queries / benchmark_duration
            self.metrics.queries_per_second.append(throughput)

        logger.info(f"Benchmark completed in {benchmark_duration:.2f}s")
        logger.info(f"Successful queries: {successful_queries}/{self.num_queries}")
        logger.info(f"Throughput: {throughput:.2f} queries/sec")

    async def _send_single_query(self, client: Any, query_id: int, is_warmup: bool = False) -> float:
        """Send a single query through a client and measure latency.

        Args:
            client: WebSocket client instance
            query_id: Query identifier
            is_warmup: Whether this is a warmup query

        Returns:
            Query latency in milliseconds
        """
        query_start = time.perf_counter()

        try:
            # Generate unique query to avoid duplicate filtering
            unique_question = f"Benchmark query {query_id}: Calculate {query_id} + {query_id * 2}"
            await client.send_input(text=unique_question)

            # Wait for first response (stream start or status event)
            # We measure latency to first response chunk, not completion
            timeout_seconds = 30.0 if not is_warmup else 10.0

            async def receive_first_response():
                received_thread_id = None

                async for event in client.receive():
                    event_type = event.get("type")

                    # First, capture the thread_id from status events
                    # The daemon sends status events with thread_id when processing queries
                    if event_type == "status":
                        thread_id = event.get("thread_id")
                        state = event.get("state")

                        # Capture the thread_id assigned to our query
                        if thread_id and not received_thread_id:
                            received_thread_id = thread_id
                            logger.debug(f"Query {query_id} assigned thread {thread_id[:8]}")

                        # Wait for our specific thread to complete (state="idle")
                        if thread_id and thread_id == received_thread_id and state == "idle":
                            logger.debug(f"Query {query_id} completed on thread {thread_id[:8]}")
                            return True

                    # Also accept message/output events (contain actual LLM response)
                    if event_type in ["message", "output", "stream_start"]:
                        return True

                    # Collect resource metrics from daemon status events
                    if event_type == "daemon_status":
                        data = event.get("data", {})
                        if "input_queue_depth" in data:
                            self.metrics.queue_depth_samples.append(data["input_queue_depth"])
                        if "active_tasks" in data:
                            self.metrics.task_count_samples.append(data["active_tasks"])
                        if "client_count" in data:
                            self.metrics.client_count_samples.append(data["client_count"])
                return False

            response_received = await asyncio.wait_for(
                receive_first_response(),
                timeout=timeout_seconds
            )

            query_latency_ms = (time.perf_counter() - query_start) * 1000

            if response_received:
                logger.debug(f"Query {query_id} completed in {query_latency_ms:.2f}ms")
                return query_latency_ms
            else:
                logger.warning(f"Query {query_id} timed out after {timeout_seconds}s")
                raise asyncio.TimeoutError(f"Query timed out after {timeout_seconds}s")

        except asyncio.TimeoutError:
            logger.warning(f"Query {query_id} timed out")
            raise
        except Exception as e:
            logger.warning(f"Query {query_id} failed: {e}")
            raise

    async def _send_single_query_with_new_client(self, query_id: int) -> float:
        """Send a single query with a fresh WebSocket client connection.

        This method creates a dedicated client for each query to avoid
        WebSocket concurrency issues where multiple queries try to use
        the same client's recv() method concurrently.

        Args:
            query_id: Query identifier

        Returns:
            Query latency in milliseconds (from send to completion)
        """
        from soothe_sdk.client.websocket import WebSocketClient

        client = None
        try:
            # Create fresh WebSocket client for this query
            client = WebSocketClient(url="ws://127.0.0.1:8765")
            await asyncio.wait_for(client.connect(), timeout=5.0)

            # Send query and wait for completion (not just send)
            # The daemon auto-subscribes the client when processing input
            latency = await self._send_single_query(client, query_id, is_warmup=False)

            # DON'T disconnect immediately - wait for daemon to finish processing
            # The _send_single_query method already waits for completion events

            return latency

        except Exception as e:
            logger.warning(f"Query {query_id} failed: {e}")
            raise
        finally:
            # Now we can disconnect after query completion
            if client:
                try:
                    await client.close()
                except Exception:
                    pass  # Ignore disconnect errors

    async def cleanup_clients(self, clients: list[Any]) -> None:
        """Close all client connections.

        Args:
            clients: List of WebSocket clients
        """
        logger.info(f"Closing {len(clients)} client connections...")

        async def close_client(client):
            try:
                await client.close()
            except Exception as e:
                logger.debug(f"Failed to close client: {e}")

        await asyncio.gather(*[close_client(c) for c in clients], return_exceptions=True)

        logger.info("All clients disconnected")

    async def run(self) -> dict[str, Any]:
        """Run the complete end-to-end benchmark against existing daemon.

        Returns:
            Benchmark results report
        """
        try:
            # Check daemon is running
            if not await self.check_daemon_connection():
                return {"error": "Daemon not running. Start with: soothed start"}

            # Create clients
            clients = await self.create_websocket_clients()

            if not clients:
                logger.error("Failed to connect any clients")
                return {"error": "No clients connected"}

            # Send concurrent queries
            await self.send_concurrent_queries(clients)

            # Cleanup
            await self.cleanup_clients(clients)

            # Generate report
            report = self.metrics.to_report()

            return report

        except Exception as e:
            logger.exception("Benchmark failed: %s", e)
            return {"error": str(e)}


def print_benchmark_report(report: dict[str, Any]) -> None:
    """Print formatted benchmark report."""
    logger.info("\n" + "=" * 80)
    logger.info("End-to-End Concurrent Query Benchmark Results")
    logger.info("=" * 80)

    if "error" in report:
        logger.error(f"BENCHMARK FAILED: {report['error']}")
        return

    summary = report["summary"]
    latency = report["latency"]["query_latency_ms"]
    throughput = report["throughput"]["queries_per_second"]
    resources = report["resources"]

    logger.info("\nQuery Performance:")
    logger.info(f"  Total Queries: {summary['total_queries']}")
    logger.info(f"  Successful: {summary['successful_queries']} ({summary['successful_queries']/summary['total_queries']*100:.1f}%)")
    logger.info(f"  Failed: {summary['failed_queries']}")
    logger.info(f"  Connection Errors: {summary['connection_errors']}")

    logger.info("\nLatency Measurements:")
    logger.info(f"  Min: {latency['min']:.2f}ms")
    logger.info(f"  Avg: {latency['avg']:.2f}ms")
    logger.info(f"  Max: {latency['max']:.2f}ms")
    logger.info(f"  P50: {latency['p50']:.2f}ms")
    logger.info(f"  P95: {latency['p95']:.2f}ms")
    logger.info(f"  P99: {latency['p99']:.2f}ms")

    logger.info("\nThroughput:")
    logger.info(f"  Avg: {throughput['avg']:.2f} queries/sec")
    logger.info(f"  Max: {throughput['max']:.2f} queries/sec")
    logger.info(f"  Total Duration: {summary['total_duration_sec']:.2f}s")
    logger.info(f"  Warmup Duration: {summary['warmup_duration_sec']:.2f}s")

    logger.info("\nResource Usage During Load:")
    logger.info(f"  Queue Depth Avg: {resources['queue_depth']['avg']:.1f} (max: {resources['queue_depth']['max']})")
    logger.info(f"  Task Count Avg: {resources['task_count']['avg']:.1f} (max: {resources['task_count']['max']})")
    logger.info(f"  Client Count Avg: {resources['client_count']['avg']:.1f} (max: {resources['client_count']['max']})")

    if report["errors"]["connection_errors"]:
        logger.info("\nConnection Errors (first 5):")
        for err in report["errors"]["connection_errors"][:5]:
            logger.info(f"  - {err}")

    if report["errors"]["query_errors"]:
        logger.info("\nQuery Errors (first 5):")
        for err in report["errors"]["query_errors"][:5]:
            logger.info(f"  - {err}")

    logger.info("\n" + "=" * 80)

    # Success criteria
    success = True
    issues = []

    if latency["avg"] > 5000:  # 5 seconds
        success = False
        issues.append(f"Query latency > 5s (avg: {latency['avg']:.2f}ms)")

    if throughput["avg"] < 1.0:  # Less than 1 query/sec
        success = False
        issues.append(f"Throughput < 1 query/sec (avg: {throughput['avg']:.2f})")

    if resources["queue_depth"]["max"] > 900:  # Queue exceeds 90% capacity
        success = False
        issues.append(f"Queue depth > 900 (max: {resources['queue_depth']['max']})")

    if summary["failed_queries"] > summary["total_queries"] * 0.1:  # > 10% failures
        success = False
        issues.append(f"Failure rate > 10% ({summary['failed_queries']}/{summary['total_queries']})")

    if success:
        logger.info("✅ BENCHMARK PASSED - All success criteria met")
        logger.info("Phase 1 + Phase 2 optimizations validated under real concurrent load")
    else:
        logger.error("❌ BENCHMARK FAILED:")
        for issue in issues:
            logger.error(f"  - {issue}")

    logger.info("=" * 80)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Soothe End-to-End Concurrent Query Benchmark"
    )
    parser.add_argument(
        "--clients",
        type=int,
        default=3,
        help="Number of concurrent WebSocket clients (default: 3)"
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=10,
        help="Total number of queries to send (default: 10)"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Number of warmup queries (default: 2)"
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Soothe Daemon End-to-End Concurrent Query Benchmark (IG-258)")
    logger.info("=" * 80)
    logger.info("\n⚠️  REQUIREMENTS:")
    logger.info("  Daemon must be running on ws://127.0.0.1:8765")
    logger.info("  Start with: soothed start")
    logger.info("")
    logger.info(f"\nConfiguration:")
    logger.info(f"  Concurrent Clients: {args.clients}")
    logger.info(f"  Total Queries: {args.queries}")
    logger.info(f"  Warmup Queries: {args.warmup}")
    logger.info("")

    benchmark = ConcurrentQueryBenchmark(
        num_clients=args.clients,
        num_queries=args.queries,
        warmup_queries=args.warmup
    )

    try:
        report = asyncio.run(benchmark.run())

        # Print report
        print_benchmark_report(report)

        # Save report
        report_path = Path(__file__).parent.parent / "benchmark_e2e_results.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"\n📊 Full report saved to: {report_path}")

        # Check for success
        if "error" in report:
            return 1

        # Validate success criteria
        latency = report["latency"]["query_latency_ms"]
        throughput = report["throughput"]["queries_per_second"]
        resources = report["resources"]
        summary = report["summary"]

        if (latency["avg"] <= 5000 and
            throughput["avg"] >= 1.0 and
            resources["queue_depth"]["max"] <= 900 and
            summary["failed_queries"] <= summary["total_queries"] * 0.1):
            return 0
        else:
            return 1

    except KeyboardInterrupt:
        logger.info("\nBenchmark interrupted by user")
        return 1
    except Exception as e:
        logger.exception(f"Benchmark failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
