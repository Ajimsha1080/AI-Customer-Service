import pytest
import io
import os
import uuid
from httpx import AsyncClient, ASGITransport
from sqlalchemy import delete
from apps.api.main import app
from services.agent_runtime.tools import HospitalityToolRegistry
from services.database.session import AsyncSessionLocal
from services.database.models import (
    User, Organization, Property, Room, Facility, Restaurant, Activity,
    RatePlan, Resident, SupportTicket, Reservation, Document
)
from services.rag.embeddings import MockEmbeddingProvider
from services.rag.vector_store import RAGVectorService
rag_service = RAGVectorService()
from apps.api.auth import create_access_token

@pytest.fixture
def auth_headers():
    token = create_access_token({
        "sub": "user_p2_admin",
        "email": "p2admin@azure.com",
        "role": "ORGANIZATION_ADMIN",
        "organization_id": "org_p2_test"
    })
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def viewer_headers():
    token = create_access_token({
        "sub": "user_p2_viewer",
        "email": "p2viewer@azure.com",
        "role": "VIEWER",
        "organization_id": "org_p2_test"
    })
    return {"Authorization": f"Bearer {token}"}

async def ensure_p2_db():
    async with AsyncSessionLocal() as session:
        org = await session.get(Organization, "org_p2_test")
        if not org:
            org = Organization(id="org_p2_test", name="P2 Test Org", slug="p2-test-org")
            session.add(org)
        prop = await session.get(Property, "prop_p2_test")
        if not prop:
            prop = Property(id="prop_p2_test", organization_id="org_p2_test", name="P2 Resort", address="100 Ocean Dr, Miami")
            session.add(prop)
        
        user_admin = await session.get(User, "user_p2_admin")
        if not user_admin:
            user_admin = User(
                id="user_p2_admin",
                organization_id="org_p2_test",
                email="p2admin@azure.com",
                hashed_password="mock_argon2_hashed_password_for_testing",
                full_name="P2 Admin",
                role="ORGANIZATION_ADMIN",
                is_active=True
            )
            session.add(user_admin)

        user_viewer = await session.get(User, "user_p2_viewer")
        if not user_viewer:
            user_viewer = User(
                id="user_p2_viewer",
                organization_id="org_p2_test",
                email="p2viewer@azure.com",
                hashed_password="mock_argon2_hashed_password_for_testing",
                full_name="P2 Viewer",
                role="VIEWER",
                is_active=True
            )
            session.add(user_viewer)

        await session.execute(delete(Document).where(Document.organization_id == "org_p2_test"))
        await session.commit()

@pytest.mark.asyncio
async def test_production_environment_rejects_mock_embedding():
    os.environ["ENVIRONMENT"] = "production"
    try:
        with pytest.raises(RuntimeError, match="Mock embeddings cannot be used in production"):
            MockEmbeddingProvider()
    finally:
        os.environ["ENVIRONMENT"] = "testing"

@pytest.mark.asyncio
async def test_rag_ingest_and_real_similarity_search():
    await ensure_p2_db()
    org_id = "org_p2_test"
    prop_id = "prop_p2_test"
    doc_id = str(uuid.uuid4())
    content = "The Azure Palm infinity pool is located on the 4th floor terrace and opens from 7 AM to 10 PM daily."

    # Ingest document
    chunk_ids = await rag_service.add_document_async(
        doc_id=doc_id,
        title="Pool Information Guide",
        content=content,
        metadata={"organization_id": org_id, "property_id": prop_id}
    )
    assert len(chunk_ids) > 0

    # Search document
    results = await rag_service.similarity_search(
        query="When is the pool open?",
        organization_id=org_id,
        property_id=prop_id,
        top_k=2
    )
    assert len(results) > 0
    assert any("infinity pool" in r["content"].lower() for r in results)
    assert "score" in results[0]

@pytest.mark.asyncio
async def test_multipart_knowledge_upload(auth_headers):
    await ensure_p2_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        file_bytes = b"Executive Suite amenities include a private sauna, 24/7 butler service, and complimentary champagne."
        files = {
            "file": ("amenities.txt", io.BytesIO(file_bytes), "text/plain")
        }
        data = {
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "title": "Executive Suite Amenities",
            "category": "amenities"
        }
        res = await client.post(
            "/api/v1/knowledge/documents/upload",
            headers=auth_headers,
            data=data,
            files=files
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "INDEXED"
        assert body["bytes_processed"] > 0
        assert body["id"] is not None

@pytest.mark.asyncio
async def test_hospitality_crud_endpoints(auth_headers, viewer_headers):
    await ensure_p2_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create Room (Admin allowed)
        room_payload = {
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "room_number": "501",
            "room_type": "Penthouse Suite",
            "price_per_night": 650.0,
            "max_occupancy": 4
        }
        res = await client.post("/api/v1/rooms", headers=auth_headers, json=room_payload)
        assert res.status_code == 201, res.text
        room_data = res.json()
        room_id = room_data["id"]
        assert room_data["room_number"] == "501"

        # 2. Get Rooms (Viewer allowed)
        res = await client.get("/api/v1/rooms?organization_id=org_p2_test&property_id=prop_p2_test", headers=viewer_headers)
        assert res.status_code == 200
        items = res.json()
        assert any(r["id"] == room_id for r in items)

        # 3. Create Restaurant with aliases opening_time / closing_time / cuisine_type
        rest_payload = {
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "name": "Azure Blue Bistro",
            "cuisine_type": "Mediterranean",
            "opening_time": "11:00",
            "closing_time": "23:00"
        }
        res = await client.post("/api/v1/restaurants", headers=auth_headers, json=rest_payload)
        assert res.status_code == 201, res.text
        rest_data = res.json()
        assert rest_data["cuisine_type"] == "Mediterranean"
        assert rest_data["opening_time"] == "11:00"

        # 4. Create Activity with aliases name / location
        act_payload = {
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "name": "Morning Scuba Diving",
            "location": "Reef Marina",
            "time_slot": "09:00 AM - 12:00 PM",
            "price": 85.0
        }
        res = await client.post("/api/v1/activities", headers=auth_headers, json=act_payload)
        assert res.status_code == 201, res.text
        act_data = res.json()
        assert act_data["name"] == "Morning Scuba Diving"
        assert act_data["location"] == "Reef Marina"

        # 5. Create Resident & Support Ticket
        res_resident = await client.post("/api/v1/residents", headers=auth_headers, json={
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "name": "Jane Resident",
            "room_number": "501",
            "email": "jane@resident.com"
        })
        assert res_resident.status_code == 201
        resident_id = res_resident.json()["id"]

        res_ticket = await client.post("/api/v1/support-tickets", headers=auth_headers, json={
            "organization_id": "org_p2_test",
            "property_id": "prop_p2_test",
            "category": "maintenance",
            "room_number": "501",
            "description": "Balcony door lock is sticky"
        })
        assert res_ticket.status_code == 201
        ticket_id = res_ticket.json()["id"]

@pytest.mark.asyncio
async def test_real_tools_zero_fakes():
    await ensure_p2_db()
    registry = HospitalityToolRegistry()
    org_id = "org_p2_test"
    prop_id = "prop_p2_test"
    all_tools = [
        "get_resident_info", "get_request_status", "get_notices",
        "get_food_menu", "create_maintenance_request", "check_room_availability",
        "create_booking", "modify_booking", "cancel_booking"
    ]

    # 1. Unknown resident does NOT return fake "Alex Johnson"
    # When requesting as staff/admin, target_user_id is read from args
    res = await registry.execute_tool(
        "get_resident_info",
        {"resident_id": "res_unknown_999"},
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools,
        user_context={"user_role": "admin"}
    )
    assert res["success"] is True
    assert res["result"]["status"] == "RESIDENT_NOT_FOUND"

    # 2. Unknown ticket does NOT return fake "John Doe"
    res = await registry.execute_tool(
        "get_request_status",
        {"ticket_id": "tkt_unknown_999"},
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools,
        user_context={"user_role": "admin"}
    )
    assert res["success"] is True
    assert res["result"]["status"] == "TICKET_NOT_FOUND"

    # 3. Notices queries real DB (empty if none)
    res = await registry.execute_tool(
        "get_notices",
        {},
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools,
        user_context={"user_role": "admin"}
    )
    assert res["success"] is True
    assert isinstance(res["result"]["notices"], list)

    # 4. Create maintenance request creates real DB SupportTicket
    res = await registry.execute_tool(
        "create_maintenance_request",
        {"issue_description": "AC temperature stuck at 18C", "room_number": "501"},
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools,
        user_context={"user_role": "admin"}
    )
    assert res["success"] is True
    tkt_id = res["result"]["ticket_id"]
    async with AsyncSessionLocal() as session:
        tkt = await session.get(SupportTicket, tkt_id)
        assert tkt is not None
        assert tkt.description == "AC temperature stuck at 18C"
        assert tkt.organization_id == org_id

@pytest.mark.asyncio
async def test_transactional_booking_and_double_booking_prevention():
    await ensure_p2_db()
    registry = HospitalityToolRegistry()
    org_id = "org_p2_test"
    prop_id = "prop_p2_test"
    all_tools = ["create_booking", "modify_booking", "cancel_booking", "check_room_availability"]

    # Seed exactly one room
    async with AsyncSessionLocal() as session:
        room = Room(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            property_id=prop_id,
            room_number="909",
            room_type="Deluxe Ocean View",
            price_per_night=300.0,
            is_available=True
        )
        session.add(room)
        await session.commit()

    # Book room for Oct 10 to Oct 15
    res1 = await registry.execute_tool(
        "create_booking",
        {
            "customer_name": "First Guest",
            "customer_email": "first@guest.com",
            "check_in": "2026-10-10",
            "check_out": "2026-10-15",
            "room_type": "Deluxe Ocean View"
        },
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools
    )
    assert res1["success"] is True
    assert res1["result"]["status"] == "CONFIRMED"
    assert res1["result"]["total_price"] == 1500.0  # 5 nights * 300.0

    # Attempt overlapping booking for same room type (Oct 12 to Oct 14) -> NO_VACANCY
    res2 = await registry.execute_tool(
        "create_booking",
        {
            "customer_name": "Conflicting Guest",
            "customer_email": "second@guest.com",
            "check_in": "2026-10-12",
            "check_out": "2026-10-14",
            "room_type": "Deluxe Ocean View"
        },
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools
    )
    assert res2["success"] is False
    assert res2["status"] == "NO_VACANCY"

    # Non-overlapping booking (Oct 16 to Oct 18) -> SUCCESS
    res3 = await registry.execute_tool(
        "create_booking",
        {
            "customer_name": "Third Guest",
            "customer_email": "third@guest.com",
            "check_in": "2026-10-16",
            "check_out": "2026-10-18",
            "room_type": "Deluxe Ocean View"
        },
        organization_id=org_id,
        property_id=prop_id,
        enabled_tools=all_tools
    )
    assert res3["success"] is True
    assert res3["result"]["status"] == "CONFIRMED"
