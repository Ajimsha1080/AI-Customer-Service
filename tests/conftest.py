import os
import sys

# Ensure repository root is in python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import pytest
import pytest_asyncio
from sqlalchemy import select
from services.database.session import AsyncSessionLocal, engine, Base
import services.database.models
from services.database.models import User, Organization, UserRole
from apps.api.auth import hash_password

@pytest_asyncio.fixture(autouse=True, scope="function")
async def prepare_db():
    """Ensure DB schema and clean test fixtures exist for tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        res_org = await db.execute(select(Organization).where(Organization.id == "org_azure_group"))
        org = res_org.scalar_one_or_none()
        if not org:
            org = Organization(id="org_azure_group", name="Azure Palm Hostel", slug="azure-palm-hostel")
            db.add(org)
            await db.flush()

        users_to_seed = [
            ("usr_admin_01", "admin@azurehostel.com", UserRole.OWNER, "admin123"),
            ("usr_demo123", "demo@azurehostel.com", UserRole.STAFF, "admin123"),
            ("usr_viewer_01", "viewer@azurehostel.com", UserRole.VIEWER, "viewer123"),
            ("usr_superadmin", "superadmin@azurehostel.com", UserRole.SUPER_ADMIN, "superadmin123"),
        ]

        for u_id, email, role, pwd in users_to_seed:
            res_u = await db.execute(select(User).where(User.id == u_id))
            if not res_u.scalar_one_or_none():
                u_obj = User(
                    id=u_id,
                    organization_id=org.id,
                    email=email,
                    hashed_password=hash_password(pwd),
                    full_name=email.split("@")[0].title(),
                    role=role,
                    is_active=True
                )
                db.add(u_obj)
        await db.commit()
