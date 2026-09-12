import re
from typing import List, Dict, Any, Optional
from services.rag.vector_store import VectorStoreInterface, PostgresPgVectorStore

class RAGPipeline:
    def __init__(self, vector_store: Optional[VectorStoreInterface] = None):
        self.vector_store = vector_store or PostgresPgVectorStore()

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Splits raw document text into clean overlapping chunks."""
        cleaned_text = re.sub(r'\s+', ' ', text).strip()
        words = cleaned_text.split()
        if not words:
            return []

        chunks = []
        i = 0
        while i < len(words):
            chunk = " ".join(words[i:i + chunk_size])
            chunks.append(chunk)
            i += (chunk_size - overlap)
        return chunks

    async def ingest_document(
        self,
        title: str,
        content: str,
        document_type: str,
        organization_id: str,
        property_id: str,
        agent_id: Optional[str] = None,
        source_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Parses, cleans, chunks, embeds, and stores a document in vector storage."""
        chunks = self.chunk_text(content)
        documents_to_add = []

        for idx, chunk in enumerate(chunks):
            documents_to_add.append({
                "id": f"doc_{title.replace(' ', '_')}_{idx}",
                "content": chunk,
                "metadata": {
                    "title": title,
                    "document_type": document_type,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "source_url": source_url or ""
                }
            })

        chunk_ids = await self.vector_store.add_documents(
            documents=documents_to_add,
            organization_id=organization_id,
            property_id=property_id,
            agent_id=agent_id
        )

        return {
            "title": title,
            "document_type": document_type,
            "chunks_created": len(chunks),
            "chunk_ids": chunk_ids,
            "organization_id": organization_id,
            "property_id": property_id,
            "agent_id": agent_id
        }

    async def retrieve_context(
        self,
        query: str,
        organization_id: str,
        property_id: str,
        agent_id: Optional[str] = None,
        top_k: int = 4
    ) -> str:
        """Retrieves top matching context chunks formatted for LLM context inclusion."""
        results = await self.vector_store.similarity_search(
            query=query,
            organization_id=organization_id,
            property_id=property_id,
            agent_id=agent_id,
            top_k=top_k
        )

        if not results:
            return "No specific property document context found."

        context_blocks = []
        for idx, res in enumerate(results):
            source = res["metadata"].get("title", "Document")
            context_blocks.append(f"[Source {idx+1}: {source}]\n{res['content']}")

        return "\n\n".join(context_blocks)

    async def delete_document(
        self,
        document_id: str,
        organization_id: str,
        property_id: str
    ) -> bool:
        """Deletes document chunks from vector storage."""
        return await self.vector_store.delete_document(
            document_id=document_id,
            organization_id=organization_id,
            property_id=property_id
        )

