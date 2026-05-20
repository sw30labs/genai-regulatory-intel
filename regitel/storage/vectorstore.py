"""ChromaDB vector store wrapper with local sentence-transformer embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from chromadb import Documents, EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer


# Collection names
REGULATION_TEXTS = "regulation_texts"
AI_GOVERNANCE_GUIDANCE = "ai_governance_guidance"
RESEARCH_CACHE = "research_cache"

ALL_COLLECTIONS = [REGULATION_TEXTS, AI_GOVERNANCE_GUIDANCE, RESEARCH_CACHE]


class LocalEmbeddingFunction(EmbeddingFunction[Documents]):
    """Local embedding function using sentence-transformers.

    Runs entirely on-device — no cloud calls.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self.model.encode(
            [str(doc) for doc in input],
            normalize_embeddings=True,
        )
        return embeddings


class VectorStoreManager:
    """Manages ChromaDB collections for regulatory document embeddings.

    Uses local sentence-transformer embeddings — no cloud dependencies.
    """

    def __init__(self, persist_path: str | Path, embedding_model: str = "all-MiniLM-L6-v2"):
        self.persist_path = Path(persist_path)
        self.persist_path.mkdir(parents=True, exist_ok=True)
        self.embedding_fn = LocalEmbeddingFunction(embedding_model)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=Settings(anonymized_telemetry=False),
        )

    def init_collections(self) -> None:
        """Ensure all expected collections exist."""
        for name in ALL_COLLECTIONS:
            self.client.get_or_create_collection(
                name=name,
                embedding_function=self.embedding_fn,
            )

    def get_collection(self, name: str) -> chromadb.Collection:
        """Get a collection by name."""
        return self.client.get_or_create_collection(
            name=name,
            embedding_function=self.embedding_fn,
        )

    def add_documents(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        """Add documents to a collection."""
        collection = self.get_collection(collection_name)
        kwargs: dict = {"ids": ids, "documents": documents}
        if metadatas:
            kwargs["metadatas"] = metadatas
        if embeddings:
            kwargs["embeddings"] = embeddings
        collection.add(**kwargs)

    def query(
        self,
        collection_name: str,
        query_texts: list[str],
        n_results: int = 5,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
    ) -> dict:
        """Query a collection by text similarity."""
        collection = self.get_collection(collection_name)
        kwargs: dict = {
            "query_texts": query_texts,
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        if where_document:
            kwargs["where_document"] = where_document
        return collection.query(**kwargs)

    def get_stats(self) -> dict[str, int]:
        """Return document counts per collection."""
        stats = {}
        for name in ALL_COLLECTIONS:
            try:
                collection = self.client.get_collection(name)
                stats[name] = collection.count()
            except Exception:
                stats[name] = 0
        return stats

    def delete_collection(self, name: str) -> None:
        """Delete a collection entirely."""
        try:
            self.client.delete_collection(name)
        except ValueError:
            pass  # Collection doesn't exist
