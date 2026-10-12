from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Agent, AgentConfig, UserRole
from apps.api.auth import get_current_user, verify_tenant_access, ROLE_HIERARCHY
from packages.agent_sdk.sdk import HospitalityAgentSDK
from services.agent_runtime.engine import AgentRuntimeEngine
from services.billing.metering import SaaSMeteringService
from services.security.limiter import limiter

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
async def list_agents(organization_id: Optional[str] = None, property_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Agent).where(Agent.organization_id == org_id)
    if property_id:
        stmt = stmt.where(Agent.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    agents = res.scalars().all()
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

    allowed, reason, details = await metering_service.check_billing_quota(effective_org_id, resource="agent_turn", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent_id)
    cfg_res = await db.execute(cfg_stmt)
    config = cfg_res.scalar_one_or_none()

    agent_config = {
        "model_name": config.model_name if config else "sarvam-2b",
        "system_prompt": config.system_prompt if config else "You are the head AI Concierge for Azure Palm Resort. Assist guests with amenities, pool hours, dining, and bookings.",
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
        organization_id=effective_org_id,
        property_id=req.property_id,
        conversation_id=req.conversation_id,
        channel=req.channel,
        user_language=req.language
    )

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

    return result

