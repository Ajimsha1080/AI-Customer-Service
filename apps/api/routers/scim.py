import hashlib
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Header, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db, set_tenant_context
from services.database.models import User, Organization, UserRole, SCIMToken, UserSession
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    get_current_user, require_permission,
    revoke_all_user_sessions, _hash_token
)

router = APIRouter(prefix="/api/v1/scim/v2", tags=["SCIM 2.0"])

class CreateSCIMTokenRequest(BaseModel):
    name: str = "Okta/Azure SCIM Integration"

async def get_scim_org(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> Organization:
    """Authenticates SCIM 2.0 Bearer token and returns associated tenant organization."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SCIM Bearer token required."
        )
    token_str = authorization[len("Bearer "):].strip()
    token_h = hashlib.sha256(token_str.encode("utf-8")).hexdigest()

    stmt = select(SCIMToken).where(SCIMToken.token_hash == token_h)
    res = await db.execute(stmt)
    scim_token = res.scalar_one_or_none()

    if not scim_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired SCIM token."
        )

    stmt_org = select(Organization).where(Organization.id == scim_token.organization_id)
    res_org = await db.execute(stmt_org)
    org = res_org.scalar_one_or_none()

    if not org:
        raise HTTPException(status_code=404, detail="Organization associated with SCIM token not found.")

    await set_tenant_context(db, org.id)
    return org

@router.post("/tokens")
async def create_scim_token(
    req: CreateSCIMTokenRequest,
    current_user: User = Depends(require_permission("scim:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Generates a new SCIM 2.0 Directory Bearer Token for identity providers (Okta, Azure AD)."""
    raw_token = f"scim_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    token_rec = SCIMToken(
        organization_id=current_user.organization_id,
        name=req.name,
        token_hash=token_hash
    )
    db.add(token_rec)
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="SCIM_TOKEN_CREATED",
        target_type="scim_token",
        target_id=token_rec.id,
        details={"name": req.name},
        db=db
    )

    return {
        "id": token_rec.id,
        "name": token_rec.name,
        "token": raw_token,
        "message": "Token generated. Copy this secret now as it cannot be shown again."
    }

def format_scim_user(user: User) -> dict:
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": user.id,
        "userName": user.email,
        "name": {
            "formatted": user.full_name,
            "familyName": user.full_name.split()[-1] if " " in user.full_name else "",
            "givenName": user.full_name.split()[0] if " " in user.full_name else user.full_name
        },
        "emails": [
            {"value": user.email, "primary": True, "type": "work"}
        ],
        "active": user.is_active,
        "roles": [{"value": user.role.value if hasattr(user.role, "value") else str(user.role)}],
        "meta": {
            "resourceType": "User",
            "created": user.created_at.isoformat() if hasattr(user, "created_at") and user.created_at else None
        }
    }

@router.get("/Users")
async def list_scim_users(
    startIndex: int = 1,
    count: int = 100,
    org: Organization = Depends(get_scim_org),
    db: AsyncSession = Depends(get_db)
):
    """SCIM 2.0 List Users Endpoint."""
    stmt = select(User).where(User.organization_id == org.id).offset(startIndex - 1).limit(count)
    res = await db.execute(stmt)
    users = res.scalars().all()

    total_stmt = select(User).where(User.organization_id == org.id)
    total_res = await db.execute(total_stmt)
    total_count = len(total_res.scalars().all())

    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total_count,
        "startIndex": startIndex,
        "itemsPerPage": len(users),
        "Resources": [format_scim_user(u) for u in users]
    }

@router.get("/Users/{user_id}")
async def get_scim_user(
    user_id: str,
    org: Organization = Depends(get_scim_org),
    db: AsyncSession = Depends(get_db)
):
    """SCIM 2.0 Get Single User Endpoint."""
    stmt = select(User).where(User.id == user_id, User.organization_id == org.id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SCIM User not found.")

    return format_scim_user(user)

@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_scim_user(
    payload: Dict[str, Any],
    org: Organization = Depends(get_scim_org),
    db: AsyncSession = Depends(get_db)
):
    """SCIM 2.0 User Provisioning Endpoint."""
    email = payload.get("userName") or (payload.get("emails", [{}])[0].get("value"))
    if not email:
        raise HTTPException(status_code=400, detail="userName or emails is required.")

    name_obj = payload.get("name", {})
    full_name = name_obj.get("formatted") or f"{name_obj.get('givenName', '')} {name_obj.get('familyName', '')}".strip() or email.split("@")[0]

    stmt = select(User).where(User.email == email)
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists.")

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        organization_id=org.id,
        email=email,
        full_name=full_name,
        role=UserRole.STAFF,
        is_active=payload.get("active", True),
        email_verified=True,
        hashed_password=""
    )
    db.add(user)
    await db.flush()

    await record_audit_log_async(
        org_id=org.id,
        user_id="SCIM_PROVISIONING",
        action="SCIM_USER_PROVISIONED",
        target_type="user",
        target_id=user.id,
        details={"email": email, "active": user.is_active},
        db=db
    )

    return format_scim_user(user)

@router.put("/Users/{user_id}")
@router.patch("/Users/{user_id}")
async def update_scim_user(
    user_id: str,
    payload: Dict[str, Any],
    org: Organization = Depends(get_scim_org),
    db: AsyncSession = Depends(get_db)
):
    """SCIM 2.0 User Update / Deprovisioning Endpoint."""
    stmt = select(User).where(User.id == user_id, User.organization_id == org.id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SCIM User not found.")

    # Handle active status change or PATCH operation
    target_active = None
    if "active" in payload:
        target_active = bool(payload["active"])
    elif "Operations" in payload:
        for op in payload.get("Operations", []):
            if op.get("path") == "active" or op.get("op", "").lower() == "replace":
                val = op.get("value")
                if isinstance(val, dict) and "active" in val:
                    target_active = bool(val["active"])
                elif isinstance(val, bool):
                    target_active = val

    if target_active is not None and target_active != user.is_active:
        user.is_active = target_active
        if not target_active:
            # Immediate deprovisioning: revoke all active sessions
            await revoke_all_user_sessions(db=db, user_id=user.id)
            await record_audit_log_async(
                org_id=org.id,
                user_id="SCIM_DEPROVISIONING",
                action="SCIM_USER_DEPROVISIONED",
                target_type="user",
                target_id=user.id,
                details={"sessions_revoked": True},
                db=db
            )

    if "name" in payload and isinstance(payload["name"], dict):
        new_name = payload["name"].get("formatted")
        if new_name:
            user.full_name = new_name

    await db.flush()
    return format_scim_user(user)

@router.delete("/Users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deprovision_scim_user(
    user_id: str,
    org: Organization = Depends(get_scim_org),
    db: AsyncSession = Depends(get_db)
):
    """SCIM 2.0 Immediate Deprovisioning Endpoint."""
    stmt = select(User).where(User.id == user_id, User.organization_id == org.id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SCIM User not found.")

    user.is_active = False
    await revoke_all_user_sessions(db=db, user_id=user.id)
    await db.flush()

    await record_audit_log_async(
        org_id=org.id,
        user_id="SCIM_DEPROVISIONING",
        action="SCIM_USER_DELETED",
        target_type="user",
        target_id=user.id,
        details={"status": "deactivated_sessions_revoked"},
        db=db
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/Groups")
async def list_scim_groups(
    org: Organization = Depends(get_scim_org)
):
    """SCIM 2.0 Groups listing mapped to tenant roles."""
    groups = [
        {"id": "OWNER", "displayName": "Owners"},
        {"id": "ADMIN", "displayName": "Administrators"},
        {"id": "STAFF", "displayName": "Hospitality Staff"},
        {"id": "ANALYST", "displayName": "Analysts"},
        {"id": "VIEWER", "displayName": "Viewers"}
    ]
    return {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": len(groups),
        "startIndex": 1,
        "itemsPerPage": len(groups),
        "Resources": groups
    }
