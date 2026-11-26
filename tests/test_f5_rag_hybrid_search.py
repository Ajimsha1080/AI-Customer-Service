import pytest
import asyncio
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete

from apps.api.main import app
from services.database.session import AsyncSessionLocal
from services.database.models import User, Organization, Property, Document, DocumentChunk, UserRole, UserSession
from services.rag.vector_store import RAGVectorService, compute_bm25_scores, reciprocal_rank_fusion
from services.rag.pipeline import RAGPipeline
from apps.api.auth import create_access_token

async def setup_f5_data():
    async with AsyncSessionLocal() as session:
        # Create Org A
        org_a = await session.get(Organization, "org_f5_a")
        if not org_a:
            org_a = Organization(id="org_f5_a", name="Tenant A Hotel", slug="tenant-a-hotel", status="ACTIVE")
            session.add(org_a)

        # Create Org B
        org_b = await session.get(Organization, "org_f5_b")
        if not org_b:
            org_b = Organization(id="org_f5_b", name="Tenant B Hotel", slug="tenant-b-hotel", status="ACTIVE")
            session.add(org_b)

        # Property A
        prop_a = await session.get(Property, "prop_f5_a")
        if not prop_a:
            prop_a = Property(id="prop_f5_a", organization_id="org_f5_a", name="Hotel A")
            session.add(prop_a)

        # Property B
        prop_b = await session.get(Property, "prop_f5_b")
        if not prop_b:
            prop_b = Property(id="prop_f5_b", organization_id="org_f5_b", name="Hotel B")
            session.add(prop_b)

        # Admin user for Org A
        user_a = await session.get(User, "user_f5_admin_a")
        if not user_a:
            user_a = User(
                id="user_f5_admin_a",
                organization_id="org_f5_a",
                email="admin_a@test.com",
                full_name="Admin Tenant A",
                hashed_password="hashed_pw_f5",
                role=UserRole.ADMIN,
                is_active=True,
                email_verified=True
            )
            session.add(user_a)

        await session.commit()

    token_a = create_access_token(data={"sub": "user_f5_admin_a", "org": "org_f5_a", "role": "admin"})
    async with AsyncSessionLocal() as session:
        session_hash = hashlib.sha256(token_a.encode()).hexdigest()
        sess_id = f"sess_f5_{uuid.uuid4().hex[:6]}"
        sess = UserSession(
            id=sess_id,
            user_id="user_f5_admin_a",
            organization_id="org_f5_a",
            session_token_hash=session_hash,
            is_revoked=False,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2)
        )
        session.add(sess)
        await session.commit()

    return {"token_a": token_a, "org_a": "org_f5_a", "prop_a": "prop_f5_a", "org_b": "org_f5_b", "prop_b": "prop_f5_b"}

@pytest.mark.asyncio
async def test_f5_chunk_size_and_overlap():
    pipeline = RAGPipeline()
    # Create long text of 1200 words
    long_words = [f"word{i}" for i in range(1200)]
    long_text = " ".join(long_words)

    # Chunk with 500 size and 50 overlap
    chunks = pipeline.chunk_text(long_text, chunk_size=500, overlap=50)
    assert len(chunks) == 3
    # First chunk has 500 words
    assert len(chunks[0].split()) == 500
    # Overlap check: words 450 to 499 appear in both chunk 0 and chunk 1
    assert "word450" in chunks[0] and "word450" in chunks[1]

@pytest.mark.asyncio
async def test_f5_hybrid_search_bm25_and_rrf():
    rag = RAGVectorService()
    org_id = "org_f5_a"
    prop_id = "prop_f5_a"

    # Clean existing docs for this test org
    async with AsyncSessionLocal() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.metadata_json["organization_id"].as_string() == org_id))
        await session.execute(delete(Document).where(Document.organization_id == org_id))
        await session.commit()

    # Ingest two documents
    doc1_id = str(uuid.uuid4())
    content1 = "The rooftop swimming pool opens at 7:00 AM and closes at 10:00 PM. Towels are provided at the pool deck."
    await rag.add_document_async(doc1_id, "Pool Information", content1, {
        "organization_id": org_id,
        "property_id": prop_id
    })

    doc2_id = str(uuid.uuid4())
    content2 = "High-speed Wi-Fi network is available throughout the property. The guest password is AzureGuest2026."
    await rag.add_document_async(doc2_id, "WiFi Instructions", content2, {
        "organization_id": org_id,
        "property_id": prop_id
    })

    # BM25 Keyword Search
    bm25_res = await rag.bm25_search_async(query="swimming pool towels", organization_id=org_id, property_id=prop_id)
    assert len(bm25_res) > 0
    assert "swimming pool" in bm25_res[0]["content"].lower()

    # Hybrid Search with RRF
    hybrid_res = await rag.hybrid_search_async(query="swimming pool hours", organization_id=org_id, property_id=prop_id)
    assert len(hybrid_res) > 0
    assert "pool" in hybrid_res[0]["content"].lower()
    assert "rrf_score" in hybrid_res[0]

@pytest.mark.asyncio
async def test_f5_tenant_scoping_isolation():
    data = await setup_f5_data()
    rag = RAGVectorService()

    # Seed doc in Org B
    doc_b_id = str(uuid.uuid4())
    content_b = "Secret confidential financial report for Tenant B hotel operations."
    await rag.add_document_async(doc_b_id, "Tenant B Secret", content_b, {
        "organization_id": data["org_b"],
        "property_id": data["prop_b"]
    })

    # Search with Org A's credentials and context
    search_a = await rag.hybrid_search_async(
        query="confidential financial report",
        organization_id=data["org_a"],
        property_id=data["prop_a"]
    )
    # Must NOT find any chunk of Tenant B
    assert not any("financial report" in r["content"].lower() for r in search_a)
    assert not any(r.get("metadata", {}).get("organization_id") == data["org_b"] for r in search_a)

    # Search with Org B's context finds the document
    search_b = await rag.hybrid_search_async(
        query="confidential financial report",
        organization_id=data["org_b"],
        property_id=data["prop_b"]
    )
    assert len(search_b) > 0
    assert any("financial report" in r["content"].lower() for r in search_b)
    assert all(r.get("metadata", {}).get("organization_id") == data["org_b"] for r in search_b)

@pytest.mark.asyncio
async def test_f5_reindexing_on_update_and_delete():
    data = await setup_f5_data()
    token = data["token_a"]
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Upload initial document
        upload_res = await client.post(
            "/api/v1/knowledge/documents",
            json={
                "organization_id": data["org_a"],
                "property_id": data["prop_a"],
                "title": "Gym Policies",
                "content": "The gym is accessible with keycard from 6:00 AM to 8:00 PM.",
                "document_type": "txt"
            },
            headers=headers
        )
        assert upload_res.status_code == 200
        doc_id = upload_res.json()["id"]

        # 2. Update document content (Re-indexing)
        update_res = await client.put(
            f"/api/v1/knowledge/documents/{doc_id}",
            json={
                "organization_id": data["org_a"],
                "property_id": data["prop_a"],
                "title": "Gym Policies Updated",
                "content": "The fitness center is now open 24 hours daily with biometric access."
            },
            headers=headers
        )
        assert update_res.status_code == 200
        assert update_res.json()["status"] == "INDEXED"

        # Query updated content
        query_res = await client.post(
            "/api/v1/rag/query",
            json={
                "organization_id": data["org_a"],
                "property_id": data["prop_a"],
                "query": "biometric access 24 hours"
            },
            headers=headers
        )
        assert query_res.status_code == 200
        assert len(query_res.json()["results"]) > 0
        assert "biometric" in query_res.json()["results"][0]["content"]

        # 3. Delete document
        del_res = await client.delete(
            f"/api/v1/knowledge/documents/{doc_id}?organization_id={data['org_a']}",
            headers=headers
        )
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True

        # Verify chunks deleted from DB
        async with AsyncSessionLocal() as session:
            stmt = select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
            res = await session.execute(stmt)
            assert len(res.scalars().all()) == 0

@pytest.mark.asyncio
async def test_f5_empty_query_and_zero_results():
    data = await setup_f5_data()
    token = data["token_a"]
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Empty query string
        res_empty = await client.post(
            "/api/v1/rag/query",
            json={
                "organization_id": data["org_a"],
                "property_id": data["prop_a"],
                "query": "   "
            },
            headers=headers
        )
        assert res_empty.status_code == 200
        assert res_empty.json()["results"] == []

        # Non-matching nonsense query
        res_none = await client.post(
            "/api/v1/rag/query",
            json={
                "organization_id": data["org_a"],
                "property_id": data["prop_a"],
                "query": "xyzunobtainiumrandomword9999"
            },
            headers=headers
        )
        assert res_none.status_code == 200
        # Zero matching chunks handled gracefully
        assert isinstance(res_none.json()["results"], list)
