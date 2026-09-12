import pytest
import asyncio
from services.rag.pipeline import RAGPipeline

@pytest.mark.asyncio
async def test_rag_pipeline_ingest_and_delete():
    pipeline = RAGPipeline()
    org_id = "org_test_group"
    prop_id = "prop_test_hostel"

    # Ingest test document
    result = await pipeline.ingest_document(
        title="Hostel Pool & Gym Timings",
        content="The hostel swimming pool opens at 06:00 AM and closes at 09:00 PM daily. The fitness gym is open 24 hours for all resident guests.",
        document_type="txt",
        organization_id=org_id,
        property_id=prop_id
    )

    assert result["chunks_created"] > 0
    assert result["organization_id"] == org_id
    assert result["property_id"] == prop_id

    # Retrieve context
    context = await pipeline.retrieve_context(
        query="What time does the swimming pool open?",
        organization_id=org_id,
        property_id=prop_id
    )
    assert "swimming pool opens at 06:00 AM" in context

    # Delete document from RAG storage
    deleted = await pipeline.delete_document(
        document_id="Hostel Pool & Gym Timings",
        organization_id=org_id,
        property_id=prop_id
    )
    assert deleted is True
