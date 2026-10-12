import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Conversation, Message, ConversationStatus, UserRole
from apps.api.auth import get_current_user, verify_tenant_access

router = APIRouter(prefix="/api/v1/conversations", tags=["Staff Inbox & Conversations"])

class HumanTakeoverRequest(BaseModel):
    reason: Optional[str] = "Manual Staff Takeover Initiated"

class StaffReplyRequest(BaseModel):
    content: str

@router.get("")
async def list_conversations(
    organization_id: Optional[str] = None,
    property_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Conversation).where(Conversation.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Conversation.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    convs = res.scalars().all()
    return [
        {
            "id": c.id,
            "guest": c.channel_user_id or c.customer_name or "Guest",
            "agent_id": c.agent_id,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "is_human_takeover": c.is_human_takeover,
            "time": c.created_at.isoformat() if c.created_at else None
        }
        for c in convs
    ]

from services.realtime.broadcaster import realtime_hub

@router.post("/{conversation_id}/takeover")
async def takeover_conversation(
    conversation_id: str,
    req: HumanTakeoverRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """0.4 Conversation Takeover: Staff ID derived from authenticated principal, 404 for foreign conversations."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    # Strictly 404 if not found OR belongs to another tenant (zero information leakage)
    if not conv or (current_user.role != UserRole.SUPER_ADMIN and conv.organization_id != current_user.organization_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found."
        )

    conv.status = ConversationStatus.HUMAN_STAFF_TAKEN_OVER
    conv.is_human_takeover = True
    await db.flush()

    await realtime_hub.publish(
        event_type="HUMAN_TAKEOVER",
        data={
            "conversation_id": conversation_id,
            "staff_user_id": current_user.id,
            "status": "HUMAN_STAFF_TAKEN_OVER"
        },
        organization_id=conv.organization_id,
        property_id=conv.property_id
    )

    return {
        "conversation_id": conversation_id,
        "status": "HUMAN_STAFF_TAKEN_OVER",
        "staff_user_id": current_user.id,
        "message": "Human staff takeover initiated and saved to database."
    }

@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieves full turn history for a conversation."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    if not conv or (current_user.role != UserRole.SUPER_ADMIN and conv.organization_id != current_user.organization_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found."
        )

    stmt_msgs = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    res_msgs = await db.execute(stmt_msgs)
    msgs = res_msgs.scalars().all()

    return [{
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_type": m.sender_type,
        "content": m.content,
        "created_at": m.created_at.isoformat() if m.created_at else None
    } for m in msgs]

@router.post("/{conversation_id}/messages")
async def send_staff_message(
    conversation_id: str,
    req: StaffReplyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Staff inbox reply endpoint: persists message from staff into conversation history and relays via pubsub."""
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()

    if not conv or (current_user.role != UserRole.SUPER_ADMIN and conv.organization_id != current_user.organization_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found."
        )

    msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        sender_type="STAFF",
        content=req.content,
        metadata_json={"staff_user_id": current_user.id, "staff_name": current_user.full_name}
    )
    db.add(msg)
    await db.flush()

    await realtime_hub.publish(
        event_type="STAFF_REPLY",
        data={
            "conversation_id": conversation_id,
            "message_id": msg.id,
            "sender_type": "STAFF",
            "content": msg.content
        },
        organization_id=conv.organization_id,
        property_id=conv.property_id
    )

    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "sender_type": msg.sender_type,
        "content": msg.content,
        "created_at": msg.created_at.isoformat() if msg.created_at else None
    }
