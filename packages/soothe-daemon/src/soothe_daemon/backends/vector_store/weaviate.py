"""WeaviateVectorStore -- async Weaviate v4 client implementation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from soothe_daemon.protocols.vector_store import VectorRecord

logger = logging.getLogger(__name__)

_DISTANCE_MAP = {
    "cosine": "cosine",
    "l2": "l2-squared",
    "ip": "dot",
}


class WeaviateVectorStore:
    """VectorStoreProtocol implementation using Weaviate v4 async client.

    Uses self-provided vectors (``skip`` vectorizer) so embedding is
    handled externally by Soothe's embedding model.

    Args:
        collection: Weaviate collection (class) name.
        url: Weaviate server URL.
        api_key: Weaviate API key (for Weaviate Cloud).
        grpc_port: gRPC port for Weaviate.
    """

    def __init__(
        self,
        collection: str = "SootheVectors",
        url: str = "http://localhost:8080",
        api_key: str | None = None,
        grpc_port: int = 50051,
    ) -> None:
        """Initialize WeaviateVectorStore.

        Args:
            collection: Weaviate collection name.
            url: Weaviate server URL.
            api_key: Weaviate API key.
            grpc_port: gRPC port.
        """
        self._collection_name = collection
        self._url = url
        self._api_key = api_key
        self._grpc_port = grpc_port
        self._client: Any = None

    async def _ensure_client(self) -> Any:
        if self._client is None:
            import weaviate
            import weaviate.classes as wvc

            if self._api_key:
                auth = weaviate.auth.AuthApiKey(api_key=self._api_key)
                self._client = weaviate.use_async_with_weaviate_cloud(
                    cluster_url=self._url,
                    auth_credentials=auth,
                )
            else:
                # Parse host and port from URL
                url_parts = self._url.replace("http://", "").split(":")
                host = url_parts[0]
                port = int(url_parts[1]) if len(url_parts) > 1 else 8080

                self._client = weaviate.use_async_with_local(
                    host=host,
                    port=port,
                    grpc_port=self._grpc_port,
                    skip_init_checks=True,
                    additional_config=wvc.init.AdditionalConfig(
                        timeout=wvc.init.Timeout(init=30, query=30, insert=120),
                    ),
                )
            await self._client.connect()
        return self._client

    def _get_collection(self, client: Any) -> Any:
        return client.collections.get(self._collection_name)

    async def create_collection(self, vector_size: int, distance: str = "cosine") -> None:  # noqa: ARG002
        """Create the Weaviate collection with ``none`` vectorizer."""
        import weaviate.classes.config as wc

        client = await self._ensure_client()
        if await client.collections.exists(self._collection_name):
            return

        dist = _DISTANCE_MAP.get(distance, "cosine")
        await client.collections.create(
            name=self._collection_name,
            vectorizer_config=wc.Configure.Vectorizer.none(),
            vector_index_config=wc.Configure.VectorIndex.hnsw(
                distance_metric=getattr(
                    wc.VectorDistances, dist.upper().replace("-", "_"), wc.VectorDistances.COSINE
                ),
            ),
            properties=[
                wc.Property(name="record_id", data_type=wc.DataType.TEXT),
                wc.Property(name="payload_json", data_type=wc.DataType.TEXT),
            ],
        )

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors into Weaviate with self-provided embeddings."""
        import json

        client = await self._ensure_client()
        collection = self._get_collection(client)
        payloads = payloads or [{}] * len(vectors)
        ids = ids or [str(uuid.uuid4()) for _ in vectors]

        # Use batch insertion with async context manager
        for vid, vec, payload in zip(ids, vectors, payloads, strict=False):
            await collection.data.insert(
                properties={
                    "record_id": vid,
                    "payload_json": json.dumps(payload, default=str),
                },
                vector=vec,
                uuid=weaviate_uuid_from_str(vid),
            )

    async def search(
        self,
        query: str,  # noqa: ARG002
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search Weaviate using near_vector."""
        import json

        import weaviate.classes.query as wq

        client = await self._ensure_client()
        collection = self._get_collection(client)

        weaviate_filters = None
        if filters:
            from weaviate.classes.query import Filter

            conditions = []
            for k, v in filters.items():
                conditions.append(
                    Filter.by_property("payload_json").contains_any([json.dumps({k: v})])
                )
            if len(conditions) == 1:
                weaviate_filters = conditions[0]

        result = await collection.query.near_vector(
            near_vector=vector,
            limit=limit,
            filters=weaviate_filters,
            return_metadata=wq.MetadataQuery(distance=True),
        )

        records: list[VectorRecord] = []
        for obj in result.objects:
            payload = json.loads(obj.properties.get("payload_json", "{}"))
            record_id = obj.properties.get("record_id", str(obj.uuid))
            score = 1.0 - (obj.metadata.distance or 0.0)
            records.append(VectorRecord(id=record_id, payload=payload, score=score))
        return records

    async def delete(self, record_id: str) -> None:
        """Delete a record by its record_id."""
        client = await self._ensure_client()
        collection = self._get_collection(client)
        try:
            await collection.data.delete_by_id(weaviate_uuid_from_str(record_id))
        except Exception:
            logger.debug("Record %s not found for deletion", record_id)

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update a record's vector and/or payload."""
        import json

        client = await self._ensure_client()
        collection = self._get_collection(client)
        wid = weaviate_uuid_from_str(record_id)

        props: dict[str, Any] = {}
        if payload is not None:
            props["payload_json"] = json.dumps(payload, default=str)

        await collection.data.update(
            uuid=wid,
            properties=props or None,
            vector=vector,
        )

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve a record by ID."""
        import json

        client = await self._ensure_client()
        collection = self._get_collection(client)
        try:
            obj = await collection.query.fetch_object_by_id(weaviate_uuid_from_str(record_id))
        except Exception:
            return None
        if obj is None:
            return None
        payload = json.loads(obj.properties.get("payload_json", "{}"))
        return VectorRecord(
            id=obj.properties.get("record_id", str(obj.uuid)),
            payload=payload,
        )

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List all records from the collection."""
        import json

        client = await self._ensure_client()
        collection = self._get_collection(client)

        records: list[VectorRecord] = []
        async for obj in collection.iterator(include_vector=False):
            payload = json.loads(obj.properties.get("payload_json", "{}"))
            record_id = obj.properties.get("record_id", str(obj.uuid))

            if filters:
                match = all(payload.get(k) == v for k, v in filters.items())
                if not match:
                    continue

            records.append(VectorRecord(id=record_id, payload=payload))
            if limit and len(records) >= limit:
                break
        return records

    async def delete_collection(self) -> None:
        """Delete the entire Weaviate collection."""
        client = await self._ensure_client()
        if await client.collections.exists(self._collection_name):
            await client.collections.delete(self._collection_name)

    async def reset(self) -> None:
        """Delete and recreate the collection to clear all data."""
        await self.delete_collection()

    async def close(self) -> None:
        """Close the Weaviate client connection."""
        if self._client is not None:
            await self._client.close()
            self._client = None


def weaviate_uuid_from_str(s: str) -> str:
    """Generate a deterministic UUID5 from a string for Weaviate.

    Args:
        s: Input string.

    Returns:
        UUID string.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, s))
