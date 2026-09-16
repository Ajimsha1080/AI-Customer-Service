from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Conversation
from apps.api.auth import get_current_user, verify_tenant_access

router = APIRouter(prefix="/api/v1/conversations", tags=["Staff Inbox & Conversations"])

class HumanTakeoverRequest(BaseModel):
    staff_user_id: str
    reason: Optional[str] = "Manual Staff Takeover Initiated"

@router.get("")
async def list_conversations(organization_id: Optional[str] = None, property_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Conversation).where(Conversation.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Conversation.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    convs = res.scalars().all()
    return [
        { "id": c.id, "guest": c.channel_user_id or "Guest", "agent_id": c.agent_id, "status": c.status, "time": str(c.created_at) }
        for c in convs
    ]

@router.post("/{conversation_id}/takeover")
async def takeover_conversation(conversation_id: str, req: HumanTakeoverRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if conv:
        verify_tenant_access(current_user, conv.organization_id)
        conv.status = "HUMAN_STAFF_TAKEN_OVER"
        conv.is_human_takeover = True
        await db.flush()
        return {
            "conversation_id": conversation_id,
            "status": "HUMAN_STAFF_TAKEN_OVER",
            "staff_user_id": req.staff_user_id,
            "message": "Human staff takeover initiated and saved to database."
        }
    raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")
