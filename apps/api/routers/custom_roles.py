import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, CustomRole
from services.database.audit import record_audit_log_async
from apps.api.auth import get_current_user, require_permission

router = APIRouter(prefix="/api/v1/roles", tags=["Custom Roles"])

class CreateCustomRoleRequest(BaseModel):
    name: str
    description: Optional[str] = None
    permissions: List[str]

class UpdateCustomRoleRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[List[str]] = None

@router.get("")
async def list_custom_roles(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Lists all custom defined roles for the organization."""
    stmt = select(CustomRole).where(CustomRole.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    roles = res.scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "permissions": r.permissions,
            "created_at": r.created_at
        }
        for r in roles
    ]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    req: CreateCustomRoleRequest,
    current_user: User = Depends(require_permission("roles:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Creates a new granular custom role within the organization."""
    role_id = str(uuid.uuid4())
    custom_role = CustomRole(
        id=role_id,
        organization_id=current_user.organization_id,
        name=req.name,
        description=req.description,
        permissions=req.permissions
    )
    db.add(custom_role)
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="CUSTOM_ROLE_CREATED",
        target_type="custom_role",
        target_id=custom_role.id,
        details={"name": req.name, "permissions": req.permissions},
        db=db
    )

    return {
        "id": custom_role.id,
        "name": custom_role.name,
        "description": custom_role.description,
        "permissions": custom_role.permissions
    }

@router.put("/{role_id}")
async def update_custom_role(
    role_id: str,
    req: UpdateCustomRoleRequest,
    current_user: User = Depends(require_permission("roles:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Updates an existing custom role's permissions or description."""
    stmt = select(CustomRole).where(CustomRole.id == role_id, CustomRole.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    custom_role = res.scalar_one_or_none()

    if not custom_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom role not found.")

    if req.name is not None:
        custom_role.name = req.name
    if req.description is not None:
        custom_role.description = req.description
    if req.permissions is not None:
        custom_role.permissions = req.permissions

    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="CUSTOM_ROLE_UPDATED",
        target_type="custom_role",
        target_id=custom_role.id,
        details={"permissions": custom_role.permissions},
        db=db
    )

    return {
        "id": custom_role.id,
        "name": custom_role.name,
        "description": custom_role.description,
        "permissions": custom_role.permissions
    }

@router.delete("/{role_id}")
async def delete_custom_role(
    role_id: str,
    current_user: User = Depends(require_permission("roles:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Deletes a custom role."""
    stmt = select(CustomRole).where(CustomRole.id == role_id, CustomRole.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    custom_role = res.scalar_one_or_none()

    if not custom_role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Custom role not found.")

    await db.delete(custom_role)
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="CUSTOM_ROLE_DELETED",
        target_type="custom_role",
        target_id=role_id,
        details={"name": custom_role.name},
        db=db
    )

    return {"message": "Custom role successfully deleted."}
