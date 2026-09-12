import math
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class VectorStoreInterface(ABC):
    @abstractmethod
    async def add_documents(self, documents: List[Dict[str, Any]], organization_id: str, property_id: str, agent_id: Optional[str] = None) -> List[str]:
        pass

    @abstractmethod
    async def delete_document(self, document_id: str, organization_id: str, property_id: str) -> bool:
        pass

class MockEmbeddings:
    """Deterministic embedding generator for testing and offline development."""
    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed_text(self, text: str) -> List[float]:
        # Hash text to seed vector
        hash_val = sum(ord(c) for c in text)
        vector = []
        for i in range(self.dimension):
            val = math.sin(hash_val * (i + 1))
            vector.append(val)
        # Normalize vector
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

class PostgresPgVectorStore(VectorStoreInterface):
    def __init__(self, db_session=None):
        self.db_session = db_session
        self.embedder = MockEmbeddings()
        # In-memory document index fallback when direct pgvector extension is unconfigured
        self._in_memory_store: List[Dict[str, Any]] = []

    async def add_documents(self, documents: List[Dict[str, Any]], organization_id: str, property_id: str, agent_id: Optional[str] = None) -> List[str]:
        added_ids = []
        for doc in documents:
            content = doc.get("content", "")
            doc_id = doc.get("id", f"chunk_{len(self._in_memory_store) + 1}")
            embedding = self.embedder.embed_text(content)
            entry = {
                "id": doc_id,
                "content": content,
                "embedding": embedding,
                "organization_id": organization_id,
                "property_id": property_id,
                "agent_id": agent_id,
                "metadata": doc.get("metadata", {})
            }
            self._in_memory_store.append(entry)
            added_ids.append(doc_id)
        return added_ids

    async def delete_document(self, document_id: str, organization_id: str, property_id: str) -> bool:
        initial_len = len(self._in_memory_store)
        doc_id_normalized = document_id.replace(' ', '_')
        self._in_memory_store = [
            item for item in self._in_memory_store
            if not (
                item["organization_id"] == organization_id and
                item["property_id"] == property_id and
                (
                    item["metadata"].get("document_id") == document_id or
                    item["metadata"].get("title") == document_id or
                    doc_id_normalized in item["id"] or
                    document_id in item["id"]
                )
            )
        ]
        return len(self._in_memory_store) < initial_len


    async def similarity_search(self, query: str, organization_id: str, property_id: str, agent_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        query_vec = self.embedder.embed_text(query)
        results = []

        for item in self._in_memory_store:
            # STRICT TENANT ISOLATION FILTERING
            if item["organization_id"] != organization_id:
                continue
            if item["property_id"] != property_id:
                continue
            if agent_id and item.get("agent_id") and item["agent_id"] != agent_id:
                continue

            # Compute Cosine Similarity
            dot_product = sum(a * b for a, b in zip(query_vec, item["embedding"]))
            results.append({
                "id": item["id"],
                "content": item["content"],
                "score": dot_product,
                "metadata": item["metadata"]
            })

        # Sort by similarity score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
