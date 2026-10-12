import asyncio
import uuid
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from services.database.session import Base
from services.database.models import (
    Organization, Property, User, Agent, AgentConfig, Room, Facility,
    Restaurant, Activity, LiveUpdate, Reservation, Conversation, Message,
    Document, UserRole, AgentStatus, AgentType
)
from services.rag.pipeline import RAGPipeline
from apps.api.config import settings

from apps.api.auth import hash_password

async def seed_demo_data():
    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        raise RuntimeError("CRITICAL: Seeding demo data is strictly prohibited in production environments.")

    print("Seeding realistic demo dataset for Azure Hospitality Group...")

    try:
        engine = create_async_engine(settings.DATABASE_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        print("Connected to PostgreSQL for seeding.")
    except Exception as e:
        print("PostgreSQL unavailable. Using local SQLite dev database for seeding...")
        sqlite_url = "sqlite+aiosqlite:///./dev_hospitality.db"
        engine = create_async_engine(sqlite_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        # Check if already seeded
        existing_org = (await session.execute(select(Organization).where(Organization.id == "org_azure_group"))).scalar_one_or_none()
        if existing_org:
            print("Database already contains seeded demo records for Azure Hospitality Group. Skipping duplicate insert.")
        else:
            # 1. Organization
            org = Organization(
                id="org_azure_group",
                name="Azure Hospitality Group",
                slug="azure-hospitality-group",
                status="active"
            )
            session.add(org)

            # 2. Properties
            resort = Property(
                id="prop_azure_palm_resort",
                organization_id=org.id,
                name="Azure Palm Resort & Spa",
                property_type="resort",
                timezone="Asia/Kolkata",
                currency="USD",
                address="Coastal Beach Road, Marari, Kerala, India",
                contact_email="concierge@azurepalmresort.com"
            )
            hostel = Property(
                id="prop_azure_palm_hostel",
                organization_id=org.id,
                name="Azure Palm Hostel",
                property_type="hostel",
                timezone="Asia/Kolkata",
                currency="USD",
                address="Fort Kochi Heritage Zone, Kerala, India",
                contact_email="hello@azurepalmhostel.com"
            )
            session.add_all([resort, hostel])

            # 3. Users
            org_admin = User(
                id="usr_azure_admin",
                organization_id=org.id,
                email="admin@azurepalm.com",
                hashed_password=hash_password("AzureDemo2026!"),
                full_name="Azure Group Admin",
                role=UserRole.ORGANIZATION_ADMIN
            )
            staff_user = User(
                id="usr_frontdesk_staff",
                organization_id=org.id,
                email="concierge@azurepalm.com",
                hashed_password=hash_password("AzureDemo2026!"),
                full_name="Front Desk Manager",
                role=UserRole.STAFF
            )
            session.add_all([org_admin, staff_user])

            # 4. Agents
            concierge_agent = Agent(
                id="agt_concierge_01",
                organization_id=org.id,
                property_id=resort.id,
                name="Azure Palm Concierge",
                agent_type=AgentType.CONCIERGE,
                status=AgentStatus.ACTIVE,
                primary_language="English",
                supported_languages=["English", "Malayalam", "Hindi", "Tamil"]
            )
            concierge_config = AgentConfig(
                id="cfg_concierge_01",
                agent_id=concierge_agent.id,
                model_name="gpt-4o-mini",
                system_prompt="You are the head AI Concierge for Azure Palm Resort. Assist guests with amenities, pool hours, dining, and bookings.",
                greeting="Welcome to Azure Palm Resort! How can I assist your stay today?",
                enabled_tools=[
                    "search_property_information", "get_facility_status", "check_room_availability",
                    "create_booking", "get_current_property_updates", "handoff_to_human"
                ],
                enabled_channels=["web_widget", "voice", "whatsapp"]
            )
            session.add_all([concierge_agent, concierge_config])

            # 5. Rooms & Facilities
            room1 = Room(
                id="rm_101",
                property_id=resort.id,
                room_number="101",
                room_type="Deluxe Ocean Suite",
                price_per_night=280.0,
                max_occupancy=3,
                is_available=True,
                description="Luxury ocean-facing suite with private plunge pool and butler service."
            )
            room2 = Room(
                id="rm_201",
                property_id=resort.id,
                room_number="201",
                room_type="Garden Villa",
                price_per_night=450.0,
                max_occupancy=4,
                is_available=True,
                description="Secluded villa surrounded by tropical gardens with outdoor rainforest shower."
            )
            facility_pool = Facility(
                id="fac_pool",
                property_id=resort.id,
                name="Infinity Swimming Pool",
                status="Open",
                opening_time="06:00 AM",
                closing_time="08:00 PM",
                description="Temperature-controlled infinity pool overlooking the Arabian Sea."
            )
            facility_spa = Facility(
                id="fac_spa",
                property_id=resort.id,
                name="Ayurvedic Spa & Wellness",
                status="Open",
                opening_time="08:00 AM",
                closing_time="09:00 PM",
                description="Traditional Panchakarma treatments and therapeutic massages."
            )
            session.add_all([room1, room2, facility_pool, facility_spa])

            # 6. Live Updates
            update1 = LiveUpdate(
                id="upd_bonfire",
                organization_id=org.id,
                property_id=resort.id,
                title="Evening Beach Bonfire",
                content="Beach bonfire starts at 7:30 PM near the south pavilion with complimentary marshmallows.",
                type="EVENT",
                priority="HIGH",
                is_active=True
            )
            session.add(update1)

            await session.commit()
            print("Demo database successfully seeded!")

    # 7. Ingest Demo Document via RAG Pipeline
    pipeline = RAGPipeline()
    await pipeline.ingest_document(
        title="Azure Palm Resort Guest Guide 2026",
        content="Welcome to Azure Palm Resort & Spa. Check-in is at 3:00 PM and check-out is at 11:00 AM. Breakfast is served at Spice Route Fine Dining from 7:00 AM to 10:30 AM. High-speed Wi-Fi network 'Azure_Guest' is available without password across all villas.",
        document_type="pdf",
        organization_id="org_azure_group",
        property_id="prop_azure_palm_resort",
        agent_id="agt_concierge_01"
    )
    print("Demo RAG vector knowledge base successfully indexed.")

if __name__ == "__main__":
    asyncio.run(seed_demo_data())
