import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.session import AsyncSessionLocal
from services.database.models import UsageEvent, Subscription, Agent, Document

class UsageMeteringService:
    PLAN_LIMITS = {
        "FREE": {"max_agents": 1, "max_properties": 1, "max_conversations": 100, "max_documents": 5, "monthly_price": 0.0, "voice_enabled": False},
        "STARTER": {"max_agents": 2, "max_properties": 1, "max_conversations": 1000, "max_documents": 10, "monthly_price": 49.0, "voice_enabled": False},
        "PROFESSIONAL": {"max_agents": 5, "max_properties": 2, "max_conversations": 10000, "max_documents": 50, "monthly_price": 199.0, "voice_enabled": True},
        "BUSINESS": {"max_agents": 15, "max_properties": 5, "max_conversations": 50000, "max_documents": 200, "monthly_price": 499.0, "voice_enabled": True},
        "ENTERPRISE": {"max_agents": 999, "max_properties": 999, "max_conversations": 9999999, "max_documents": 5000, "monthly_price": 1999.0, "voice_enabled": True}
    }

    MODEL_PRICING = {
        "gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015},
        "gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
        "claude-3-5-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
        "gemini-1.5-flash": {"input_per_1k": 0.0001, "output_per_1k": 0.0004}
    }

    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db_session = db_session
        self._events_log = []

    async def record_usage_event_async(
        self,
        organization_id: str,
        property_id: str,
        agent_id: str,
        event_type: str,
        provider: str = "openai",
        quantity: int = 1,
        unit: str = "tokens",
        conversation_id: Optional[str] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Logs billable usage event and persists it directly into the database UsageEvent table."""
        unit_cost = 0.000002 if unit == "tokens" else (0.02 if unit == "minutes" else 0.001)
        estimated_cost = round(quantity * unit_cost, 6)
        evt_id = f"evt_{uuid.uuid4().hex[:10]}"

        event_dict = {
            "id": evt_id,
            "organization_id": organization_id,
            "property_id": property_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "event_type": event_type,
            "provider": provider,
            "quantity": quantity,
            "unit": unit,
            "estimated_cost": estimated_cost,
            "created_at": str(datetime.now(timezone.utc))
        }
        self._events_log.append(event_dict)

        session = db or self.db_session
        is_local = False
        if not session:
            try:
                session = AsyncSessionLocal()
                is_local = True
            except Exception:
                session = None

        if session:
            try:
                evt_obj = UsageEvent(
                    id=evt_id,
                    organization_id=organization_id,
                    property_id=property_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    event_type=event_type,
                    provider=provider,
                    quantity=quantity,
                    unit=unit,
                    estimated_cost=estimated_cost
                )
                session.add(evt_obj)
                if is_local:
                    await session.commit()
                    await session.close()
            except Exception as e:
                print(f"[Metering] Warning: Could not persist UsageEvent to DB ({e})")
                if is_local:
                    await session.rollback()
                    await session.close()

        return event_dict

    def record_usage_event(
        self,
        organization_id: str,
        property_id: str,
        agent_id: str,
        event_type: str,
        provider: str = "openai",
        quantity: int = 1,
        unit: str = "tokens",
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Synchronous legacy method signature maintaining backward compatibility."""
        unit_cost = 0.000002 if unit == "tokens" else (0.02 if unit == "minutes" else 0.001)
        estimated_cost = round(quantity * unit_cost, 6)
        evt_id = f"evt_{uuid.uuid4().hex[:10]}"

        event_dict = {
            "id": evt_id,
            "organization_id": organization_id,
            "property_id": property_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "event_type": event_type,
            "provider": provider,
            "quantity": quantity,
            "unit": unit,
            "estimated_cost": estimated_cost,
            "created_at": str(datetime.now(timezone.utc))
        }
        self._events_log.append(event_dict)
        return event_dict

    def check_entitlement(self, plan_name: str, current_agents_count: int, resource_type: str = "agent_creation") -> Tuple[bool, str]:
        """Enforces SaaS plan limits and entitlement boundaries."""
        plan = self.PLAN_LIMITS.get(plan_name.upper(), self.PLAN_LIMITS["STARTER"])
        if resource_type == "agent_creation":
            if current_agents_count >= plan["max_agents"]:
                return False, f"Plan limit reached: '{plan_name}' allows maximum {plan['max_agents']} agents. Please upgrade to Business or Enterprise."
        return True, "Entitlement check passed."

    async def get_organization_usage_summary_async(self, organization_id: str, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """Queries persisted UsageEvents from database for an organization."""
        session = db or self.db_session
        is_local = False
        if not session:
            try:
                session = AsyncSessionLocal()
                is_local = True
            except Exception:
                session = None

        if session:
            try:
                stmt = select(UsageEvent).where(UsageEvent.organization_id == organization_id)
                res = await session.execute(stmt)
                db_events = res.scalars().all()
                if is_local:
                    await session.close()

                if db_events:
                    total_tokens = sum(e.quantity for e in db_events if e.unit == "tokens")
                    total_voice_mins = sum(e.quantity for e in db_events if e.unit == "minutes")
                    total_cost = sum(e.estimated_cost or 0.0 for e in db_events)
                    return {
                        "organization_id": organization_id,
                        "total_events_logged": len(db_events),
                        "total_tokens_consumed": total_tokens,
                        "total_voice_minutes": total_voice_mins,
                        "estimated_total_cost_usd": round(total_cost, 4),
                        "period": datetime.now(timezone.utc).strftime("%B %Y")
                    }
            except Exception as e:
                print(f"[Metering] Warning DB summary query failed: {e}")
                if is_local:
                    await session.close()

        return self.get_organization_usage_summary(organization_id)

    def get_organization_usage_summary(self, organization_id: str) -> Dict[str, Any]:
        org_events = [e for e in self._events_log if e["organization_id"] == organization_id]
        total_tokens = sum(e["quantity"] for e in org_events if e.get("unit") == "tokens")
        total_voice_mins = sum(e["quantity"] for e in org_events if e.get("unit") == "minutes")
        total_cost = sum(e.get("estimated_cost", 0.0) for e in org_events)

        return {
            "organization_id": organization_id,
            "total_events_logged": len(org_events),
            "total_tokens_consumed": total_tokens,
            "total_voice_minutes": total_voice_mins,
            "estimated_total_cost_usd": round(total_cost, 4),
            "period": datetime.now(timezone.utc).strftime("%B %Y")
        }

    async def get_or_create_subscription_async(self, organization_id: str, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """Retrieves or initializes an organization's active subscription tier and limits."""
        session = db or self.db_session
        is_local = False
        if not session:
            try:
                session = AsyncSessionLocal()
                is_local = True
            except Exception:
                session = None

        plan_name = "BUSINESS" if organization_id == "org_azure_group" else "STARTER"
        default_limits = self.PLAN_LIMITS[plan_name]

        sub_dict = {
            "id": f"sub_{organization_id[:12]}",
            "organization_id": organization_id,
            "plan_name": plan_name,
            "status": "ACTIVE",
            "monthly_price": default_limits["monthly_price"],
            "max_agents": default_limits["max_agents"],
            "max_properties": default_limits["max_properties"],
            "max_conversations_per_month": default_limits["max_conversations"],
            "max_documents": default_limits.get("max_documents", 10)
        }

        if session:
            try:
                stmt = select(Subscription).where(Subscription.organization_id == organization_id)
                res = await session.execute(stmt)
                sub_obj = res.scalar_one_or_none()
                if not sub_obj:
                    sub_obj = Subscription(
                        id=f"sub_{uuid.uuid4().hex[:10]}",
                        organization_id=organization_id,
                        plan_name=plan_name,
                        status="ACTIVE",
                        monthly_price=default_limits["monthly_price"],
                        max_agents=default_limits["max_agents"],
                        max_properties=default_limits["max_properties"],
                        max_conversations_per_month=default_limits["max_conversations"]
                    )
                    session.add(sub_obj)
                    if is_local:
                        await session.commit()
                    else:
                        await session.flush()
                
                sub_dict = {
                    "id": sub_obj.id,
                    "organization_id": sub_obj.organization_id,
                    "plan_name": sub_obj.plan_name,
                    "status": sub_obj.status,
                    "monthly_price": sub_obj.monthly_price,
                    "max_agents": sub_obj.max_agents,
                    "max_properties": sub_obj.max_properties,
                    "max_conversations_per_month": sub_obj.max_conversations_per_month,
                    "max_documents": self.PLAN_LIMITS.get(sub_obj.plan_name.upper(), default_limits).get("max_documents", 10)
                }
                if is_local:
                    await session.close()
            except Exception as e:
                print(f"[Metering] Warning DB subscription lookup failed: {e}")
                if is_local:
                    await session.close()

        return sub_dict

    async def check_billing_quota(
        self,
        organization_id: str,
        resource: str = "agent_turn",
        db: Optional[AsyncSession] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Enforces organization billing subscription quotas for agent turns, agent creation, and documents."""
        sub = await self.get_or_create_subscription_async(organization_id, db=db)
        plan_name = sub["plan_name"].upper()
        limits = self.PLAN_LIMITS.get(plan_name, self.PLAN_LIMITS["STARTER"])

        session = db or self.db_session
        is_local = False
        if not session:
            try:
                session = AsyncSessionLocal()
                is_local = True
            except Exception:
                session = None

        current_usage = 0

        try:
            if resource in ["agent_turn", "chat_message"]:
                max_allowed = sub.get("max_conversations_per_month", limits["max_conversations"])
                if session:
                    stmt = select(func.count(UsageEvent.id)).where(
                        UsageEvent.organization_id == organization_id,
                        UsageEvent.event_type.in_(["agent_turn", "chat_message"])
                    )
                    res = await session.execute(stmt)
                    current_usage = res.scalar() or 0
                else:
                    current_usage = len([e for e in self._events_log if e["organization_id"] == organization_id and e.get("event_type") in ["agent_turn", "chat_message"]])

                if current_usage >= max_allowed:
                    return False, f"Monthly agent turn limit reached ({current_usage}/{max_allowed} turns) for plan '{plan_name}'", {"current": current_usage, "limit": max_allowed, "plan": plan_name}

                # Per-tenant spend cap enforcement
                spend_caps = {"FREE": 5.0, "STARTER": 100.0, "PROFESSIONAL": 500.0, "BUSINESS": 2000.0, "ENTERPRISE": 10000.0}
                max_spend = spend_caps.get(plan_name, 500.0)
                if session:
                    stmt_cost = select(func.sum(UsageEvent.estimated_cost)).where(UsageEvent.organization_id == organization_id)
                    res_cost = await session.execute(stmt_cost)
                    total_cost = res_cost.scalar() or 0.0
                    if total_cost >= max_spend:
                        return False, f"Monthly spend cap limit reached (${round(total_cost, 2)}/${max_spend}) for plan '{plan_name}'", {"total_cost": total_cost, "cap": max_spend, "plan": plan_name}

            elif resource in ["agent_creation", "create_agent"]:
                max_allowed = sub.get("max_agents", limits["max_agents"])
                if session:
                    stmt = select(func.count(Agent.id)).where(Agent.organization_id == organization_id)
                    res = await session.execute(stmt)
                    current_usage = res.scalar() or 0
                else:
                    current_usage = 1

                if current_usage >= max_allowed:
                    return False, f"Agent creation limit reached ({current_usage}/{max_allowed} agents) for plan '{plan_name}'", {"current": current_usage, "limit": max_allowed, "plan": plan_name}

            elif resource in ["document_upload", "upload_document"]:
                max_allowed = limits.get("max_documents", 10)
                if session:
                    stmt = select(func.count(Document.id)).where(Document.organization_id == organization_id)
                    res = await session.execute(stmt)
                    current_usage = res.scalar() or 0
                else:
                    current_usage = 0

                if current_usage >= max_allowed:
                    return False, f"Document upload storage limit reached ({current_usage}/{max_allowed} documents) for plan '{plan_name}'", {"current": current_usage, "limit": max_allowed, "plan": plan_name}

        finally:
            if is_local and session:
                await session.close()

        return True, "Quota check passed", {"current": current_usage, "plan": plan_name}

    async def update_subscription_plan_async(
        self,
        organization_id: str,
        new_plan_name: str,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """Upgrades or modifies organization subscription tier in database."""
        clean_plan = new_plan_name.upper()
        if clean_plan not in self.PLAN_LIMITS:
            raise ValueError(f"Invalid plan name '{new_plan_name}'. Must be one of {list(self.PLAN_LIMITS.keys())}")

        limits = self.PLAN_LIMITS[clean_plan]

        session = db or self.db_session
        is_local = False
        if not session:
            try:
                session = AsyncSessionLocal()
                is_local = True
            except Exception:
                session = None

        if session:
            try:
                stmt = select(Subscription).where(Subscription.organization_id == organization_id)
                res = await session.execute(stmt)
                sub_obj = res.scalar_one_or_none()

                if not sub_obj:
                    sub_obj = Subscription(
                        id=f"sub_{uuid.uuid4().hex[:10]}",
                        organization_id=organization_id,
                        plan_name=clean_plan,
                        status="ACTIVE",
                        monthly_price=limits["monthly_price"],
                        max_agents=limits["max_agents"],
                        max_properties=limits["max_properties"],
                        max_conversations_per_month=limits["max_conversations"]
                    )
                    session.add(sub_obj)
                else:
                    sub_obj.plan_name = clean_plan
                    sub_obj.monthly_price = limits["monthly_price"]
                    sub_obj.max_agents = limits["max_agents"]
                    sub_obj.max_properties = limits["max_properties"]
                    sub_obj.max_conversations_per_month = limits["max_conversations"]

                await session.flush()
                if is_local:
                    await session.commit()
                    await session.close()
            except Exception as e:
                print(f"[Metering] Warning DB subscription update failed: {e}")
                if is_local:
                    await session.rollback()
                    await session.close()

        return {
            "organization_id": organization_id,
            "plan_name": clean_plan,
            "status": "ACTIVE",
            "monthly_price": limits["monthly_price"],
            "max_agents": limits["max_agents"],
            "max_properties": limits["max_properties"],
            "max_conversations_per_month": limits["max_conversations"],
            "max_documents": limits.get("max_documents", 10),
            "message": f"Subscription plan successfully updated to {clean_plan}."
        }

SaaSMeteringService = UsageMeteringService

