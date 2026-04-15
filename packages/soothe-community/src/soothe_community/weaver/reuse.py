"""ReuseIndex -- vector search over previously generated agents (RFC-0005) -- community edition."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .models import AgentManifest, CapabilitySignature, ReuseCandidate

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

    from soothe.protocols.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)


class ReuseIndex:
    """Semantic index of previously generated agents for reuse-first strategy.

    Args:
        vector_store: Vector store for agent description embeddings.
        embeddings: Embedding model for vectorization.
        threshold: Minimum confidence score to consider a reuse hit.
        collection: Vector store collection name.
        embedding_dims: Embedding vector dimensionality.
    """

    def __init__(
        self,
        vector_store: "VectorStoreProtocol",
        embeddings: Embeddings,
        threshold: float = 0.85,
        collection: str = "soothe_weaver_reuse",
        embedding_dims: int = 1536,
    ) -> None:
        """Initialize the reuse index.

        Args:
            vector_store: Vector store for agent description embeddings.
            embeddings: Embedding model for vectorization.
            threshold: Minimum confidence score to consider a reuse hit.
            collection: Vector store collection name.
            embedding_dims: Embedding vector dimensionality.
        """
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._threshold = threshold
        self._collection = collection
        self._embedding_dims = embedding_dims
        self._initialized = False

    async def _ensure_collection(self) -> None:
        if self._initialized:
            return
        try:
            await self._vector_store.create_collection(
                vector_size=self._embedding_dims,
                distance="cosine",
            )
        except Exception:
            logger.debug("Reuse collection creation failed (may already exist)", exc_info=True)
        self._initialized = True

    async def find_reusable(self, capability: CapabilitySignature) -> ReuseCandidate | None:
        """Search for an existing generated agent matching the capability.

        Args:
            capability: The analysed capability signature.

        Returns:
            A ``ReuseCandidate`` if confidence >= threshold, else ``None``.
        """
        await self._ensure_collection()

        try:
            vector = await self._embeddings.aembed_query(capability.description)
        except Exception:
            logger.exception("Failed to embed capability description")
            return None

        try:
            results = await self._vector_store.search(
                query=capability.description,
                vector=vector,
                limit=5,
            )
        except Exception:
            logger.exception("Reuse index search failed")
            return None

        if not results:
            return None

        best = results[0]
        confidence = best.score or 0.0
        if confidence < self._threshold:
            return None

        payload = best.payload
        try:
            manifest = AgentManifest(**payload.get("manifest", {}))
        except Exception:
            logger.warning("Failed to parse reuse candidate manifest", exc_info=True)
            return None

        return ReuseCandidate(
            manifest=manifest,
            confidence=confidence,
            path=payload.get("path", ""),
        )

    async def index_agent(self, manifest: AgentManifest, path: str) -> None:
        """Add a newly generated agent to the reuse index.

        Args:
            manifest: The agent's manifest.
            path: Absolute path to the agent directory.
        """
        await self._ensure_collection()

        text = f"{manifest.name}: {manifest.description}"
        if manifest.capabilities:
            text += f"\nCapabilities: {', '.join(manifest.capabilities)}"

        try:
            vector = await self._embeddings.aembed_query(text)
        except Exception:
            logger.exception("Failed to embed agent description for reuse index")
            return

        payload: dict[str, Any] = {
            "manifest": manifest.model_dump(mode="json"),
            "path": path,
            "agent_name": manifest.name,
        }

        try:
            await self._vector_store.insert(
                vectors=[vector],
                payloads=[payload],
                ids=[manifest.name],
            )
        except Exception:
            logger.exception("Failed to index agent in reuse store")

    async def close(self) -> None:
        """Close the underlying vector store if supported."""
        close_method = getattr(self._vector_store, "close", None)
        if callable(close_method):
            await close_method()
