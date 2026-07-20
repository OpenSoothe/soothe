"""PGVectorStore -- async PostgreSQL + pgvector implementation."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from soothe_sdk.protocols.vector_store import VectorRecord

logger = logging.getLogger(__name__)


def _row_get(row: Any, *, name: str, index: int) -> Any:
    """Read a column from psycopg rows (tuple or dict_row)."""
    if isinstance(row, Mapping):
        return row[name]
    return row[index]


class PGVectorStore:
    """VectorStoreProtocol implementation using PostgreSQL with pgvector.

    Uses ``psycopg`` (v3) with async connection pooling. Supports HNSW
    and IVFFlat index types.

    Args:
        collection: Table name for storing vectors.
        dsn: PostgreSQL connection string.
        pool_size: Connection pool size.
        index_type: Index type (``hnsw``, ``ivfflat``, or ``none``).
        vector_size: Dimension of vectors (default: 1536).
    """

    def __init__(
        self,
        collection: str = "soothe_vectors",
        dsn: str = "postgresql://localhost/soothe",
        pool_size: int = 16,
        index_type: str = "hnsw",
        vector_size: int = 1536,
        *,
        shared_pool: Any | None = None,
        pool_timing: dict[str, Any] | None = None,
    ) -> None:
        """Initialize PGVectorStore.

        Args:
            collection: Table name for storing vectors.
            dsn: PostgreSQL connection string.
            pool_size: Connection pool size (ignored when ``shared_pool`` is set).
            index_type: Index type (``hnsw``, ``ivfflat``, or ``none``).
            vector_size: Dimension of vectors (default: 1536).
            shared_pool: Externally managed registry pool (``pool_size=0`` mode).
            pool_timing: Optional psycopg pool timing kwargs.
        """
        self._collection = collection
        self._dsn = dsn
        self._pool_size = pool_size
        self._index_type = index_type
        self._vector_size = vector_size
        self._pool: Any = shared_pool
        self._pool_timing = pool_timing
        self._owns_pool = shared_pool is None

    async def _ensure_pool(self) -> Any:
        pool = self._pool
        if pool is not None:
            if getattr(pool, "closed", False) is True:
                self._pool = None
            else:
                return pool

        if not self._owns_pool:
            msg = "PGVectorStore shared pool is closed or unavailable"
            raise RuntimeError(msg)

        from psycopg_pool import AsyncConnectionPool

        pool_kwargs: dict[str, Any] = {
            "max_size": self._pool_size,
            "open": False,
        }
        if self._pool_timing:
            pool_kwargs.update(self._pool_timing)
        else:
            pool_kwargs["min_size"] = min(1, self._pool_size)
        self._pool = AsyncConnectionPool(self._dsn, **pool_kwargs)
        await self._pool.open()
        return self._pool

    async def _table_vector_dimension(self) -> int | None:
        """Return the embedding column dimension for an existing table, if any."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                """
                SELECT a.atttypmod
                FROM pg_class c
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relname = %s
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """,
                (self._collection,),
            )
            result = await row.fetchone()
            if result is None:
                return None
            typmod = int(_row_get(result, name="atttypmod", index=0))
            return typmod if typmod > 0 else None

    async def create_collection(
        self, vector_size: int | None = None, distance: str = "cosine"
    ) -> None:
        """Create the vector table and index if they don't exist.

        Args:
            vector_size: Vector dimension. If None, uses instance's vector_size.
            distance: Distance metric (cosine, l2, ip).
        """
        actual_vector_size = vector_size if vector_size is not None else self._vector_size
        self._vector_size = actual_vector_size

        existing_dim = await self._table_vector_dimension()
        if existing_dim is not None and existing_dim != actual_vector_size:
            logger.warning(
                "Vector table %r dimension mismatch (%d != %d); recreating table",
                self._collection,
                existing_dim,
                actual_vector_size,
            )
            await self.delete_collection()

        pool = await self._ensure_pool()

        dist_ops = {
            "cosine": "vector_cosine_ops",
            "l2": "vector_l2_ops",
            "ip": "vector_ip_ops",
        }
        ops = dist_ops.get(distance, "vector_cosine_ops")

        async with pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._collection} (
                    id TEXT PRIMARY KEY,
                    embedding vector({actual_vector_size}),
                    payload JSONB DEFAULT '{{}}'::jsonb
                )
            """)
            if self._index_type == "hnsw":
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self._collection}_hnsw
                    ON {self._collection}
                    USING hnsw (embedding {ops})
                """)
            elif self._index_type == "ivfflat":
                await conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self._collection}_ivfflat
                    ON {self._collection}
                    USING ivfflat (embedding {ops})
                    WITH (lists = 100)
                """)

    async def _ensure_collection(self, vector_size: int | None = None) -> None:
        """Ensure the collection/table exists with the expected vector dimension."""
        await self.create_collection(vector_size=vector_size)

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors into the table."""
        import json

        if not vectors:
            return

        vector_dim = len(vectors[0])
        for index, vec in enumerate(vectors):
            if len(vec) != vector_dim:
                msg = (
                    f"Vector dimension mismatch at index {index}: "
                    f"expected {vector_dim}, got {len(vec)}"
                )
                raise ValueError(msg)

        await self._ensure_collection(vector_size=vector_dim)

        pool = await self._ensure_pool()
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(uuid.uuid4()) for _ in vectors]

        async with pool.connection() as conn:
            for vid, vec, payload in zip(ids, vectors, payloads, strict=False):
                # Collection name is controlled internally, not from user input
                await conn.execute(
                    f"INSERT INTO {self._collection} (id, embedding, payload) "
                    "VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE "
                    "SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload",
                    (vid, str(vec), json.dumps(payload)),
                )

    async def search(
        self,
        query: str,  # noqa: ARG002
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours using cosine distance."""
        pool = await self._ensure_pool()

        where_clause = ""
        params: list[Any] = []
        if filters:
            conditions = []
            for k, v in filters.items():
                # Pass raw value, not JSON-serialized
                params.append(str(v))
                conditions.append(f"payload->>'{k}' = %s")
            where_clause = "WHERE " + " AND ".join(conditions)

        async with pool.connection() as conn:
            # Build the query with proper parameter ordering
            # Collection name is controlled internally, not from user input
            sql = (
                f"SELECT id, payload, 1 - (embedding <=> %s) as score "
                f"FROM {self._collection} {where_clause} "
                f"ORDER BY embedding <=> %s LIMIT %s"
            )

            # Parameters: vector for score, filter params, vector for ordering, limit
            sql_params = [str(vector), *params, str(vector), limit]

            rows = await conn.execute(sql, sql_params)
            results = await rows.fetchall()
            return [
                VectorRecord(
                    id=_row_get(r, name="id", index=0),
                    payload=_row_get(r, name="payload", index=1) or {},
                    score=float(_row_get(r, name="score", index=2)),
                )
                for r in results
            ]

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            # Collection name is controlled internally, not from user input
            await conn.execute(
                f"DELETE FROM {self._collection} WHERE id = %s",
                (record_id,),
            )

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload."""
        import json

        pool = await self._ensure_pool()
        sets: list[str] = []
        params: list[Any] = []
        if vector is not None:
            sets.append("embedding = %s")
            params.append(str(vector))
        if payload is not None:
            sets.append("payload = %s")
            params.append(json.dumps(payload))
        if not sets:
            return
        params.append(record_id)
        async with pool.connection() as conn:
            # Collection name is controlled internally, not from user input
            await conn.execute(
                f"UPDATE {self._collection} SET {', '.join(sets)} WHERE id = %s",
                tuple(params),
            )

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            # Collection name is controlled internally, not from user input
            row = await conn.execute(
                f"SELECT id, payload FROM {self._collection} WHERE id = %s",
                (record_id,),
            )
            r = await row.fetchone()
            if r is None:
                return None
            return VectorRecord(
                id=_row_get(r, name="id", index=0),
                payload=_row_get(r, name="payload", index=1) or {},
            )

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records with optional filters."""
        pool = await self._ensure_pool()

        where_clause = ""
        params: list[Any] = []
        if filters:
            import json

            conditions = []
            for k, v in filters.items():
                params.append(json.dumps(v))
                conditions.append(f"payload->>'{k}' = %s")
            where_clause = "WHERE " + " AND ".join(conditions)

        limit_clause = f" LIMIT {limit}" if limit else ""
        async with pool.connection() as conn:
            # Collection name is controlled internally, not from user input
            rows = await conn.execute(
                f"SELECT id, payload FROM {self._collection} {where_clause}{limit_clause}",
                tuple(params) if params else None,
            )
            results = await rows.fetchall()
            return [
                VectorRecord(
                    id=_row_get(r, name="id", index=0),
                    payload=_row_get(r, name="payload", index=1) or {},
                )
                for r in results
            ]

    async def delete_collection(self) -> None:
        """Drop the vector table."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {self._collection}")

    async def reset(self) -> None:
        """Truncate all records from the table."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            await conn.execute(f"TRUNCATE TABLE {self._collection}")

    async def close(self) -> None:
        """Close the connection pool and release resources."""
        if not self._owns_pool:
            self._pool = None
            return
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
