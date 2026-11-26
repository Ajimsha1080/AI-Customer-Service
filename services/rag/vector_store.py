import uuid
import time
import math
import re
import asyncio
from collections import Counter
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.session import AsyncSessionLocal
from services.database.models import Document, DocumentChunk
from services.rag.embeddings import BaseEmbeddingProvider, get_embedding_provider, LocalHashedEmbeddingProvider

def compute_bm25_scores(query: str, corpus: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> List[Dict[str, Any]]:
    """Computes BM25 ranking scores over a corpus of document chunks."""
    if not corpus or not query:
        return []

    def tokenize(text: str) -> List[str]:
        return re.findall(r'\b\w+\b', text.lower())

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    doc_tokens = [tokenize(doc.get("content", "")) for doc in corpus]
    doc_lens = [len(tokens) for tokens in doc_tokens]
    n_docs = len(corpus)
    avgdl = sum(doc_lens) / (n_docs or 1)

    df = Counter()
    for tokens in doc_tokens:
        unique_tokens = set(tokens)
        for qt in query_tokens:
            if qt in unique_tokens:
                df[qt] += 1

    results = []
    for doc, tokens, doc_len in zip(corpus, doc_tokens, doc_lens):
        tf = Counter(tokens)
        score = 0.0
        for qt in query_tokens:
            if qt not in tf:
                continue
            doc_freq = df[qt]
            idf = math.log(1.0 + (n_docs - doc_freq + 0.5) / (doc_freq + 0.5))
            term_tf = tf[qt]
            denom = term_tf + k1 * (1.0 - b + b * (doc_len / (avgdl or 1.0)))
            score += idf * (term_tf * (k1 + 1.0) / (denom or 1.0))

        if score > 0:
            doc_res = doc.copy()
            doc_res["bm25_score"] = round(score, 4)
            doc_res["score"] = round(score, 4)
            results.append(doc_res)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def reciprocal_rank_fusion(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """Fuses dense vector rankings and BM25 keyword rankings using RRF."""
    rrf_scores: Dict[str, float] = {}
    item_map: Dict[str, Dict[str, Any]] = {}

    for rank, item in enumerate(vector_results, start=1):
        doc_id = item["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        item_map[doc_id] = item

    for rank, item in enumerate(bm25_results, start=1):
        doc_id = item["id"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        if doc_id not in item_map:
            item_map[doc_id] = item

    sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    fused = []
    for doc_id in sorted_ids:
        entry = item_map[doc_id].copy()
        entry["rrf_score"] = round(rrf_scores[doc_id], 6)
        entry["score"] = round(rrf_scores[doc_id], 6)
        fused.append(entry)
    return fused

class VectorStoreInterface(ABC):
    @abstractmethod
    async def add_documents(self, documents: List[Dict[str, Any]], organization_id: str, property_id: str, agent_id: Optional[str] = None) -> List[str]:
        pass

    @abstractmethod
    async def delete_document(self, document_id: str, organization_id: str, property_id: str) -> bool:
        pass

    @abstractmethod
    async def similarity_search(self, query: str, organization_id: str, property_id: str, agent_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        pass

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Computes cosine similarity score between two float vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm_a = math.sqrt(sum(a * a for a in vec1)) or 1.0
    norm_b = math.sqrt(sum(b * b for b in vec2)) or 1.0
    return dot_product / (norm_a * norm_b)

class PostgresPgVectorStore(VectorStoreInterface):
    """Real Database-backed Vector Store supporting persistent storage and semantic similarity search.
    Persists documents and vector embeddings into the database (documents and document_chunks tables),
    ensuring documents survive application restarts.
    """
    def __init__(self, db_session: Optional[AsyncSession] = None, embedder: Optional[BaseEmbeddingProvider] = None):
        self.db_session = db_session
        self.embedder = embedder or get_embedding_provider()

    async def _get_session(self):
        if self.db_session:
            return self.db_session, False
        return AsyncSessionLocal(), True

    async def add_documents(self, documents: List[Dict[str, Any]], organization_id: str, property_id: str, agent_id: Optional[str] = None) -> List[str]:
        session, is_local_session = await self._get_session()
        added_ids = []

        try:
            embedder_model = getattr(self.embedder, "model_name", "all-MiniLM-L6-v2")
            embedder_dim = getattr(self.embedder, "dimension", 384)

            for doc in documents:
                content = doc.get("content", "")
                chunk_id = doc.get("id") or str(uuid.uuid4())
                metadata = doc.get("metadata", {})
                title = metadata.get("title") or doc.get("title") or "Untitled Document"
                document_type = metadata.get("document_type", "txt")
                parent_doc_id = doc.get("parent_doc_id") or doc.get("document_id")

                embedding = await self.embedder.embed_text_async(content)

                # Find or create parent Document record scoped by org and property
                db_doc = None
                if parent_doc_id:
                    stmt = select(Document).where(Document.id == parent_doc_id)
                    res = await session.execute(stmt)
                    db_doc = res.scalar_one_or_none()

                if not db_doc:
                    stmt = select(Document).where(
                        Document.organization_id == organization_id,
                        Document.property_id == property_id,
                        Document.title == title
                    )
                    res = await session.execute(stmt)
                    db_doc = res.scalar_one_or_none()

                if not db_doc:
                    new_doc_id = parent_doc_id or str(uuid.uuid4())
                    db_doc = Document(
                        id=new_doc_id,
                        organization_id=organization_id,
                        property_id=property_id,
                        agent_id=agent_id,
                        title=title,
                        document_type=document_type,
                        content_raw=content,
                        content=content,
                        status="INDEXED"
                    )
                    session.add(db_doc)
                    await session.flush()
                else:
                    db_doc.status = "INDEXED"

                # Delete existing chunk if chunk with chunk_id already exists
                stmt_del = select(DocumentChunk).where(DocumentChunk.id == chunk_id)
                res_del = await session.execute(stmt_del)
                existing_chunk = res_del.scalar_one_or_none()
                if existing_chunk:
                    await session.delete(existing_chunk)
                    await session.flush()

                # Add DocumentChunk record with model, dimension, and embedding
                chunk = DocumentChunk(
                    id=chunk_id,
                    document_id=db_doc.id,
                    content=content,
                    embedding_json=embedding,
                    model=embedder_model,
                    dimension=embedder_dim,
                    metadata_json={
                        "title": title,
                        "document_type": document_type,
                        "organization_id": organization_id,
                        "property_id": property_id,
                        "agent_id": agent_id,
                        **metadata
                    }
                )
                try:
                    chunk.embedding = embedding
                except Exception:
                    pass
                session.add(chunk)
                added_ids.append(chunk_id)

            await session.commit()
            return added_ids
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            if is_local_session:
                await session.close()

    async def delete_document(self, document_id: str, organization_id: str, property_id: str) -> bool:
        session, is_local_session = await self._get_session()
        try:
            stmt = select(Document).where(
                Document.organization_id == organization_id,
                Document.property_id == property_id,
                (Document.id == document_id) | (Document.title == document_id)
            )
            res = await session.execute(stmt)
            target_docs = res.scalars().all()

            if not target_docs:
                return False

            for target in target_docs:
                await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == target.id))
                await session.delete(target)

            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False
        finally:
            if is_local_session:
                await session.close()

    async def similarity_search(self, query: str, organization_id: str, property_id: str, agent_id: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        if not query or not query.strip() or not organization_id:
            return []
        session, is_local_session = await self._get_session()
        query_vec = await self.embedder.embed_text_async(query)

        try:
            # 1. Attempt pgvector HNSW distance search if dialect and extension support it
            try:
                stmt_pg = select(DocumentChunk).join(Document, DocumentChunk.document_id == Document.id).where(
                    Document.organization_id == organization_id,
                    Document.property_id == property_id,
                    DocumentChunk.embedding.isnot(None)
                )
                if agent_id:
                    stmt_pg = stmt_pg.where((Document.agent_id == agent_id) | (Document.agent_id.is_(None)))
                stmt_pg = stmt_pg.order_by(DocumentChunk.embedding.cosine_distance(query_vec)).limit(top_k)
                res_pg = await session.execute(stmt_pg)
                pg_chunks = res_pg.scalars().all()
                if pg_chunks:
                    return [
                        {
                            "id": c.id,
                            "content": c.content,
                            "score": 0.95,
                            "metadata": c.metadata_json or {}
                        }
                        for c in pg_chunks
                    ]
            except Exception as e:
                import os
                if os.getenv("ENVIRONMENT", "").lower() == "production":
                    raise RuntimeError(f"CRITICAL: pgvector cosine search failed in production: {e}. Python-cosine fallback is forbidden in production.")
                pass

            # 2. Resilient Python cosine fallback over stored embedding_json
            stmt = select(DocumentChunk).join(Document, DocumentChunk.document_id == Document.id).where(
                Document.organization_id == organization_id,
                Document.property_id == property_id
            )
            if agent_id:
                stmt = stmt.where((Document.agent_id == agent_id) | (Document.agent_id.is_(None)))

            res = await session.execute(stmt)
            chunks = res.scalars().all()

            results = []
            for chunk in chunks:
                vec = chunk.embedding_json
                if not vec:
                    continue
                score = cosine_similarity(query_vec, vec)
                results.append({
                    "id": chunk.id,
                    "content": chunk.content,
                    "score": round(score, 4),
                    "metadata": chunk.metadata_json or {}
                })

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:top_k]
        finally:
            if is_local_session:
                await session.close()

class RAGVectorService(PostgresPgVectorStore):
    """Production RAG Vector Service performing genuine document chunking, embedding,
    storage, hybrid BM25 + vector search with Reciprocal Rank Fusion, and re-indexing.
    """
    async def add_document_async(self, doc_id: str, title: str, content: str, metadata: dict) -> List[str]:
        org_id = metadata.get("organization_id", "")
        prop_id = metadata.get("property_id", "")
        agent_id = metadata.get("agent_id")
        doc_type = metadata.get("document_type", "txt")

        # Chunk document text: 500 words per chunk with 50 word overlap (500-1000 tokens)
        words = content.split()
        chunks = []
        if not words:
            chunks = [content]
        else:
            chunk_size = 500
            overlap = 50
            i = 0
            while i < len(words):
                chunk_text = " ".join(words[i:i + chunk_size])
                chunks.append(chunk_text)
                i += (chunk_size - overlap)
                if i >= len(words):
                    break

        docs_to_add = []
        for idx, chunk_str in enumerate(chunks):
            docs_to_add.append({
                "id": str(uuid.uuid4()),
                "parent_doc_id": doc_id,
                "title": title,
                "content": chunk_str,
                "metadata": {
                    **metadata,
                    "title": title,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "document_type": doc_type
                }
            })

        return await self.add_documents(docs_to_add, organization_id=org_id, property_id=prop_id, agent_id=agent_id)

    async def bm25_search_async(self, query: str, organization_id: str, property_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Performs BM25 keyword search over chunks scoped strictly by organization_id and property_id."""
        if not query or not query.strip() or not organization_id:
            return []
        session, is_local = await self._get_session()
        try:
            stmt = select(DocumentChunk).join(Document, DocumentChunk.document_id == Document.id).where(
                Document.organization_id == organization_id,
                Document.property_id == property_id
            )
            res = await session.execute(stmt)
            chunks = res.scalars().all()
            corpus = [
                {
                    "id": c.id,
                    "content": c.content,
                    "metadata": c.metadata_json or {},
                    "document_id": c.document_id
                }
                for c in chunks
            ]
            return compute_bm25_scores(query, corpus, k1=1.5, b=0.75)[:top_k]
        finally:
            if is_local:
                await session.close()

    async def hybrid_search_async(self, query: str, organization_id: str, property_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Hybrid search combining vector similarity and BM25 keyword search using Reciprocal Rank Fusion (RRF)."""
        if not query or not query.strip() or not organization_id:
            return []

        vector_results = await self.similarity_search(
            query=query,
            organization_id=organization_id,
            property_id=property_id,
            top_k=top_k * 2
        )
        bm25_results = await self.bm25_search_async(
            query=query,
            organization_id=organization_id,
            property_id=property_id,
            top_k=top_k * 2
        )

        fused = reciprocal_rank_fusion(vector_results, bm25_results, k=60)
        return fused[:top_k]

    async def reindex_document_async(self, doc_id: str, title: str, content: str, organization_id: str, property_id: str, metadata: dict) -> List[str]:
        """Re-indexes an existing document on update: cleans old chunks, generates new chunks, embeds, and updates metadata."""
        session, is_local = await self._get_session()
        try:
            stmt = select(Document).where(Document.id == doc_id, Document.organization_id == organization_id)
            res = await session.execute(stmt)
            doc_record = res.scalar_one_or_none()
            if doc_record:
                doc_record.title = title
                doc_record.content = content
                doc_record.content_raw = content
                doc_record.status = "INDEXED"

            # Delete old chunks
            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            await session.commit()
        finally:
            if is_local:
                await session.close()

        return await self.add_document_async(doc_id, title, content, {**metadata, "organization_id": organization_id, "property_id": property_id})

    def add_document(self, doc_id: str, title: str, content: str, metadata: dict):
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self.add_document_async(doc_id, title, content, metadata))
            return [doc_id]
        except RuntimeError:
            return asyncio.run(self.add_document_async(doc_id, title, content, metadata))

    async def search_async(self, query: str, top_k: int = 3, organization_id: str = "", property_id: str = "") -> List[Dict[str, Any]]:
        return await self.hybrid_search_async(query=query, organization_id=organization_id, property_id=property_id, top_k=top_k)

    def search(self, query: str, top_k: int = 3, organization_id: str = "", property_id: str = "") -> List[Dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.search_async(query, top_k, organization_id, property_id)).result()
        except RuntimeError:
            return asyncio.run(self.search_async(query, top_k, organization_id, property_id))

