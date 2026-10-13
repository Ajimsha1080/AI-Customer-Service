from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, UserSession
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    get_current_user, security_scheme, _hash_token,
    revoke_user_session, revoke_all_user_sessions
)

router = APIRouter(prefix="/api/v1/auth/sessions", tags=["Sessions"])

class SessionResponse(BaseModel):
    id: str
    device_name: str
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    is_current: bool

@router.get("", response_model=List[SessionResponse])
async def list_active_sessions(
    current_user: User = Depends(get_current_user),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
):
    """Lists all active logged-in devices and sessions for the current user."""
    stmt = (
        select(UserSession)
        .where(
            UserSession.user_id == current_user.id,
            UserSession.is_revoked == False
        )
        .order_by(UserSession.last_activity_at.desc())
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    current_token_hash = _hash_token(credentials.credentials) if credentials and credentials.credentials else ""

    result = []
    for s in sessions:
        result.append(
            SessionResponse(
                id=s.id,
                device_name=s.device_name,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                created_at=s.created_at,
                last_activity_at=s.last_activity_at,
                expires_at=s.expires_at,
                is_current=(s.session_token_hash == current_token_hash)
            )
        )
    return result

@router.delete("/{session_id}")
async def terminate_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remotely terminates a specific active session."""
    revoked = await revoke_user_session(db=db, session_id=session_id, user_id=current_user.id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or already terminated."
        )

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="SESSION_REVOKED",
        target_type="user_session",
        target_id=session_id,
        details={"terminated_by": current_user.id},
        db=db
    )

    return {"message": "Session terminated successfully."}

@router.delete("")
async def terminate_other_sessions(
    current_user: User = Depends(get_current_user),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
):
    """Remotely terminates all active sessions except the current caller session."""
    current_token_hash = _hash_token(credentials.credentials) if credentials and credentials.credentials else None
    count = await revoke_all_user_sessions(
        db=db,
        user_id=current_user.id,
        except_token_hash=current_token_hash
    )

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="ALL_SESSIONS_REVOKED",
        target_type="user",
        target_id=current_user.id,
        details={"revoked_count": count},
        db=db
    )

    return {"message": f"Successfully terminated {count} other active session(s)."}
