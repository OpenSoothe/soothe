#!/usr/bin/env python3
"""Dev workspace sync backup snapshot — pushes a workspace snapshot to MinIO S3.

Uses the soothe workspace sync subsystem (RFC-906) to:
  1. Construct an FsspecSyncBackend against the dev MinIO S3 endpoint.
  2. Create a workspace, write agent output files.
  3. Run a checkpoint (SNAPSHOT) — uploads dirty-file blobs (CAS) + manifest
     + checkpoint payload to the ``soothe`` S3 bucket.
  4. Publish artifacts to the durable store.
  5. Verify the snapshot landed in S3.

Usage:
  SOOTHE_MINIO_PORT=19100 \\
  SOOTHE_MINIO_ROOT_USER=soothe SOOTHE_MINIO_ROOT_PASSWORD=soothe@minio \\
  .venv/bin/python scripts/dev_workspace_sync_backup.py
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Ensure the soothe package is importable when running from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "soothe" / "src"))

from soothe.workspace.sync import (  # noqa: E402
    CASCache,
    CheckpointManager,
    DirtyTracker,
    construct_sync_backend,
)
from soothe_sdk.protocols.workspace_sync import (  # noqa: E402
    ArtifactSpec,
    CheckpointPayload,
    CheckpointType,
    Manifest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dev_workspace_sync_backup")


async def run_backup() -> int:
    """Run a workspace sync backup snapshot to dev MinIO S3.

    Returns:
        Exit code (0 = success).
    """
    minio_port = os.environ.get("SOOTHE_MINIO_PORT", "19100")
    minio_user = os.environ.get("SOOTHE_MINIO_ROOT_USER", "soothe")
    minio_pass = os.environ.get("SOOTHE_MINIO_ROOT_PASSWORD", "soothe@minio")
    endpoint = f"http://127.0.0.1:{minio_port}"

    source_uri = "s3://soothe/"
    config = {
        "endpoint_url": endpoint,
        "key": minio_user,
        "secret": minio_pass,
        "anon": False,
    }

    run_id = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    logger.info("=== Workspace Sync Backup Snapshot ===")
    logger.info("Endpoint:    %s", endpoint)
    logger.info("Bucket URI:  %s", source_uri)
    logger.info("Run ID:      %s", run_id)

    # --- 1. Construct the S3 backend via the factory ---
    logger.info("Step 1: Constructing FsspecSyncBackend via factory...")
    backend = construct_sync_backend(source_uri, config)
    logger.info("Backend constructed: %s", type(backend).__name__)

    # --- 2. Set up local workspace dirs ---
    tmp_root = Path(tempfile.mkdtemp(prefix="soothe-ws-sync-"))
    workspace_root = tmp_root / run_id
    for subdir in ("input", "working", "output", ".workspace"):
        (workspace_root / subdir).mkdir(parents=True, exist_ok=True)
    cas_root = tmp_root / "cas"
    cas_root.mkdir(parents=True, exist_ok=True)
    logger.info("Step 2: Local workspace at %s", workspace_root)

    # --- 3. Write agent output files (simulated agent work) ---
    report_content = (
        f"# Soothe Dev Backup Snapshot\n\n"
        f"Generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"Run ID: {run_id}\n\n"
        f"This is a workspace sync backup snapshot test against MinIO S3.\n"
    )
    (workspace_root / "output" / "report.md").write_text(report_content)

    data_content = b'{"status": "ok", "source": "dev_workspace_sync_backup"}'
    (workspace_root / "output" / "metadata.json").write_bytes(data_content)

    logger.info("Step 3: Wrote 2 output files to workspace")

    # --- 4. Wire up sync components ---
    cas = CASCache(cache_root=cas_root)
    dirty_tracker = DirtyTracker(workspace_root=workspace_root)
    # Manually mark files dirty (simulating dirty-tracker events)
    dirty_tracker.mark_dirty("output/report.md")
    dirty_tracker.mark_dirty("output/metadata.json")

    checkpoint_mgr = CheckpointManager(
        run_id=run_id,
        backend=backend,
        cas=cas,
        dirty_tracker=dirty_tracker,
        workspace_root=workspace_root,
    )

    # --- 5. Create checkpoint (SNAPSHOT) ---
    logger.info("Step 4: Creating checkpoint (SNAPSHOT)...")
    ckpt_id = await checkpoint_mgr.create_checkpoint()
    logger.info("Checkpoint created: %s", ckpt_id)

    # Verify it's a snapshot
    full_ckpt_id = f"{run_id}-{ckpt_id}" if "-" not in ckpt_id else ckpt_id
    # The checkpoint_path uses run_id prefix; reconstruct properly
    stored_ckpt_data = await backend.get_checkpoint(f"{run_id}-{ckpt_id}")
    if stored_ckpt_data is None:
        # Try without run_id prefix
        stored_ckpt_data = await backend.get_checkpoint(ckpt_id)
    if stored_ckpt_data is not None:
        payload = CheckpointPayload.model_validate_json(stored_ckpt_data)
        logger.info(
            "Checkpoint verified: kind=%s, dirty_files=%d, manifest_version=%d",
            payload.kind.value,
            len(payload.dirty_files),
            payload.manifest_snapshot.version if payload.manifest_snapshot else 0,
        )
        assert payload.kind == CheckpointType.SNAPSHOT, f"Expected SNAPSHOT, got {payload.kind}"

    # --- 6. Publish artifacts ---
    logger.info("Step 5: Publishing artifacts to durable store...")
    specs = [
        ArtifactSpec(path="output/report.md", publish=True, content_type="text/markdown"),
        ArtifactSpec(path="output/metadata.json", publish=True, content_type="application/json"),
    ]
    # Use backend directly for publish (Workspace.publish wraps this)
    published = []
    for spec in specs:
        file_path = workspace_root / spec.path
        if file_path.exists():
            data = file_path.read_bytes()
            artifact = await backend.publish_artifact(
                spec.path, data, content_type=spec.content_type
            )
            published.append(artifact)
            logger.info("Published: %s -> %s", spec.path, artifact.published_uri)

    # --- 7. Verify the snapshot in S3 ---
    logger.info("Step 6: Verifying snapshot in S3...")
    # Check manifest
    manifest = await backend.get_manifest(run_id)
    if manifest is not None:
        logger.info(
            "Manifest OK: run_id=%s, version=%d, artifacts=%d",
            manifest.run_id,
            manifest.version,
            len(manifest.artifacts),
        )
    else:
        logger.error("Manifest NOT found in S3!")
        return 1

    # Check blobs (CAS)
    report_sha = hashlib.sha256(report_content.encode()).hexdigest()
    data_sha = hashlib.sha256(data_content).hexdigest()
    for name, sha in [("report.md", report_sha), ("metadata.json", data_sha)]:
        exists = await backend.head_blob(sha)
        logger.info("Blob %s: head_blob=%s", name, exists)
        if not exists:
            logger.error("Blob %s NOT found in S3!", name)
            return 1

    # List checkpoints
    checkpoints = await backend.list_checkpoints(run_id)
    logger.info("Checkpoints in S3: %s", checkpoints)

    # --- 8. Summary ---
    logger.info("=== Backup Snapshot Complete ===")
    logger.info("Run ID:        %s", run_id)
    logger.info("Checkpoint:    %s", ckpt_id)
    logger.info("Manifest:      version %d", manifest.version)
    logger.info("Artifacts:     %d published", len(published))
    logger.info("CAS blobs:     2 (report.md, metadata.json)")
    logger.info("S3 bucket:     s3://soothe/")

    # Cleanup local temp
    import shutil
    shutil.rmtree(tmp_root, ignore_errors=True)
    logger.info("Local temp workspace cleaned up.")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_backup()))
