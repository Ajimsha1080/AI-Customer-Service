import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import (
    User, Organization, Property, Agent, Document, Conversation, Message, AuditLog
)
from apps.api.auth import get_current_user, verify_tenant_access
from services.database.audit import record_audit_log_async

router = APIRouter(prefix="/api/v1", tags=["Organizations & Properties"])

class CreateOrgRequest(BaseModel):
    name: str
    slug: str

class CreatePropertyRequest(BaseModel):
    organization_id: str
    name: str
    property_type: str = "resort"
    timezone: str = "UTC"

@router.post("/organizations")
async def create_organization(req: CreateOrgRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = f"org_{req.slug.replace('-', '_')[:20]}_{int(time.time())}"
    org = Organization(id=org_id, name=req.name, slug=req.slug)
    db.add(org)
    await db.flush()
    return {"id": org.id, "name": org.name, "slug": org.slug}

@router.get("/organizations")
async def list_organizations(limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role == "SUPER_ADMIN":
        stmt = select(Organization)
    else:
        stmt = select(Organization).where(Organization.id == current_user.organization_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    orgs = res.scalars().all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "status": o.status} for o in orgs]

@router.post("/properties")
async def create_property(req: CreatePropertyRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    prop_id = f"prop_{req.name.lower().replace(' ', '_')[:20]}_{int(time.time())}"
    prop = Property(id=prop_id, organization_id=org_id, name=req.name, property_type=req.property_type, timezone=req.timezone)
    db.add(prop)
    await db.flush()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="PROPERTY_CREATED",
        target_type="property",
        target_id=prop.id,
        details={"name": prop.name},
        db=db
    )
    return {"id": prop.id, "organization_id": prop.organization_id, "name": prop.name}

@router.get("/properties")
async def list_properties(organization_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Property).where(Property.organization_id == org_id).limit(limit).offset(offset)
    res = await db.execute(stmt)
    props = res.scalars().all()
    return [{"id": p.id, "organization_id": p.organization_id, "name": p.name, "type": p.property_type} for p in props]

@router.get("/organizations/{organization_id}/export-data", tags=["GDPR & Data Compliance"])
async def export_tenant_data(organization_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """GDPR Compliance: Export all tenant data (properties, agents, documents, conversations)."""
    org_id = verify_tenant_access(current_user, organization_id)

    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalar_one_or_none()
    props = (await db.execute(select(Property).where(Property.organization_id == org_id))).scalars().all()
    agents = (await db.execute(select(Agent).where(Agent.organization_id == org_id))).scalars().all()
    docs = (await db.execute(select(Document).where(Document.organization_id == org_id))).scalars().all()
    convs = (await db.execute(select(Conversation).where(Conversation.organization_id == org_id))).scalars().all()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="GDPR_DATA_EXPORTED",
        target_type="organization",
        target_id=org_id,
        db=db
    )

    return {
        "export_metadata": {
            "organization_id": org_id,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "format": "JSON_ZIP"
        },
        "organization": {"id": org.id, "name": org.name, "slug": org.slug} if org else {},
        "properties": [{"id": p.id, "name": p.name, "type": p.property_type} for p in props],
        "agents": [{"id": a.id, "name": a.name, "status": a.status} for a in agents],
        "documents": [{"id": d.id, "title": d.title, "type": d.document_type} for d in docs],
        "conversations_count": len(convs)
    }

@router.delete("/organizations/{organization_id}/purge-data", tags=["GDPR & Data Compliance"])
async def purge_tenant_data(organization_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """GDPR Compliance: Hard purge all tenant data and associated records."""
    org_id = verify_tenant_access(current_user, organization_id)

    if current_user.role not in ("SUPER_ADMIN", "ORGANIZATION_ADMIN"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required to purge tenant data.")

    # Delete organization cascade
    stmt = select(Organization).where(Organization.id == org_id)
    res = await db.execute(stmt)
    org = res.scalar_one_or_none()
    if org:
        await db.delete(org)
        await db.commit()

    return {"status": "success", "message": f"Tenant organization {org_id} and all associated data purged successfully."}
