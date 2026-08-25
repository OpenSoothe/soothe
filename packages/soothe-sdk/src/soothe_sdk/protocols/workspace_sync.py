"""WorkspaceSyncBackend protocol -- async workspace-to-storage abstraction.

Defines the data models and abstract protocol that the Workspace Manager
uses to synchronize agent workspaces with durable object-storage backends
(S3-compatible, MinIO, GCS, local filesystem, etc.).

The protocol lives in soothe-sdk so that CLI/SDK consumers can construct
Resource / Manifest / Artifact objects without importing host code, while
concrete backend implementations live in the host package (soothe).
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data Models (wire contracts)
# ---------------------------------------------------------------------------


class Resource(BaseModel):
    """A logical input supplied to an agent workspace.

    The model is purely content-addressed -- ``sha256`` is the immutable
    identity.  Physical location (S3 key, GCS path, local file) is a
    backend implementation detail and does **not** appear on the wire
    contract.

    Args:
        id: Stable resource identifier (e.g. ``res-123``).
        path: Relative workspace path where the resource should appear,
            e.g. ``input/paper.pdf``.
        size: Content size in bytes.
        sha256: SHA-256 hex digest of the content.  This is the canonical
            identity used for CAS deduplication.
        content_type: MIME type hint (e.g. ``application/pdf``).
    """

    id: str = Field(description="Stable resource identifier (e.g. ``res-123``).")
    path: str = Field(
        description=(
            "Relative workspace path where the resource should appear, e.g. ``input/paper.pdf``."
        ),
    )
    size: int = Field(description="Content size in bytes.")
    sha256: str = Field(
        description=(
            "SHA-256 hex digest of the content.  This is the canonical "
            "identity used for CAS deduplication."
        ),
    )
    content_type: str | None = Field(
        default=None,
        description="MIME type hint (e.g. ``application/pdf``).",
    )

    @staticmethod
    def compute_sha256(data: bytes) -> str:
        """Compute SHA-256 hex digest of raw bytes.

        Args:
            data: Raw content bytes.

        Returns:
            Hex-encoded SHA-256 digest.
        """
        return hashlib.sha256(data).hexdigest()


class ManifestEntry(BaseModel):
    """Single entry inside a :class:`Manifest` referencing one file.

    Args:
        path: Relative workspace path.
        sha256: Content hash.
        size: Content size in bytes.
    """

    path: str = Field(description="Relative workspace path.")
    sha256: str = Field(description="Content hash.")
    size: int = Field(description="Content size in bytes.")


class Manifest(BaseModel):
    """The synchronization contract between a run and its storage backend.

    Contains the expected hashes for every resource (inputs) and artifact
    (outputs) so the backend can perform incremental materialization and
    persistence.

    Args:
        run_id: Unique run identifier.
        version: Optimistic concurrency counter.
        resources: Expected input resources.
        artifacts: Expected output artifacts.
        checkpoint_id: Checkpoint this manifest represents, if any.
    """

    run_id: str = Field(description="Unique run identifier.")
    version: int = Field(
        default=1,
        description="Optimistic concurrency counter.",
    )
    resources: list[ManifestEntry] = Field(
        default_factory=list,
        description="Expected input resources.",
    )
    artifacts: list[ManifestEntry] = Field(
        default_factory=list,
        description="Expected output artifacts.",
    )
    checkpoint_id: str | None = Field(
        default=None,
        description="Checkpoint this manifest represents, if any.",
    )


class ArtifactSpec(BaseModel):
    """Declaration of agent output to publish.

    Args:
        path: Relative workspace path of the artifact.
        content_type: MIME type hint.
        publish: Whether to publish this artifact durably.
    """

    path: str = Field(description="Relative workspace path of the artifact.")
    content_type: str | None = Field(default=None, description="MIME type hint.")
    publish: bool = Field(default=True, description="Whether to publish durably.")


class Artifact(BaseModel):
    """Published artifact returned by the backend after ``publish``.

    Args:
        path: Relative workspace path.
        sha256: Content hash.
        size: Content size in bytes.
        published_uri: URI where the published artifact can be fetched.
            Filled by the backend during publication.
        content_type: MIME type hint.
    """

    path: str = Field(description="Relative workspace path.")
    sha256: str = Field(description="Content hash.")
    size: int = Field(description="Content size in bytes.")
    published_uri: str | None = Field(
        default=None,
        description=(
            "URI where the published artifact can be fetched.  Filled by "
            "the backend during publication."
        ),
    )
    content_type: str | None = Field(default=None, description="MIME type hint.")


class CheckpointType(StrEnum):
    """Discriminator for checkpoint payload encoding.

    ``SNAPSHOT`` payloads are self-contained: they embed the full
    :class:`Manifest` and the complete set of dirty-file entries since
    the last snapshot.  ``DELTA`` payloads carry only the files that
    changed since the *previous* checkpoint; they are meaningless
    without their snapshot anchor.

    The Workspace Manager writes a ``SNAPSHOT`` for the first
    checkpoint of a run and periodically compacts a growing delta
    chain into a new ``SNAPSHOT``.  Recovery always anchors on the
    latest ``SNAPSHOT`` and replays subsequent ``DELTA`` entries.
    """

    SNAPSHOT = "snapshot"
    DELTA = "delta"


class CheckpointPayload(BaseModel):
    """Self-describing checkpoint payload (Option C: snapshot + delta).

    The serialized form of this model is the ``data: bytes`` argument
    to :meth:`WorkspaceSyncBackend.put_checkpoint` and the return
    value of :meth:`get_checkpoint` (deserialized by the caller).

    Design rationale -- snapshot + delta rather than full-snapshot-only
    or delta-only:

    * **Full snapshot only** repeats unchanged entries every checkpoint,
      burning object-store bandwidth on long runs.
    * **Delta only** requires strict ordering, tombstone tracking, and
      gap-filling; a lost or corrupted delta corrupts recovery.
    * **Snapshot + delta** gives a safe anchor (the snapshot) with
      compact incremental updates (the deltas).  Compaction collapses
      a long delta chain back into a fresh snapshot when the cumulative
      delta size exceeds a configurable threshold.

    Args:
        checkpoint_id: Unique checkpoint identifier (e.g. ``c001``).
        kind: Whether this payload is a full snapshot or a delta.
        manifest_version: The :class:`Manifest` version this checkpoint
            was captured against.  Used to detect stale replays.
        dirty_files: Files that changed since the previous checkpoint
            (for ``DELTA``) or since the last snapshot (for the first
            ``SNAPSHOT`` of a run).  Each entry is content-addressed.
        manifest_snapshot: Full manifest snapshot.  Required for
            ``SNAPSHOT`` payloads; omitted for ``DELTA`` payloads
            (they reference the nearest preceding snapshot).
        parent_checkpoint_id: For ``DELTA`` payloads, the ID of the
            checkpoint this delta applies to.  ``None`` for snapshots.
    """

    checkpoint_id: str = Field(description="Unique checkpoint identifier (e.g. ``c001``).")
    kind: CheckpointType = Field(description="Whether this payload is a snapshot or a delta.")
    manifest_version: int = Field(
        description="Manifest version captured by this checkpoint.",
    )
    dirty_files: list[ManifestEntry] = Field(
        default_factory=list,
        description=(
            "Files that changed since the previous checkpoint (for "
            "``DELTA``) or since the last snapshot (for the first "
            "``SNAPSHOT``).  Each entry is content-addressed."
        ),
    )
    manifest_snapshot: Manifest | None = Field(
        default=None,
        description=(
            "Full manifest snapshot.  Required for ``SNAPSHOT`` "
            "payloads; omitted for ``DELTA`` payloads."
        ),
    )
    parent_checkpoint_id: str | None = Field(
        default=None,
        description=(
            "For ``DELTA`` payloads, the ID of the checkpoint this "
            "delta applies to.  ``None`` for snapshots."
        ),
    )

    def is_snapshot(self) -> bool:
        """Return ``True`` if this payload is a full snapshot.

        Returns:
            ``True`` when ``kind`` is :attr:`CheckpointType.SNAPSHOT`.
        """
        return self.kind is CheckpointType.SNAPSHOT


# ---------------------------------------------------------------------------
# Protocol (abstract storage-backend interface)
# ---------------------------------------------------------------------------


@runtime_checkable
class WorkspaceSyncBackend(Protocol):
    """Async protocol for workspace-to-storage synchronization.

    Implementations provide the concrete transport (S3, GCS, local FS, ...)
    while keeping the Workspace Manager's CAS / dirty-tracking /
    checkpointing algorithm backend-agnostic.

    Every method is async and idempotent.  Callers must not assume any
    particular ordering beyond what each docstring specifies.
    """

    # -- blob operations (content-addressed) -------------------------------

    async def get_blob(self, sha256: str) -> bytes | None:
        """Return blob content by hash, or ``None`` if it does not exist.

        A missing hash means the caller should download from the original
        source and store it.

        Args:
            sha256: Content hash of the blob to fetch.

        Returns:
            Full blob payload, or ``None`` if absent.
        """
        ...

    async def put_blob(self, sha256: str, data: bytes) -> None:
        """Store a blob.  Idempotent -- no-op if the hash already exists.

        Args:
            sha256: Expected content hash (backend may verify integrity).
            data: Raw blob content.
        """
        ...

    async def head_blob(self, sha256: str) -> bool:
        """Check whether a blob with this hash exists remotely.

        Args:
            sha256: Content hash to check.

        Returns:
            ``True`` if the blob exists.
        """
        ...

    # -- manifest operations ----------------------------------------------

    async def get_manifest(self, run_id: str) -> Manifest | None:
        """Fetch the latest manifest for *run_id*.

        Args:
            run_id: Target run identifier.

        Returns:
            The current manifest, or ``None`` if none exists yet.
        """
        ...

    async def put_manifest(
        self,
        run_id: str,
        manifest: Manifest,
        *,
        if_match: str | None = None,
    ) -> Manifest:
        """Write or update the manifest for *run_id*.

        Args:
            run_id: Target run identifier.
            manifest: The manifest to write.  Its ``version`` field
                controls optimistic concurrency.
            if_match: If provided, the backend MUST reject the write
                when the stored manifest version does not match
                (conditional write).

        Returns:
            The written manifest with updated metadata.
        """
        ...

    # -- checkpoint operations --------------------------------------------

    async def list_checkpoints(self, run_id: str) -> list[str]:
        """Return checkpoint IDs for *run_id*, ordered oldest-first.

        Args:
            run_id: Target run identifier.

        Returns:
            List of checkpoint IDs.
        """
        ...

    async def get_checkpoint(self, checkpoint_id: str) -> bytes | None:
        """Fetch checkpoint payload by ID.

        The returned bytes are a serialized :class:`CheckpointPayload`
        (JSON or msgpack).  The caller deserializes and, for
        ``DELTA`` payloads, replays against the nearest preceding
        ``SNAPSHOT``.

        Args:
            checkpoint_id: Unique checkpoint identifier (e.g. ``c001``).

        Returns:
            Serialized :class:`CheckpointPayload`, or ``None`` if absent.
        """
        ...

    async def put_checkpoint(
        self,
        checkpoint_id: str,
        data: bytes,
        manifest: Manifest | None = None,
    ) -> None:
        """Store a checkpoint payload.

        ``data`` is a serialized :class:`CheckpointPayload`.  The
        Workspace Manager decides whether each checkpoint is a
        ``SNAPSHOT`` (full manifest + dirty set) or a ``DELTA`` (dirty
        set only, referencing the previous checkpoint).  Compaction
        collapses a long delta chain into a fresh snapshot.

        Args:
            checkpoint_id: Unique checkpoint identifier (e.g. ``c001``).
            data: Serialized :class:`CheckpointPayload`.
            manifest: Optional manifest snapshot captured at the time
                of the checkpoint (kept for backward compatibility;
                the payload's ``manifest_snapshot`` field is preferred).
        """
        ...

    # -- publish operations -----------------------------------------------

    async def publish_artifact(
        self,
        artifact_path: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> Artifact:
        """Publish an artifact and return its metadata.

        Idempotent -- returns existing metadata if the artifact is already
        published at the same path with the same hash.

        Args:
            artifact_path: Relative workspace path of the artifact.
            data: Raw artifact content.
            content_type: MIME type hint.

        Returns:
            Metadata for the published artifact.
        """
        ...

    # -- optional streaming (default impls buffer fully) -------------------

    async def stream_blob(self, sha256: str) -> AsyncIterator[bytes]:
        """Yield chunks of a blob.

        Default implementation delegates to :meth:`get_blob` and yields
        the full payload in one chunk.  Override for large blobs that
        should not be fully buffered in memory.

        Args:
            sha256: Content hash of the blob to stream.

        Yields:
            Chunks of blob content.
        """
        data = await self.get_blob(sha256)
        if data is None:
            raise KeyError(f"Blob {sha256!r} not found")
        yield data

    async def stream_checkpoint(self, checkpoint_id: str) -> AsyncIterator[bytes]:
        """Yield chunks of a checkpoint.

        Default implementation delegates to :meth:`get_checkpoint` and
        yields the full payload in one chunk.  Override for large
        checkpoints.

        Args:
            checkpoint_id: Unique checkpoint identifier.

        Yields:
            Chunks of checkpoint content.
        """
        data = await self.get_checkpoint(checkpoint_id)
        if data is None:
            raise KeyError(f"Checkpoint {checkpoint_id!r} not found")
        yield data
