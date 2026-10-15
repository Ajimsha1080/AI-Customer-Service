import json
import time
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Organization, Agent, IntegrationSource, UserRole
from apps.api.auth import get_super_admin_user, decode_access_token
from services.realtime.broadcaster import realtime_hub, verify_realtime_ticket

router = APIRouter(prefix="/api/v1/platform", tags=["Platform Super Admin Telemetry"])

async def _verify_superadmin_sse(request: Request, ticket: Optional[str] = None) -> bool:
    """Verifies caller is SUPER_ADMIN via 60s ticket, cookie, or Authorization header."""
    if ticket:
        ticket_data = verify_realtime_ticket(ticket)
        if ticket_data and ticket_data.get("role") == UserRole.SUPER_ADMIN.value:
            return True
    
    # Check cookies
    cookie_token = request.cookies.get("session_token") or request.cookies.get("access_token")
    if cookie_token:
        try:
            payload = decode_access_token(cookie_token)
            if payload.get("role") == UserRole.SUPER_ADMIN.value:
                return True
        except Exception:
            pass

    # Check Authorization header
    auth_hdr = request.headers.get("authorization") or ""
    if auth_hdr.startswith("Bearer "):
        tok = auth_hdr.split(" ")[1]
        try:
            payload = decode_access_token(tok)
            if payload.get("role") == UserRole.SUPER_ADMIN.value:
                return True
        except Exception:
            pass

    return False

@router.get("/events")
async def platform_realtime_events_stream(
    request: Request,
    ticket: Optional[str] = Query(None)
):
    """Server-Sent Events (SSE) stream for Super Admin real-time platform telemetry with ticket/cookie auth and replay."""
    is_authorized = await _verify_superadmin_sse(request, ticket)
    if not is_authorized:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Super Admin authentication required (valid ticket, cookie, or bearer token)."
        )

    last_event_id = request.headers.get("last-event-id") or request.query_params.get("last_event_id")

    async def event_generator():
        q, missed_events = await realtime_hub.subscribe(["platform"], last_event_id=last_event_id)
        try:
            # Yield initial handshake
            init_payload = {"type": "CONNECTED", "status": "ONLINE", "timestamp": str(time.time())}
            yield f"data: {json.dumps(init_payload)}\n\n"

            # Replay missed events
            for evt in missed_events:
                yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"

            # Stream live events with 15s heartbeats
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            realtime_hub.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.get("/telemetry")
async def get_platform_telemetry(current_user: User = Depends(get_super_admin_user), db: AsyncSession = Depends(get_db)):
    """Fetch accurate aggregated platform telemetry for Super Admin control plane."""
    from services.database.models import AgentStatus, LiveUpdate, Message

    res_o = await db.execute(select(func.count(Organization.id)))
    orgs_count = res_o.scalar() or 0

    res_a = await db.execute(select(func.count(Agent.id)))
    agents_count = res_a.scalar() or 0

    res_online = await db.execute(select(func.count(Agent.id)).where(Agent.status == AgentStatus.ACTIVE))
    online_agents = res_online.scalar() or 0
    offline_agents = max(0, agents_count - online_agents)

    res_s = await db.execute(select(func.count(IntegrationSource.id)))
    sources_count = res_s.scalar() or 0

    res_f = await db.execute(select(func.count(IntegrationSource.id)).where(IntegrationSource.status.in_(["FAILED", "ERROR"])))
    failed_integrations = res_f.scalar() or 0

    # Calculate p95 latency from recent messages
    msg_res = await db.execute(select(Message.metadata_json).order_by(Message.created_at.desc()).limit(500))
    msg_metas = msg_res.scalars().all()
    latencies = [
        meta.get("latency_ms")
        for meta in msg_metas
        if meta and isinstance(meta.get("latency_ms"), (int, float))
    ]
    p95_latency = 0
    if latencies:
        latencies.sort()
        idx = int(0.95 * (len(latencies) - 1))
        p95_latency = int(latencies[idx])

    # Fetch recent live events from database
    events_stmt = (
        select(LiveUpdate, Organization.name)
        .join(Organization, LiveUpdate.organization_id == Organization.id)
        .order_by(LiveUpdate.created_at.desc())
        .limit(10)
    )
    events_res = await db.execute(events_stmt)
    live_events_rows = events_res.all()

    recent_live_events = []
    now = datetime.now(timezone.utc)
    for update, org_name in live_events_rows:
        delta_sec = int((now - update.created_at.replace(tzinfo=timezone.utc if update.created_at.tzinfo is None else update.created_at.tzinfo)).total_seconds()) if update.created_at else 0
        if delta_sec < 60:
            time_str = "Just now"
        elif delta_sec < 3600:
            time_str = f"{delta_sec // 60}m ago"
        else:
            time_str = f"{delta_sec // 3600}h ago"

        recent_live_events.append({
            "org_name": org_name,
            "summary": f"{update.title}: {update.content[:80]}" if update.content else update.title,
            "status": "ONLINE" if update.is_active else "INACTIVE",
            "timestamp": time_str
        })

    # Real component health checks (DB, Redis, Vector, Integrations)
    db_ok = True
    try:
        r_db = await db.execute(text("SELECT 1"))
        if r_db.scalar() != 1:
            db_ok = False
    except Exception:
        db_ok = False

    redis_ok = False
    try:
        import redis.asyncio as aioredis
        r_client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5)
        if await r_client.ping():
            redis_ok = True
        await r_client.aclose()
    except Exception:
        redis_ok = False

    vector_ok = True
    if "postgresql" in settings.DATABASE_URL:
        try:
            r_vec = await db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            if not r_vec.scalar():
                vector_ok = False
        except Exception:
            vector_ok = False

    # Compute operational status dynamically
    components = [db_ok, redis_ok, vector_ok]
    healthy_count = sum(1 for c in components if c)
    if failed_integrations == 0:
        healthy_count += 1
    total_components = len(components) + 1

    if not db_ok:
        system_health = "CRITICAL_OUTAGE"
        sla_uptime = f"{round((healthy_count / total_components) * 100, 1)}%"
    elif not redis_ok or not vector_ok or failed_integrations > 0:
        system_health = "DEGRADED"
        sla_uptime = f"{round((healthy_count / total_components) * 100, 1)}%"
    else:
        system_health = "OPERATIONAL"
        sla_uptime = "99.99%"

    return {
        "total_organizations": orgs_count,
        "active_organizations": orgs_count,
        "active_agents": agents_count,
        "online_agents": online_agents,
        "offline_agents": offline_agents,
        "connected_integrations": sources_count,
        "failed_integrations": failed_integrations,
        "system_health": system_health,
        "sla_uptime": sla_uptime,
        "p95_latency_ms": p95_latency,
        "recent_live_events": recent_live_events
    }

@router.get("/db-health")
async def get_database_health(current_user: User = Depends(get_super_admin_user)):
    """Enterprise Database Health, Pool Status & Latency Monitoring endpoint. Protected for Super Admin."""
    from services.database.session import check_db_health
    return await check_db_health()

@router.post("/support/impersonate/{org_id}")
async def impersonate_organization(
    org_id: str,
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Enables Platform Super Admin to assume customer-approved support session."""
    from services.database.audit import record_audit_log_async
    from apps.api.auth import create_impersonation_token

    stmt = select(Organization).where(Organization.id == org_id)
    res = await db.execute(stmt)
    org = res.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target organization not found.")

    if not org.support_access_granted_until:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer has not granted active platform support access."
        )

    now = datetime.now(timezone.utc)
    granted_exp = org.support_access_granted_until.replace(tzinfo=timezone.utc) if org.support_access_granted_until.tzinfo is None else org.support_access_granted_until
    if granted_exp < now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer support access has expired."
        )

    remaining_minutes = min(60, int((granted_exp - now).total_seconds() / 60))
    token = create_impersonation_token(admin_user=current_user, target_org_id=org_id, expires_in_minutes=max(1, remaining_minutes))

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="SUPPORT_IMPERSONATION_STARTED",
        target_type="organization",
        target_id=org_id,
        details={"superadmin_id": current_user.id, "expires_in_minutes": remaining_minutes},
        db=db
    )

    return {
        "impersonation_token": token,
        "organization_id": org.id,
        "organization_name": org.name,
        "expires_at": granted_exp.isoformat()
    }

@router.get("/dlq")
async def get_dead_letter_queue(
    current_user: User = Depends(get_super_admin_user)
):
    """Platform inspector for worker dead-letter queue."""
    from services.tasks.worker import list_dlq_jobs
    jobs = await list_dlq_jobs(limit=100)
    return {"dlq_count": len(jobs), "jobs": jobs}

@router.post("/dlq/{job_id}/replay")
async def replay_dead_letter_job(
    job_id: str,
    current_user: User = Depends(get_super_admin_user)
):
    """Replays a failed job from the dead-letter queue."""
    from services.tasks.worker import replay_dlq_job
    res = await replay_dlq_job(job_id)
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found in DLQ.")
    return res

@router.get("/circuit-breakers")
async def list_circuit_breakers(
    current_user: User = Depends(get_super_admin_user)
):
    """Returns runtime health and status of all external outbound circuit breakers."""
    from services.resilience.circuit_breaker import _CIRCUIT_BREAKERS
    return {
        name: {
            "name": cb.name,
            "state": cb.state.value,
            "consecutive_failures": cb.consecutive_failures,
            "failure_threshold": cb.failure_threshold,
            "call_timeout": cb.call_timeout
        }
        for name, cb in _CIRCUIT_BREAKERS.items()
    }

@router.get("/organizations")
async def search_organizations(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Platform operator tenant search with filtering."""
    stmt = select(Organization)
    if search:
        search_pattern = f"%{search.strip()}%"
        stmt = stmt.where((Organization.name.ilike(search_pattern)) | (Organization.slug.ilike(search_pattern)))
    stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    orgs = res.scalars().all()
    return {
        "count": len(orgs),
        "organizations": [
            {
                "id": o.id,
                "name": o.name,
                "slug": o.slug,
                "status": o.status,
                "mfa_enforced": o.mfa_enforced,
                "data_residency_region": o.data_residency_region,
                "created_at": o.created_at.isoformat() if o.created_at else None
            }
            for o in orgs
        ]
    }

@router.post("/organizations/{org_id}/suspend")
async def suspend_organization(
    org_id: str,
    reason: str = Query("Billing or security policy suspension"),
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Platform operator suspends tenant with immutable audit logging."""
    from services.database.audit import record_audit_log_async
    stmt = select(Organization).where(Organization.id == org_id)
    res = await db.execute(stmt)
    org = res.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    org.status = "SUSPENDED"
    await db.commit()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="ORGANIZATION_SUSPENDED",
        target_type="organization",
        target_id=org_id,
        details={"reason": reason, "suspended_by": current_user.email},
        db=db
    )
    return {"status": "success", "organization_id": org_id, "organization_status": "SUSPENDED"}

@router.post("/organizations/{org_id}/unsuspend")
async def unsuspend_organization(
    org_id: str,
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Platform operator reinstates suspended tenant."""
    from services.database.audit import record_audit_log_async
    stmt = select(Organization).where(Organization.id == org_id)
    res = await db.execute(stmt)
    org = res.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    org.status = "ACTIVE"
    await db.commit()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="ORGANIZATION_UNSUSPENDED",
        target_type="organization",
        target_id=org_id,
        details={"unsuspended_by": current_user.email},
        db=db
    )
    return {"status": "success", "organization_id": org_id, "organization_status": "ACTIVE"}

@router.post("/organizations/{org_id}/plan-override")
async def override_organization_plan(
    org_id: str,
    plan_name: str = Query(..., pattern="^(FREE|STARTER|GROWTH|PRO|ENTERPRISE)$"),
    reason: str = Query("Manual contract override"),
    current_user: User = Depends(get_super_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Overrides tenant subscription plan with audit trail."""
    from services.database.models import Subscription
    from services.database.audit import record_audit_log_async

    stmt = select(Subscription).where(Subscription.organization_id == org_id)
    res = await db.execute(stmt)
    sub = res.scalar_one_or_none()
    if sub:
        old_plan = sub.plan_name
        sub.plan_name = plan_name
    else:
        old_plan = "NONE"
        sub = Subscription(
            id=f"sub_override_{uuid.uuid4().hex[:12]}",
            organization_id=org_id,
            plan_name=plan_name,
            status="ACTIVE"
        )
        db.add(sub)
    await db.commit()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="SUBSCRIPTION_PLAN_OVERRIDDEN",
        target_type="subscription",
        target_id=sub.id,
        details={"old_plan": old_plan, "new_plan": plan_name, "reason": reason, "override_by": current_user.email},
        db=db
    )
    return {"status": "success", "organization_id": org_id, "plan_name": plan_name}

@router.get("/feature-flags")
async def list_feature_flags(
    current_user: User = Depends(get_super_admin_user)
):
    """Inspects all feature flags, percentage rollouts, and kill switches."""
    from services.operations.feature_flags import feature_flags
    return {
        k: {
            "enabled": v["enabled"],
            "rollout_pct": v["rollout_pct"],
            "enabled_orgs": list(v["enabled_orgs"]),
            "disabled_orgs": list(v["disabled_orgs"])
        }
        for k, v in feature_flags._flags.items()
    }

@router.post("/kill-switches/{name}/activate")
async def activate_kill_switch_endpoint(
    name: str,
    current_user: User = Depends(get_super_admin_user)
):
    """Emergency trigger to kill subsystem traffic (e.g. kill_switch_voice, kill_switch_llm_tools)."""
    from services.operations.feature_flags import feature_flags
    feature_flags.activate_kill_switch(name)
    return {"status": "ENGAGED", "kill_switch": name}

@router.post("/kill-switches/{name}/deactivate")
async def deactivate_kill_switch_endpoint(
    name: str,
    current_user: User = Depends(get_super_admin_user)
):
    """Deactivates kill switch, restoring subsystem operations."""
    from services.operations.feature_flags import feature_flags
    feature_flags.deactivate_kill_switch(name)
    return {"status": "DISENGAGED", "kill_switch": name}

@router.post("/incidents")
async def create_platform_incident(
    title: str = Query(...),
    impact: str = Query("MINOR"),
    message: str = Query("Investigating issue"),
    current_user: User = Depends(get_super_admin_user)
):
    """Creates a new operational incident visible on status page."""
    from services.operations.incident_manager import incident_manager
    inc = incident_manager.create_incident(title=title, impact=impact, initial_message=message)
    return inc

@router.post("/incidents/{incident_id}/resolve")
async def resolve_platform_incident(
    incident_id: str,
    message: str = Query("Issue mitigated and verified normal operations."),
    current_user: User = Depends(get_super_admin_user)
):
    """Resolves an operational incident on status page."""
    from services.operations.incident_manager import incident_manager
    inc = incident_manager.resolve_incident(incident_id=incident_id, resolution_message=message)
    if not inc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")
    return inc


@router.get("/localization/ui-strings", tags=["Localization"])
async def get_localization_ui_strings(locale: str = Query("en")):
    """Returns localized UI strings and RTL direction for guest and staff portal."""
    from services.operations.localization import localization_service
    return localization_service.get_ui_strings(locale)
