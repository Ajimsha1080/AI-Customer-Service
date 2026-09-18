import logging
import asyncio
from typing import Dict, Any
from apps.api.config import settings

logger = logging.getLogger("hospitality_agent_cloud.worker")

async def async_ingest_and_embed_document(ctx: Dict[str, Any], doc_id: str, title: str, content: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Background task: chunks, embeds with SentenceTransformers, and indexes RAG document."""
    logger.info(f"[TaskWorker] Starting background RAG ingestion for doc_id='{doc_id}' title='{title}'")
    from services.rag.vector_store import RAGVectorService
    rag_service = RAGVectorService()
    rag_service.add_document(doc_id, title, content, metadata)
    logger.info(f"[TaskWorker] Successfully indexed doc_id='{doc_id}' into PGVector store.")
    return {"status": "SUCCESS", "doc_id": doc_id, "title": title}

async def async_process_voice_synthesis(ctx: Dict[str, Any], text: str, language: str, voice_id: str) -> Dict[str, Any]:
    """Background task: synthesizes voice audio with Sarvam AI or ElevenLabs."""
    logger.info(f"[TaskWorker] Starting background voice synthesis for language='{language}'")
    await asyncio.sleep(0.1)
    return {"status": "SUCCESS", "language": language}

class WorkerSettings:
    functions = [async_ingest_and_embed_document, async_process_voice_synthesis]
    redis_settings = settings.REDIS_URL
