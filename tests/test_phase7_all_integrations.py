import pytest
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from services.rag.storage import get_storage_provider, LocalStorageProvider
from services.tasks.worker import async_ingest_and_embed_document

@pytest.mark.asyncio
async def test_whatsapp_webhook_verification():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/integrations/whatsapp/webhook?hub.mode=subscribe&hub.challenge=123456&hub.verify_token=hospitality_whatsapp_verify_token")
        assert res.status_code == 200
        assert res.json() == 123456

@pytest.mark.asyncio
async def test_storage_provider_resolution():
    provider = get_storage_provider()
    assert provider is not None
    res = provider.save_file("test_doc.pdf", b"pdf content", "application/pdf")
    assert res["file_key"] == "test_doc.pdf"
    assert provider.delete_file("test_doc.pdf") is True

@pytest.mark.asyncio
async def test_background_worker_task():
    res = await async_ingest_and_embed_document({}, "doc_task_01", "Test Doc", "Sample text", {"organization_id": "org_azure_group", "property_id": "prop_azure_palm_resort"})
    assert res["status"] == "SUCCESS"
    assert res["doc_id"] == "doc_task_01"
