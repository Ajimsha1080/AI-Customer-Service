import os
import sys

# Ensure repository root is in python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from services.database.session import AsyncSessionLocal, engine, Base
import services.database.models
from services.database.models import User, Organization, UserRole, Property, LiveUpdate, Restaurant, Agent, AgentType
from apps.api.auth import hash_password

@pytest_asyncio.fixture(autouse=True, scope="function")
async def prepare_db():
    """Ensure DB schema and clean test fixtures exist for tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM agents WHERE agent_type NOT IN ('CONCIERGE', 'BOOKING', 'AVAILABILITY', 'SUPPORT', 'ACTIVITIES', 'RESTAURANT', 'VOICE', 'HOSTEL_AI_AGENT')"))
        await db.flush()
        res_org = await db.execute(select(Organization).where(Organization.id == "org_azure_group"))
        org = res_org.scalar_one_or_none()
        if not org:
            org = Organization(id="org_azure_group", name="Azure Palm Hostel", slug="azure-palm-hostel", mfa_enforced=False, status="active")
            db.add(org)
            await db.flush()
        else:
            org.mfa_enforced = False
            org.status = "active"

        res_prop = await db.execute(select(Property).where(Property.id == "prop_azure_palm_resort"))
        prop = res_prop.scalar_one_or_none()
        if not prop:
            prop = Property(
                id="prop_azure_palm_resort",
                organization_id="org_azure_group",
                name="Azure Palm Resort",
                property_type="RESORT",
                address="100 Ocean Drive",
                timezone="America/New_York",
                currency="USD"
            )
            db.add(prop)
            await db.flush()

        res_agt = await db.execute(select(Agent).where(Agent.id == "agt_hostel_01"))
        if not res_agt.scalar_one_or_none():
            db.add(Agent(
                id="agt_hostel_01",
                organization_id="org_azure_group",
                property_id="prop_azure_palm_resort",
                name="Azure Palm Concierge",
                agent_type=AgentType.CONCIERGE,
                status="ACTIVE"
            ))

        res_notice = await db.execute(select(LiveUpdate).where(LiveUpdate.property_id == "prop_azure_palm_resort"))
        if not res_notice.scalar_one_or_none():
            db.add(LiveUpdate(
                id="notice_default_1",
                organization_id="org_azure_group",
                property_id="prop_azure_palm_resort",
                title="Welcome to Azure Palm",
                content="Breakfast is served from 7 AM to 10 AM daily in the main hall.",
                type="ANNOUNCEMENT",
                priority="NORMAL",
                is_active=True
            ))

        res_rest = await db.execute(select(Restaurant).where(Restaurant.property_id == "prop_azure_palm_resort"))
        if not res_rest.scalar_one_or_none():
            db.add(Restaurant(
                id="rest_default_1",
                organization_id="org_azure_group",
                property_id="prop_azure_palm_resort",
                name="Azure Palm Dining",
                cuisine="Multicuisine",
                status="Open",
                menu_json={
                    "breakfast": ["Pancakes", "Coffee", "Fruit bowl"],
                    "lunch": ["Grilled Salmon", "Caesar Salad"],
                    "dinner": ["Ribeye Steak", "Lobster Pasta", "Red Wine"]
                },
                operating_hours="07:00 AM - 11:00 PM"
            ))

        users_to_seed = [
            ("usr_admin_01", "admin@azurehostel.com", UserRole.OWNER, "admin123"),
            ("usr_demo123", "demo@azurehostel.com", UserRole.STAFF, "admin123"),
            ("usr_viewer_01", "viewer@azurehostel.com", UserRole.VIEWER, "viewer123"),
            ("usr_superadmin", "superadmin@azurehostel.com", UserRole.SUPER_ADMIN, "superadmin123"),
        ]

        for u_id, email, role, pwd in users_to_seed:
            res_u = await db.execute(select(User).where(User.id == u_id))
            u_obj = res_u.scalar_one_or_none()
            if not u_obj:
                u_obj = User(
                    id=u_id,
                    organization_id=org.id,
                    email=email,
                    hashed_password=hash_password(pwd),
                    full_name=email.split("@")[0].title(),
                    role=role,
                    is_active=True,
                    mfa_enabled=False
                )
                db.add(u_obj)
            else:
                u_obj.mfa_enabled = False
                u_obj.is_active = True
                u_obj.locked_until = None
                u_obj.failed_login_attempts = 0
        await db.commit()

@pytest_asyncio.fixture
async def db_session():
    """Provides an isolated database session for tests."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()

