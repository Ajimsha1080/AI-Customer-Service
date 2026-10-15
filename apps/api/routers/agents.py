import uuid
import json
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db, set_tenant_context
from services.database.models import (
    User, Agent, AgentConfig, UserRole, Conversation, Message,
    SupportTicket, ConversationStatus
)
from apps.api.auth import get_current_user, verify_tenant_access, ROLE_HIERARCHY
from packages.agent_sdk.sdk import HospitalityAgentSDK
from services.agent_runtime.engine import AgentRuntimeEngine
from services.billing.metering import SaaSMeteringService
from services.security.limiter import limiter
from services.realtime.broadcaster import realtime_hub
from services.database.pagination import paginate_query
from services.resilience.tenant_limiter import tenant_limiter

router = APIRouter(prefix="/api/v1/agents", tags=["Control Plane - Agents"])
agent_sdk = HospitalityAgentSDK()
metering_service = SaaSMeteringService()

class CreateAgentRequest(BaseModel):
    organization_id: str
    property_id: str
    name: str
    agent_type: str = "CONCIERGE"
    system_prompt: Optional[str] = None
    tone: Optional[str] = "Friendly, Professional, Courteous"

class UpdateAgentConfigRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    model_name: Optional[str] = None
    system_prompt: Optional[str] = None
    greeting: Optional[str] = None
    enabled_tools: Optional[List[str]] = None

class AgentChatRequest(BaseModel):
    organization_id: str
    property_id: str
    message: str
    conversation_id: Optional[str] = None
    channel: str = "web_widget"
    language: Optional[str] = "English"

VALID_AGENT_TYPES = {"CONCIERGE", "FRONT_DESK", "ROOM_SERVICE", "MAINTENANCE", "HOSTEL_AI_AGENT"}

async def _verify_and_get_agent(agent_id: str, current_user: User, db: AsyncSession, require_mutation: bool = False) -> Agent:
    stmt = select(Agent).where(Agent.id == agent_id)
    res = await db.execute(stmt)
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")
    verify_tenant_access(current_user, agent.organization_id)
    if require_mutation:
        caller_role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
        if ROLE_HIERARCHY.get(caller_role_val, 0) < ROLE_HIERARCHY.get(UserRole.ADMIN, 80):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin permissions required to modify agent lifecycle state."
            )
    return agent

@router.post("")
async def create_agent(req: CreateAgentRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    normalized_type = req.agent_type.upper()
    if normalized_type not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid agent_type '{req.agent_type}'. Valid types: {sorted(list(VALID_AGENT_TYPES))}"
        )
    allowed, reason, details = await metering_service.check_billing_quota(org_id, resource="create_agent", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    agent = agent_sdk.createAgent(
        organization_id=org_id,
        property_id=req.property_id,
        name=req.name,
        agent_type=normalized_type
    )
    stmt = select(Agent).where(Agent.id == agent["id"])
    res = await db.execute(stmt)
    db_agent = res.scalar_one_or_none()
    if not db_agent:
        db_agent = Agent(
            id=agent["id"],
            organization_id=org_id,
            property_id=req.property_id,
            name=req.name,
            agent_type=normalized_type,
            status="ACTIVE",
            description=f"Autonomous {normalized_type} agent."
        )
        db.add(db_agent)

    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent["id"])
    cfg_res = await db.execute(cfg_stmt)
    db_cfg = cfg_res.scalar_one_or_none()
    if not db_cfg:
        db_cfg = AgentConfig(
            id=f"cfg_{agent['id']}",
            agent_id=agent["id"],
            model_name="sarvam-2b",
            system_prompt=req.system_prompt or "You are a helpful AI assistant.",
            greeting="Welcome! How can I assist you today?",
            enabled_tools=["search_property_information", "get_facility_status", "check_room_availability", "create_booking", "get_current_property_updates", "handoff_to_human"]
        )
        db.add(db_cfg)

    await db.flush()

    if req.system_prompt:
        agent_sdk.configureAgent(agent["id"], system_prompt=req.system_prompt, tone=req.tone)
    return agent

@router.put("/{agent_id}")
async def update_agent(agent_id: str, req: UpdateAgentConfigRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    agt = await _verify_and_get_agent(agent_id, current_user, db, require_mutation=True)
    
    if req.name:
        agt.name = req.name
    if req.status:
        agt.status = req.status
    if req.description:
        agt.description = req.description

    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent_id)
    cfg_res = await db.execute(cfg_stmt)
    cfg = cfg_res.scalar_one_or_none()
    if not cfg:
        cfg = AgentConfig(
            id=f"cfg_{agent_id}",
            agent_id=agent_id,
            model_name=req.model_name or "sarvam-2b",
            system_prompt=req.system_prompt or "You are a helpful AI assistant.",
            greeting=req.greeting or "Welcome! How can I assist you today?",
            enabled_tools=req.enabled_tools or ["search_property_information", "get_facility_status", "check_room_availability", "create_booking", "get_current_property_updates", "handoff_to_human"]
        )
        db.add(cfg)
    else:
        if req.model_name:
            cfg.model_name = req.model_name
        if req.system_prompt is not None:
            cfg.system_prompt = req.system_prompt
        if req.greeting is not None:
            cfg.greeting = req.greeting
        if req.enabled_tools is not None:
            cfg.enabled_tools = req.enabled_tools

    await db.flush()
    return {
        "id": agt.id,
        "name": agt.name,
        "status": agt.status,
        "config": {
            "model_name": cfg.model_name,
            "system_prompt": cfg.system_prompt,
            "greeting": cfg.greeting,
            "enabled_tools": cfg.enabled_tools
        },
        "message": "Agent configuration updated and saved."
    }

@router.get("")
async def list_agents(
    response: Response,
    organization_id: Optional[str] = None,
    property_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Agent).where(Agent.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Agent.property_id == property_id)
    agents = await paginate_query(
        db=db,
        stmt=stmt,
        model=Agent,
        limit=limit,
        cursor=cursor,
        response=response
    )
    return [
        { "id": a.id, "organization_id": a.organization_id, "property_id": a.property_id, "name": a.name, "agent_type": a.agent_type, "status": a.status or "ACTIVE", "description": a.description }
        for a in agents
    ]

@router.get("/{agent_id}")
async def get_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    agent = await _verify_and_get_agent(agent_id, current_user, db, require_mutation=False)
    
    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent_id)
    cfg_res = await db.execute(cfg_stmt)
    config = cfg_res.scalar_one_or_none()

    return {
        "id": agent.id,
        "organization_id": agent.organization_id,
        "property_id": agent.property_id,
        "name": agent.name,
        "agent_type": agent.agent_type,
        "status": agent.status,
        "config": {
            "model_name": config.model_name if config else "sarvam-2b",
            "system_prompt": config.system_prompt if config else "You are a hospitality AI concierge.",
            "greeting": config.greeting if config else "Welcome! How can I assist you today?",
            "enabled_tools": config.enabled_tools if (config and config.enabled_tools) else [
                "search_property_information", "get_facility_status", "check_room_availability", "create_booking", "get_current_property_updates", "handoff_to_human"
            ]
        }
    }

@router.post("/{agent_id}/validate")
async def validate_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_and_get_agent(agent_id, current_user, db, require_mutation=False)
    valid, msg = await agent_sdk.validateAgent(agent_id)
    return {"agent_id": agent_id, "is_valid": valid, "message": msg}

@router.post("/{agent_id}/deploy")
async def deploy_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_and_get_agent(agent_id, current_user, db, require_mutation=True)
    return await agent_sdk.deployAgent(agent_id)

@router.post("/{agent_id}/pause")
async def pause_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_and_get_agent(agent_id, current_user, db, require_mutation=True)
    return await agent_sdk.pauseAgent(agent_id)

@router.post("/{agent_id}/resume")
async def resume_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_and_get_agent(agent_id, current_user, db, require_mutation=True)
    return await agent_sdk.resumeAgent(agent_id)

@router.post("/{agent_id}/disable")
async def disable_agent(agent_id: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _verify_and_get_agent(agent_id, current_user, db, require_mutation=True)
    return await agent_sdk.disableAgent(agent_id)

@router.post("/{agent_id}/chat", tags=["Data Plane - Agent Execution"])
@limiter.limit("30/minute")
async def agent_chat(request: Request, agent_id: str, req: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    # Strict agent lookup & organization validation
    agent_stmt = select(Agent).where(Agent.id == agent_id)
    agent_res = await db.execute(agent_stmt)
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found."
        )

    if req.organization_id and req.organization_id != agent.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mismatched organization_id. Agent '{agent_id}' belongs to tenant '{agent.organization_id}'."
        )
    effective_org_id = agent.organization_id
    await set_tenant_context(db, effective_org_id)

    # Per-tenant fair-use token bucket rate limiter
    rate_ok, rem_tokens, retry_sec = await tenant_limiter.consume(org_id=effective_org_id, cost=1)
    if not rate_ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"FAIR_USE_QUOTA_EXCEEDED: Tenant '{effective_org_id}' rate limit reached. Please back off.",
            headers={
                "Retry-After": str(int(retry_sec)),
                "X-RateLimit-Limit": str(tenant_limiter.default_burst_capacity),
                "X-RateLimit-Remaining": "0"
            }
        )

    allowed, reason, details = await metering_service.check_billing_quota(effective_org_id, resource="agent_turn", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    # 1. Resolve or provision Conversation
    conv_id = req.conversation_id or str(uuid.uuid4())
    conv_stmt = select(Conversation).where(Conversation.id == conv_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        conv = Conversation(
            id=conv_id,
            organization_id=effective_org_id,
            property_id=req.property_id,
            agent_id=agent_id,
            channel=req.channel,
            customer_name="Guest",
            status=ConversationStatus.AI_ACTIVE,
            is_human_takeover=False
        )
        db.add(conv)
        await db.flush()

    # 2. Persist guest message turn
    guest_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="guest",
        content=req.message
    )
    db.add(guest_msg)
    await db.flush()

    # 3. Check for active human takeover: AI ceases responding, relays message to staff inbox
    if conv.is_human_takeover or conv.status == ConversationStatus.HUMAN_STAFF_TAKEN_OVER:
        await realtime_hub.publish(
            event_type="GUEST_MESSAGE_RECEIVED",
            data={
                "conversation_id": conv.id,
                "message_id": guest_msg.id,
                "sender_type": "guest",
                "content": req.message
            },
            organization_id=effective_org_id,
            property_id=req.property_id
        )
        await db.commit()
        return {
            "conversation_id": conv.id,
            "response": "A front desk staff member has taken over this conversation and will respond shortly.",
            "status": "HUMAN_STAFF_TAKEN_OVER",
            "is_human_takeover": True
        }

    # 4. Load recent history for agent context continuity (last 10 messages)
    hist_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.asc())
    hist_res = await db.execute(hist_stmt)
    messages = hist_res.scalars().all()
    conversation_history = [
        {"role": "user" if m.sender_type == "guest" else "assistant", "content": m.content}
        for m in messages[:-1]
    ]

    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent_id)
    cfg_res = await db.execute(cfg_stmt)
    config = cfg_res.scalar_one_or_none()

    agent_config = {
        "model_name": config.model_name if config else "sarvam-2b",
        "system_prompt": config.system_prompt if config else f"You are the AI Concierge for {agent.name}. Assist guests with amenities, services, dining, and requests.",
        "enabled_tools": config.enabled_tools if (config and config.enabled_tools) else [
            "search_property_information", "get_facility_status", "check_room_availability",
            "create_booking", "get_current_property_updates", "get_today_activities",
            "get_restaurant_status", "handoff_to_human"
        ]
    }

    engine_with_db = AgentRuntimeEngine(db_session=db)

    result = await engine_with_db.execute_agent_turn(
        agent_config=agent_config,
        user_message=req.message,
        conversation_history=conversation_history,
        organization_id=effective_org_id,
        property_id=req.property_id,
        agent_id=agent_id,
        channel=req.channel,
        language=req.language,
        conversation_id=conv.id
    )

    # 5. Check if staff handoff was requested
    tools_executed = result.get("tools_executed") or [
        tc.get("tool") or tc.get("name") for tc in result.get("tool_calls", []) if isinstance(tc, dict)
    ]
    tools_called = result.get("debug_trace", {}).get("tools_called", [])
    if (
        "handoff_to_human" in tools_executed
        or "handoff_to_human" in tools_called
        or result.get("handoff_requested")
        or result.get("status") in ["HUMAN_REQUESTED", "HUMAN_STAFF_TAKEN_OVER"]
    ):
        conv.is_human_takeover = True
        conv.status = ConversationStatus.HUMAN_STAFF_TAKEN_OVER
        result["status"] = "HUMAN_STAFF_TAKEN_OVER"
        result["is_human_takeover"] = True
        ticket = SupportTicket(
            id=str(uuid.uuid4()),
            conversation_id=conv.id,
            property_id=req.property_id,
            issue_summary=f"Guest requested staff assistance: {req.message[:200]}",
            status="OPEN",
            priority="HIGH"
        )
        db.add(ticket)
        await realtime_hub.publish(
            event_type="STAFF_TAKEOVER_REQUESTED",
            data={
                "conversation_id": conv.id,
                "ticket_id": ticket.id,
                "summary": ticket.issue_summary
            },
            organization_id=effective_org_id,
            property_id=req.property_id
        )

    # 6. Persist AI response message
    ai_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="agent",
        content=result.get("response", ""),
        tool_calls_json={"tools_executed": tools_executed}
    )
    db.add(ai_msg)
    await db.flush()

    # 7. Record metering usage event
    await metering_service.record_usage_event_async(
        organization_id=effective_org_id,
        property_id=req.property_id,
        agent_id=agent_id,
        event_type="agent_turn",
        provider="litellm",
        quantity=1,
        unit="turns",
        db=db
    )

    # 8. Publish realtime turn event
    await realtime_hub.publish(
        event_type="CHAT_TURN_COMPLETED",
        data={
            "conversation_id": conv.id,
            "agent_id": agent_id,
            "response": ai_msg.content
        },
        organization_id=effective_org_id,
        property_id=req.property_id
    )

    result["conversation_id"] = conv.id
    await db.commit()
    return result

@router.post("/{agent_id}/chat/stream", tags=["Data Plane - Agent Execution"])
@limiter.limit("30/minute")
async def agent_chat_stream(request: Request, agent_id: str, req: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    """Server-Sent Events streaming guest chat endpoint with persistence and token streaming."""
    agent_stmt = select(Agent).where(Agent.id == agent_id)
    agent_res = await db.execute(agent_stmt)
    agent = agent_res.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent '{agent_id}' not found.")

    if req.organization_id and req.organization_id != agent.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Mismatched organization_id. Agent '{agent_id}' belongs to tenant '{agent.organization_id}'."
        )
    effective_org_id = agent.organization_id
    await set_tenant_context(db, effective_org_id)

    # Per-tenant fair-use token bucket rate limiter
    rate_ok, rem_tokens, retry_sec = await tenant_limiter.consume(org_id=effective_org_id, cost=1)
    if not rate_ok:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"FAIR_USE_QUOTA_EXCEEDED: Tenant '{effective_org_id}' rate limit reached. Please back off.",
            headers={
                "Retry-After": str(int(retry_sec)),
                "X-RateLimit-Limit": str(tenant_limiter.default_burst_capacity),
                "X-RateLimit-Remaining": "0"
            }
        )

    allowed, reason, _ = await metering_service.check_billing_quota(effective_org_id, resource="agent_turn", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    conv_id = req.conversation_id or str(uuid.uuid4())
    conv_stmt = select(Conversation).where(Conversation.id == conv_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        conv = Conversation(
            id=conv_id,
            organization_id=effective_org_id,
            property_id=req.property_id,
            agent_id=agent_id,
            channel=req.channel,
            customer_name="Guest",
            status=ConversationStatus.AI_ACTIVE,
            is_human_takeover=False
        )
        db.add(conv)
        await db.flush()

    guest_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="guest",
        content=req.message
    )
    db.add(guest_msg)
    await db.flush()

    if conv.is_human_takeover or conv.status == ConversationStatus.HUMAN_STAFF_TAKEN_OVER:
        await realtime_hub.publish(
            event_type="GUEST_MESSAGE_RECEIVED",
            data={
                "conversation_id": conv.id,
                "message_id": guest_msg.id,
                "sender_type": "guest",
                "content": req.message
            },
            organization_id=effective_org_id,
            property_id=req.property_id
        )
        await db.commit()

        async def takeover_stream():
            takeover_text = "A front desk staff member has taken over this conversation and will respond shortly."
            yield f"data: {json.dumps({'token': takeover_text, 'done': False})}\n\n"
            yield f"data: {json.dumps({'response': takeover_text, 'done': True, 'conversation_id': conv.id, 'status': 'HUMAN_STAFF_TAKEN_OVER'})}\n\n"

        return StreamingResponse(takeover_stream(), media_type="text/event-stream")

    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent_id)
    cfg_res = await db.execute(cfg_stmt)
    config = cfg_res.scalar_one_or_none()

    agent_config = {
        "model_name": config.model_name if config else "sarvam-2b",
        "system_prompt": config.system_prompt if config else f"You are the AI Concierge for {agent.name}.",
        "enabled_tools": config.enabled_tools if (config and config.enabled_tools) else []
    }

    engine_with_db = AgentRuntimeEngine(db_session=db)
    result = await engine_with_db.execute_agent_turn(
        agent_config=agent_config,
        user_message=req.message,
        conversation_history=[],
        organization_id=effective_org_id,
        property_id=req.property_id,
        agent_id=agent_id,
        channel=req.channel,
        language=req.language
    )

    full_response = result.get("response", "")
    ai_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="agent",
        content=full_response
    )
    db.add(ai_msg)
    await db.commit()

    async def token_generator():
        words = full_response.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield f"data: {json.dumps({'token': chunk, 'done': False})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'response': full_response, 'done': True, 'conversation_id': conv.id})}\n\n"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

