import pytest
import os
import tempfile
import subprocess
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from apps.api.auth import create_access_token
from services.rag.vector_store import PostgresPgVectorStore
from services.rag.pipeline import RAGPipeline
from services.billing.metering import UsageMeteringService

@pytest.mark.asyncio
async def test_vector_store_persistence_and_paraphrase_semantic_search():
    """Phase 2 Acceptance Criteria 1 & 2:
    1. Documents survive process restart (database persistence).
    2. Paraphrased query matches semantically relevant document over exact keyword match.
    """
    pipeline = RAGPipeline()
    org_id = "org_azure_group"
    prop_id = "prop_azure_palm_resort"

    # Ingest document
    doc_content = "Resort swimming pool operating hours are strictly 06:00 AM to 10:00 PM daily. High-speed Wi-Fi network password is AzurePalm2026."
    await pipeline.ingest_document(
        title="Pool and Wifi Information Guide",
        content=doc_content,
        document_type="guide",
        organization_id=org_id,
        property_id=prop_id
    )

    # 1. Paraphrased query semantic search (query uses different words)
    paraphrased_query = "When can guests swim in the water pool?"
    context = await pipeline.retrieve_context(
        query=paraphrased_query,
        organization_id=org_id,
        property_id=prop_id
    )

    assert "swimming pool operating hours" in context
    assert "06:00 AM to 10:00 PM" in context

    # 2. Process Restart Simulation: Instantiate a fresh VectorStore instance
    fresh_vector_store = PostgresPgVectorStore()
    fresh_pipeline = RAGPipeline(vector_store=fresh_vector_store)

    # Search paraphrased query on fresh instance -> Proves DB persistence across process restart
    wifi_query = "What is the internet access credential code?"
    persisted_context = await fresh_pipeline.retrieve_context(
        query=wifi_query,
        organization_id=org_id,
        property_id=prop_id
    )

    assert "Wi-Fi network password is AzurePalm2026" in persisted_context

@pytest.mark.asyncio
async def test_usage_metering_db_persistence():
    """Phase 2 Acceptance Criterion: UsageMeteringService events persist to database."""
    metering = UsageMeteringService()
    org_id = "org_azure_group"
    prop_id = "prop_azure_palm_resort"

    # Record event
    event = await metering.record_usage_event_async(
        organization_id=org_id,
        property_id=prop_id,
        agent_id="agt_hostel_01",
        event_type="llm_generation",
        provider="openai",
        quantity=500,
        unit="tokens"
    )
    assert event["id"].startswith("evt_")

    # Retrieve summary from DB persistence
    summary = await metering.get_organization_usage_summary_async(org_id)
    assert summary["total_events_logged"] >= 1
    assert summary["total_tokens_consumed"] >= 500

@pytest.mark.asyncio
async def test_alembic_upgrade_head_on_empty_db():
    """Phase 2 Acceptance Criterion: alembic upgrade head runs cleanly against an empty database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, "test_alembic_empty.db").replace("\\", "/")
        env = os.environ.copy()
        env["DATABASE_URL"] = f"sqlite+aiosqlite:///{test_db_path}"

        import sys
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=os.getcwd(),
            env=env,
            capture_output=True,
            text=True
        )

        assert result.returncode == 0, f"Alembic migration failed (stdout: {result.stdout}, stderr: {result.stderr})"

@pytest.mark.asyncio
async def test_list_endpoints_pagination():
    """Phase 2 Requirement: Pagination (limit & offset) on list endpoints."""
    token = create_access_token({"sub": "usr_superadmin", "org_id": "org_azure_group", "role": "SUPER_ADMIN"})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/properties?limit=1&offset=0", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) <= 1
