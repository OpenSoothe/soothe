"""SQLite vector store using sqlite-vec extension."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import sqlite3
import struct
import threading
import uuid
from pathlib import Path
from typing import Any

from soothe.config import SOOTHE_HOME
from soothe.protocols.vector_store import VectorRecord

logger = logging.getLogger(__name__)

# Distance metric constants
_DISTANCE_MAP = {
    "cosine": "cosine",
    "l2": "l2",
    "ip": "dot",
}


def _pack_vector(vector: list[float]) -> bytes:
    """Pack a list of floats into F32 binary format for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _l2_distance(a: list[float], b: list[float]) -> float:
    """Compute L2 (Euclidean) distance between two vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))


def _ip_similarity(a: list[float], b: list[float]) -> float:
    """Compute inner product (dot product) similarity."""
    return sum(x * y for x, y in zip(a, b, strict=False))


class SQLiteVecStore:
    """VectorStoreProtocol implementation using SQLite with sqlite-vec.

    Uses the sqlite-vec extension for vector similarity search.
    Falls back to Python-side similarity computation if sqlite-vec
    virtual tables are unavailable.

    Args:
        collection: Collection name (becomes table name prefix).
        db_path: Path to SQLite database. Defaults to $SOOTHE_HOME/vector.db.
        vector_size: Dimension of vectors (default: 1536).
        distance: Distance metric (cosine, l2, ip).
    """

    def __init__(
        self,
        collection: str = "soothe_vectors",
        db_path: str | None = None,
        vector_size: int = 1536,
        distance: str = "cosine",
    ) -> None:
        """Initialize SQLiteVecStore.

        Args:
            collection: Collection name for storing vectors.
            db_path: Path to SQLite database file. Defaults to $SOOTHE_HOME/vector.db.
            vector_size: Dimension of vectors (default: 1536).
            distance: Distance metric (cosine, l2, ip).
        """
        self._collection = collection
        self._db_path = db_path or str(Path(SOOTHE_HOME) / "vector.db")
        self._vector_size = vector_size
        self._distance = distance
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._thread_lock = threading.Lock()
        self._has_vec_ext = False

    def _ensure_connection(self) -> sqlite3.Connection:
        """Lazy connection initialization.

        Returns:
            Active SQLite connection with vec extension loaded.
        """
        if self._conn is not None:
            return self._conn

        with self._thread_lock:
            if self._conn is not None:
                return self._conn

            db_path = Path(self._db_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)

            self._conn = sqlite3.connect(
                str(db_path),
                check_same_thread=False,
                timeout=30,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row

            self._load_vec_extension()
            logger.info(
                "SQLite vector store initialized at %s (collection=%s, has_vec_ext=%s)",
                self._db_path,
                self._collection,
                self._has_vec_ext,
            )
            return self._conn

    def _load_vec_extension(self) -> None:
        """Load sqlite-vec extension."""
        if self._conn is None:
            return
        try:
            import sqlite_vec

            self._conn.enable_load_extension(enable=True)
            self._conn.load_extension(sqlite_vec.loadable_path())
            self._conn.enable_load_extension(enable=False)
            self._has_vec_ext = True

            # sqlite-vec v0.1.x provides SQL functions (vec_distance_cosine, etc.)
            # but not vec0 virtual tables. We use regular tables with BLOB vectors
            # and SQL distance functions for search. This works across all v0.1.x versions.
            self._has_vec0 = False

            logger.debug("sqlite-vec extension loaded successfully (SQL functions available)")
        except ImportError:
            logger.warning(
                "sqlite-vec not installed. Install with: pip install sqlite-vec. "
                "Falling back to Python-side similarity (non-persistent vector storage)."
            )
            self._has_vec_ext = False
        except Exception as e:
            logger.warning("Failed to load sqlite-vec extension: %s", e)
            self._has_vec_ext = False

    def _table_name(self) -> str:
        """Get the table name for this collection."""
        return f"vec_{self._collection}"

    def _create_table_sql(self) -> str:
        """Generate table creation SQL.

        Always uses regular tables with BLOB vectors.
        sqlite-vec SQL functions (vec_distance_cosine) operate on BLOB columns
        directly, no vec0 virtual tables needed.
        """
        table = self._table_name()
        return f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                vector_size INTEGER NOT NULL,
                payload TEXT DEFAULT '{{}}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        """Create or ensure a collection exists.

        Args:
            vector_size: Dimensionality of vectors in this collection.
            distance: Distance metric (cosine, l2, ip).
        """
        self._vector_size = vector_size
        self._distance = distance

        def _create() -> None:
            conn = self._ensure_connection()
            conn.execute(self._create_table_sql())
            conn.commit()

        await asyncio.to_thread(_create)

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads and IDs.

        Args:
            vectors: List of embedding vectors.
            payloads: Per-vector metadata dicts.
            ids: Per-vector IDs. Auto-generated if not provided.
        """
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(uuid.uuid4()) for _ in vectors]

        async with self._lock:
            await self.create_collection(self._vector_size, self._distance)

            def _insert() -> None:
                conn = self._ensure_connection()
                table = self._table_name()
                for vid, vec, payload in zip(ids, vectors, payloads, strict=False):
                    packed = _pack_vector(vec)
                    payload_json = json.dumps(payload)
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} (id, embedding, vector_size, payload) VALUES (?, ?, ?, ?)",
                        (vid, packed, len(vec), payload_json),
                    )
                conn.commit()

            await asyncio.to_thread(_insert)

    async def search(
        self,
        query: str,  # noqa: ARG002
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours.

        Args:
            query: Original text query (unused in pure vector search).
            vector: Query embedding vector.
            limit: Maximum results to return.
            filters: Metadata filter conditions.

        Returns:
            Records ordered by descending similarity.
        """

        def _search() -> list[VectorRecord]:
            conn = self._ensure_connection()
            table = self._table_name()
            packed = _pack_vector(vector)

            # Try SQL distance function first (sqlite-vec v0.1.x)
            try:
                rows = conn.execute(
                    f"""
                    SELECT id, payload, vec_distance_cosine(embedding, ?) as dist
                    FROM {table}
                    ORDER BY dist ASC
                    LIMIT ?
                    """,
                    (packed, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return self._brute_force_search(table, vector, limit, filters)

            results = []
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                if filters and not self._match_filters(payload, filters):
                    continue
                score = 1.0 - row["dist"]
                results.append(VectorRecord(id=row["id"], payload=payload, score=score))
            return results

        return await asyncio.to_thread(_search)

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID.

        Args:
            record_id: The record to delete.
        """

        def _delete() -> None:
            conn = self._ensure_connection()
            table = self._table_name()
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
            conn.commit()

        await asyncio.to_thread(_delete)

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload.

        Args:
            record_id: The record to update.
            vector: New embedding vector (None to keep existing).
            payload: New metadata (None to keep existing).
        """
        if vector is not None:
            # Re-insert with new vector (upsert semantics)
            payloads = [payload] if payload is not None else [{}]
            await self.insert([vector], payloads, [record_id])
        elif payload is not None:

            def _update_payload() -> None:
                conn = self._ensure_connection()
                table = self._table_name()
                conn.execute(
                    f"UPDATE {table} SET payload = ? WHERE id = ?",
                    (json.dumps(payload), record_id),
                )
                conn.commit()

            await asyncio.to_thread(_update_payload)

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID.

        Args:
            record_id: The record to retrieve.

        Returns:
            The record, or None if not found.
        """

        def _get() -> VectorRecord | None:
            conn = self._ensure_connection()
            table = self._table_name()
            row = conn.execute(
                f"SELECT id, embedding, payload FROM {table} WHERE id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"]) if row["payload"] else {}
            return VectorRecord(id=row["id"], payload=payload)

        return await asyncio.to_thread(_get)

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records matching optional filters.

        Args:
            filters: Metadata filter conditions.
            limit: Maximum records to return. None for all.

        Returns:
            Matching records.
        """

        def _list() -> list[VectorRecord]:
            conn = self._ensure_connection()
            table = self._table_name()
            limit_clause = f" LIMIT {limit}" if limit else ""
            try:
                rows = conn.execute(
                    f"SELECT id, payload FROM {table}{limit_clause}",
                ).fetchall()
            except sqlite3.OperationalError:
                # Table doesn't exist (e.g. after delete_collection)
                return []

            results = []
            for row in rows:
                payload = json.loads(row["payload"]) if row["payload"] else {}
                if filters and not self._match_filters(payload, filters):
                    continue
                results.append(VectorRecord(id=row["id"], payload=payload))
            return results

        return await asyncio.to_thread(_list)

    async def delete_collection(self) -> None:
        """Delete the entire collection and its data."""

        def _drop() -> None:
            conn = self._ensure_connection()
            table = self._table_name()
            conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()

        await asyncio.to_thread(_drop)

    async def reset(self) -> None:
        """Clear all records from the collection without deleting it."""

        def _reset() -> None:
            conn = self._ensure_connection()
            table = self._table_name()
            conn.execute(f"DELETE FROM {table}")
            conn.commit()

        await asyncio.to_thread(_reset)

    async def close(self) -> None:
        """Close connections and release resources."""
        if self._conn is not None:
            with self._thread_lock:
                if self._conn is not None:
                    with contextlib.suppress(Exception):
                        self._conn.commit()
                    self._conn.close()
                    self._conn = None
                    logger.info("SQLite vector store closed")

    def _brute_force_search(
        self, table: str, vector: list[float], limit: int, filters: dict[str, Any] | None
    ) -> list[VectorRecord]:
        """Brute-force vector search with Python-side similarity computation.

        Args:
            table: Table name to search.
            vector: Query vector.
            limit: Maximum results.
            filters: Metadata filters.

        Returns:
            Records sorted by similarity.
        """
        conn = self._ensure_connection()
        rows = conn.execute(
            f"SELECT id, embedding, vector_size, payload FROM {table} LIMIT 1000",
        ).fetchall()

        sim_func = {
            "cosine": _cosine_similarity,
            "l2": lambda a, b: -_l2_distance(a, b),
            "ip": _ip_similarity,
        }.get(self._distance, _cosine_similarity)

        results = []
        for row in rows:
            vec_size = row["vector_size"]
            emb = list(struct.unpack(f"{vec_size}f", row["embedding"]))
            score = sim_func(vector, emb)
            payload = json.loads(row["payload"]) if row["payload"] else {}
            if filters and not self._match_filters(payload, filters):
                continue
            results.append(VectorRecord(id=row["id"], payload=payload, score=score))

        reverse = self._distance != "l2"
        results.sort(key=lambda r: r.score or 0, reverse=reverse)
        return results[:limit]

    @staticmethod
    def _match_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        """Check if payload matches all filter conditions.

        Args:
            payload: Record payload.
            filters: Filter key-value pairs.

        Returns:
            True if all filters match.
        """
        return all(payload.get(key) == value for key, value in filters.items())
