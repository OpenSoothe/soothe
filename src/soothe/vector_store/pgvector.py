"""PGVectorStore -- async PostgreSQL + pgvector implementation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from soothe.protocols.vector_store import VectorRecord

logger = logging.getLogger(__name__)


class PGVectorStore:
    """VectorStoreProtocol implementation using PostgreSQL with pgvector.

    Uses ``psycopg`` (v3) with async connection pooling. Supports HNSW
    and IVFFlat index types.

    Args:
        collection: Table name for storing vectors.
        dsn: PostgreSQL connection string.
        pool_size: Connection pool size.
        index_type: Index type (``hnsw``, ``ivfflat``, or ``none``).
    """

    def __init__(
        self,
        collection: str = "soothe_vectors",
        dsn: str = "postgresql://localhost/soothe",
        pool_size: int = 5,
        index_type: str = "hnsw",
    ) -> None:
        """Initialize PGVectorStore.

        Args:
            collection: Table name for storing vectors.
            dsn: PostgreSQL connection string.
            pool_size: Connection pool size.
            index_type: Index type (``hnsw``, ``ivfflat``, or ``none``).
        """
        self._collection = collection
        self._dsn = dsn
        self._pool_size = pool_size
        self._index_type = index_type
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            from psycopg_pool import AsyncConnectionPool

            self._pool = AsyncConnectionPool(self._dsn, min_size=1, max_size=self._pool_size, open=False)
            await self._pool.open()
        return self._pool

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:
        """Create the vector table and index if they don't exist."""
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
                    embedding vector({vector_size}),
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

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors into the table."""
        import json

        pool = await self._ensure_pool()
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(uuid.uuid4()) for _ in vectors]

        async with pool.connection() as conn:
            for vid, vec, payload in zip(ids, vectors, payloads):
                await conn.execute(
                    f"INSERT INTO {self._collection} (id, embedding, payload) "
                    "VALUES (%s, %s, %s) ON CONFLICT (id) DO UPDATE "
                    "SET embedding = EXCLUDED.embedding, payload = EXCLUDED.payload",
                    (vid, str(vec), json.dumps(payload)),
                )

    async def search(
        self,
        query: str,
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
            sql = f"SELECT id, payload, 1 - (embedding <=> %s) as score FROM {self._collection} {where_clause} ORDER BY embedding <=> %s LIMIT %s"

            # Parameters: vector for score, filter params, vector for ordering, limit
            sql_params = [str(vector)] + params + [str(vector), limit]

            rows = await conn.execute(sql, sql_params)
            results = await rows.fetchall()
            return [VectorRecord(id=r[0], payload=r[1] or {}, score=float(r[2])) for r in results]

    async def delete(self, record_id: str) -> None:
        """Delete a record by ID."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
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
            await conn.execute(
                f"UPDATE {self._collection} SET {', '.join(sets)} WHERE id = %s",
                tuple(params),
            )

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a single record by ID."""
        pool = await self._ensure_pool()
        async with pool.connection() as conn:
            row = await conn.execute(
                f"SELECT id, payload FROM {self._collection} WHERE id = %s",
                (record_id,),
            )
            r = await row.fetchone()
            if r is None:
                return None
            return VectorRecord(id=r[0], payload=r[1] or {})

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
            rows = await conn.execute(
                f"SELECT id, payload FROM {self._collection} {where_clause}{limit_clause}",
                tuple(params) if params else None,
            )
            results = await rows.fetchall()
            return [VectorRecord(id=r[0], payload=r[1] or {}) for r in results]

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
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
