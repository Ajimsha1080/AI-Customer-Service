import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import (
    User, Organization, Property, Agent, Document, Conversation, Message, AuditLog,
    Invitation, UserRole
)
from apps.api.auth import (
    get_current_user, verify_tenant_access, require_role, verify_password,
    ROLE_HIERARCHY
)
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

class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = "STAFF"

class UpdateMemberRoleRequest(BaseModel):
    role: str

class PurgeDataRequest(BaseModel):
    password: str
    confirmation_token: str

@router.post("/organizations")
async def create_organization(
    req: CreateOrgRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """0.4 Restrict create_organization to SUPER_ADMIN only."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden. Direct organization creation is restricted to platform super administrators."
        )

    org_id = str(uuid.uuid4())
    org = Organization(id=org_id, name=req.name, slug=req.slug, status="active")
    db.add(org)
    await db.flush()
    return {"id": org.id, "name": org.name, "slug": org.slug}

@router.get("/organizations")
async def list_organizations(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role == UserRole.SUPER_ADMIN:
        stmt = select(Organization)
    else:
        stmt = select(Organization).where(Organization.id == current_user.organization_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    orgs = res.scalars().all()
    return [{"id": o.id, "name": o.name, "slug": o.slug, "status": o.status} for o in orgs]

# --- 0.2 MEMBER MANAGEMENT & INVITATIONS ---

@router.post("/organizations/{organization_id}/invitations")
async def create_invitation(
    organization_id: str,
    req: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """0.2 Create an invitation to join the organization. Requires ADMIN or OWNER role."""
    org_id = verify_tenant_access(current_user, organization_id)
    caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if ROLE_HIERARCHY.get(caller_role_val, 0) < ROLE_HIERARCHY.get(UserRole.ADMIN, 80):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organization Admins or Owners may invite new members."
        )

    # Cannot invite OWNER
    target_role_str = req.role.upper()
    if target_role_str == "OWNER":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot invite another OWNER. Organization ownership is single-principal."
        )

    # Check if user already in org
    stmt_existing = select(User).where(User.email == req.email)
    res_existing = await db.execute(stmt_existing)
    if res_existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email {req.email} is already registered."
        )

    inv_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    inv = Invitation(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        email=req.email,
        role=target_role_str,
        token=inv_token,
        invited_by_user_id=current_user.id,
        expires_at=now + timedelta(days=7),
        created_at=now
    )
    db.add(inv)
    await db.flush()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="MEMBER_INVITED",
        target_type="invitation",
        target_id=inv.id,
        details={"email": req.email, "role": target_role_str},
        db=db
    )

    return {
        "invitation_token": inv_token,
        "email": req.email,
        "role": target_role_str,
        "expires_at": inv.expires_at.isoformat()
    }

@router.get("/organizations/{organization_id}/invitations")
async def list_invitations(
    organization_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists pending invitations for the organization."""
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Invitation).where(
        (Invitation.organization_id == org_id) & (Invitation.accepted_at.is_(None))
    )
    res = await db.execute(stmt)
    invs = res.scalars().all()
    return [{
        "id": i.id,
        "email": i.email,
        "role": i.role,
        "expires_at": i.expires_at.isoformat(),
        "created_at": i.created_at.isoformat()
    } for i in invs]

@router.get("/organizations/{organization_id}/members")
async def list_members(
    organization_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists all members of the organization."""
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(User).where(User.organization_id == org_id)
    res = await db.execute(stmt)
    users = res.scalars().all()
    return [{
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role.value if hasattr(u.role, "value") else str(u.role),
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat()
    } for u in users]

@router.patch("/organizations/{organization_id}/members/{user_id}")
async def update_member_role(
    organization_id: str,
    user_id: str,
    req: UpdateMemberRoleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Updates a member's role. Requires ADMIN or OWNER."""
    org_id = verify_tenant_access(current_user, organization_id)
    caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if ROLE_HIERARCHY.get(caller_role_val, 0) < ROLE_HIERARCHY.get(UserRole.ADMIN, 80):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required to update member roles."
        )

    stmt = select(User).where((User.id == user_id) & (User.organization_id == org_id))
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    target_role_str = req.role.upper()
    if target_role_str == "OWNER" and caller_role_val != "OWNER" and caller_role_val != "SUPER_ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the OWNER can transfer ownership.")

    target_user.role = UserRole(target_role_str) if target_role_str in UserRole.__members__ else target_role_str
    await db.flush()

    return {"id": target_user.id, "role": target_role_str}

@router.delete("/organizations/{organization_id}/members/{user_id}")
async def remove_member(
    organization_id: str,
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Removes a member from the organization. Cannot remove the organization OWNER."""
    org_id = verify_tenant_access(current_user, organization_id)
    caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if ROLE_HIERARCHY.get(caller_role_val, 0) < ROLE_HIERARCHY.get(UserRole.ADMIN, 80):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin permissions required to remove members."
        )

    stmt = select(User).where((User.id == user_id) & (User.organization_id == org_id))
    res = await db.execute(stmt)
    target_user = res.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")

    target_role_val = target_user.role.value if hasattr(target_user.role, "value") else str(target_user.role)
    if target_role_val == "OWNER":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the organization OWNER.")

    await db.delete(target_user)
    await db.flush()
    return {"status": "success", "message": f"Member {user_id} removed."}

# --- PROPERTIES & DATA ---

@router.post("/properties")
async def create_property(
    req: CreatePropertyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Creates a property. Enforces tenant scoping and minimum ADMIN role."""
    org_id = verify_tenant_access(current_user, req.organization_id)
    caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if ROLE_HIERARCHY.get(caller_role_val, 0) < ROLE_HIERARCHY.get(UserRole.ADMIN, 80):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Creating properties requires minimum ADMIN role."
        )

    prop_id = str(uuid.uuid4())
    prop = Property(
        id=prop_id,
        organization_id=org_id,
        name=req.name,
        property_type=req.property_type,
        timezone=req.timezone
    )
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
async def list_properties(
    organization_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Property).where(Property.organization_id == org_id).limit(limit).offset(offset)
    res = await db.execute(stmt)
    props = res.scalars().all()
    return [{"id": p.id, "organization_id": p.organization_id, "name": p.name, "type": p.property_type} for p in props]

@router.get("/organizations/{organization_id}/export-data", tags=["GDPR & Data Compliance"])
async def export_tenant_data(
    organization_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """GDPR Compliance: Export all tenant data."""
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
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": "JSON_ZIP"
        },
        "organization": {"id": org.id, "name": org.name, "slug": org.slug} if org else {},
        "properties": [{"id": p.id, "name": p.name, "type": p.property_type} for p in props],
        "agents": [{"id": a.id, "name": a.name, "status": a.status} for a in agents],
        "documents": [{"id": d.id, "title": d.title, "type": d.document_type} for d in docs],
        "conversations_count": len(convs)
    }

@router.delete("/organizations/{organization_id}/purge-data", tags=["GDPR & Data Compliance"])
async def purge_tenant_data(
    organization_id: str,
    req: PurgeDataRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """0.4 GDPR Compliance: OWNER-only, password re-auth, confirmation token, soft-delete, no explicit commit inside handler."""
    org_id = verify_tenant_access(current_user, organization_id)
    caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)

    # 1. OWNER only (or SUPER_ADMIN)
    if caller_role_val not in ("OWNER", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Purging an organization requires OWNER role privileges."
        )

    # 2. Re-authenticate password
    if not verify_password(req.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password re-authentication failed. Purge aborted."
        )

    # 3. Confirmation token verification
    expected_token = f"CONFIRM_PURGE_{org_id}"
    if req.confirmation_token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid confirmation token. Expected '{expected_token}'."
        )

    # 4. Soft delete organization
    stmt = select(Organization).where(Organization.id == org_id)
    res = await db.execute(stmt)
    org = res.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    org.status = "purged"

    # Also clean up documents/vectors/agents
    await db.execute(delete(Document).where(Document.organization_id == org_id))
    await db.execute(delete(Agent).where(Agent.organization_id == org_id))
    await db.flush()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="TENANT_DATA_PURGED",
        target_type="organization",
        target_id=org_id,
        details={"status": "purged"},
        db=db
    )

    # Note: no db.commit() inside handler per Rule 0.4
    return {
        "status": "success",
        "message": f"Tenant organization {org_id} has been soft-deleted and records purged."
    }
