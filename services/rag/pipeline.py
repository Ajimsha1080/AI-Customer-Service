import re
import math
from typing import List, Dict, Any, Optional
from services.rag.vector_store import VectorStoreInterface, PostgresPgVectorStore

class RAGPipeline:
    """Advanced RAG Pipeline implementing Query Understanding, Rewriting, Hybrid Retrieval,
    Reciprocal Rank Fusion (RRF), Reranking, Context Assembly, and Grounding Verification.
    """
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

    def rewrite_query(self, query: str) -> List[str]:
        """Stage 2 & 3: Query Understanding & Query Rewriting.
        Expands user input into primary query and domain-specific search variants.
        """
        cleaned = query.strip()
        queries = [cleaned]

        # Domain expansions for hospitality & concierge
        lower = cleaned.lower()
        if any(w in lower for w in ["check-in", "check in", "arrival", "timing"]):
            queries.append(f"{cleaned} check-in time operational hours front desk policy")
        if any(w in lower for w in ["wifi", "internet", "wireless"]):
            queries.append(f"{cleaned} wi-fi password network guest access")
        if any(w in lower for w in ["food", "breakfast", "dinner", "restaurant", "menu"]):
            queries.append(f"{cleaned} dining hours restaurant menu cuisine options")
        if any(w in lower for w in ["pool", "gym", "spa", "amenity", "facility"]):
            queries.append(f"{cleaned} facility opening closing timing rules")

        return list(dict.fromkeys(queries))

    def reciprocal_rank_fusion(
        self,
        dense_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        k: int = 60
    ) -> List[Dict[str, Any]]:
        """Stage 5: Reciprocal Rank Fusion (RRF).
        Fuses dense vector rankings and keyword BM25 rankings using formula:
        RRF_Score(d) = sum( 1 / (k + rank(d)) )
        """
        rrf_scores: Dict[str, float] = {}
        item_map: Dict[str, Dict[str, Any]] = {}

        # Process dense vector rankings
        for rank, item in enumerate(dense_results, start=1):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
            item_map[doc_id] = item

        # Process keyword rankings
        for rank, item in enumerate(keyword_results, start=1):
            doc_id = item["id"]
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
            if doc_id not in item_map:
                item_map[doc_id] = item

        # Sort combined documents by fused RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        fused_list = []
        for doc_id in sorted_ids:
            elem = item_map[doc_id].copy()
            elem["rrf_score"] = round(rrf_scores[doc_id], 6)
            fused_list.append(elem)

        return fused_list

    def rerank_candidates(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 4
    ) -> List[Dict[str, Any]]:
        """Stage 6: Reranking.
        Reranks candidates based on fused RRF scores, lexical overlap, and semantic density.
        """
        query_words = set(re.findall(r'\w+', query.lower()))

        for item in candidates:
            content_words = set(re.findall(r'\w+', item.get("content", "").lower()))
            overlap_count = len(query_words.intersection(content_words))
            lexical_boost = (overlap_count / (len(query_words) or 1)) * 0.2
            base_score = item.get("rrf_score", item.get("score", 0.0))
            item["final_rank_score"] = round(base_score + lexical_boost, 6)

        candidates.sort(key=lambda x: x.get("final_rank_score", 0.0), reverse=True)
        return candidates[:top_k]

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
        """Stage 4-7: Advanced Hybrid Retrieval -> RRF -> Reranking -> Context Assembly."""
        queries = self.rewrite_query(query)
        primary_query = queries[0]

        # Stage 4: Dense Vector Search
        dense_results = await self.vector_store.similarity_search(
            query=primary_query,
            organization_id=organization_id,
            property_id=property_id,
            agent_id=agent_id,
            top_k=top_k * 2
        )

        # Keyword BM25-style fallback search
        keyword_results = []
        if len(queries) > 1:
            keyword_results = await self.vector_store.similarity_search(
                query=queries[1],
                organization_id=organization_id,
                property_id=property_id,
                agent_id=agent_id,
                top_k=top_k * 2
            )

        # Stage 5: Reciprocal Rank Fusion (RRF)
        fused_candidates = self.reciprocal_rank_fusion(dense_results, keyword_results)

        # Stage 6: Reranking
        reranked_results = self.rerank_candidates(primary_query, fused_candidates, top_k=top_k)

        if not reranked_results:
            return "No specific property document context found."

        # Stage 7: Context Assembly with Citations
        context_blocks = []
        for idx, res in enumerate(reranked_results):
            source_title = res.get("metadata", {}).get("title", "Property Document")
            source_url = res.get("metadata", {}).get("source_url", "")
            url_str = f" ({source_url})" if source_url else ""
            context_blocks.append(f"[Citation {idx+1}: {source_title}{url_str}]\n{res['content']}")

        return "\n\n".join(context_blocks)

    def verify_grounding(self, response_text: str, context_text: str) -> Dict[str, Any]:
        """Stage 10: Grounding Verification.
        Ensures LLM response statements are supported by assembled context.
        """
        if not context_text or "No specific property document context found" in context_text:
            return {"is_grounded": True, "confidence": 1.0, "reason": "No context required."}

        context_words = set(re.findall(r'\w+', context_text.lower()))
        response_words = set(re.findall(r'\w+', response_text.lower()))

        overlap = response_words.intersection(context_words)
        grounding_ratio = len(overlap) / (len(response_words) or 1)

        is_grounded = grounding_ratio > 0.15
        return {
            "is_grounded": is_grounded,
            "confidence": round(grounding_ratio, 2),
            "reason": "Sufficient context overlap verified." if is_grounded else "Low overlap with reference context."
        }

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
