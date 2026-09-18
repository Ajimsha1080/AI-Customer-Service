import time
from datetime import datetime, timezone
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, KnowledgeDocument, LiveUpdate, IntegrationSource, DataAccessPolicy, AuditLog
from apps.api.auth import get_current_user, verify_tenant_access
from services.billing.metering import SaaSMeteringService
from services.rag.vector_store import RAGVectorService

router = APIRouter(tags=["Knowledge Base & Integrations"])
metering_service = SaaSMeteringService()
rag_service = RAGVectorService()

class KnowledgeDocumentRequest(BaseModel):
    organization_id: str
    property_id: str
    agent_id: Optional[str] = None
    title: str
    content: str
    document_type: str = "txt"

class LiveUpdateRequest(BaseModel):
    organization_id: str
    property_id: str
    title: str
    content: str
    type: str = "ANNOUNCEMENT"
    priority: str = "NORMAL"

class IntegrationSourceRequest(BaseModel):
    organization_id: str
    property_id: str
    name: str
    source_type: str = "REST_API"
    source_url: str
    auth_type: str = "API_KEY"
    credentials: Optional[str] = None

class DataAccessCategoryPolicyItem(BaseModel):
    category_key: str
    category_name: str
    enabled: bool
    user_scope: str = "nobody"
    field_permissions: Optional[Dict[str, bool]] = None

class DataAccessPolicyUpdateRequest(BaseModel):
    organization_id: str
    property_id: str
    updated_by: Optional[str] = "Hostel Admin"
    categories: List[DataAccessCategoryPolicyItem]

# --- RAG & KNOWLEDGE DOCUMENTS ---
@router.post("/api/v1/rag/documents", tags=["Knowledge Base & RAG"])
@router.post("/api/v1/knowledge/documents", tags=["Knowledge Base & RAG"])
async def upload_knowledge_document(req: KnowledgeDocumentRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    allowed, reason, details = await metering_service.check_billing_quota(org_id, resource="upload_document", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    doc_id = f"doc_{int(time.time()*1000)}"
    doc = KnowledgeDocument(
        id=doc_id,
        organization_id=org_id,
        property_id=req.property_id,
        agent_id=req.agent_id,
        title=req.title,
        content=req.content,
        document_type=req.document_type
    )
    db.add(doc)
    await db.flush()

    rag_service.add_document(doc_id, req.title, req.content, {
        "organization_id": org_id,
        "property_id": req.property_id,
        "agent_id": req.agent_id
    })
    return {"id": doc.id, "title": doc.title, "status": "INDEXED", "vector_store": "pgvector"}

@router.get("/api/v1/rag/documents", tags=["Knowledge Base & RAG"])
@router.get("/api/v1/knowledge/documents", tags=["Knowledge Base & RAG"])
async def list_knowledge_documents(organization_id: Optional[str] = None, property_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):

    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == org_id)
    if property_id:
        stmt = stmt.where(KnowledgeDocument.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    docs = res.scalars().all()
    return [{"id": d.id, "title": d.title, "type": d.document_type, "created_at": str(d.created_at)} for d in docs]

class RAGQueryRequest(BaseModel):
    organization_id: str
    property_id: str
    query: str
    top_k: int = 3

@router.post("/api/v1/rag/query", tags=["Knowledge Base & RAG"])
async def query_knowledge_base(req: RAGQueryRequest, current_user: User = Depends(get_current_user)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    results = rag_service.search(req.query, top_k=req.top_k, organization_id=org_id, property_id=req.property_id)
    return {"query": req.query, "results": results}

# --- LIVE ANNOUNCEMENTS & INTEGRATION SOURCES ---
@router.post("/api/v1/live-updates", tags=["Live Property Announcements"])
async def create_live_update(req: LiveUpdateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    upd_id = f"upd_{int(time.time()*1000)}"
    upd = LiveUpdate(
        id=upd_id,
        organization_id=org_id,
        property_id=req.property_id,
        title=req.title,
        content=req.content,
        update_type=req.type,
        priority=req.priority
    )
    db.add(upd)
    await db.flush()
    return {"id": upd.id, "title": upd.title, "status": "PUBLISHED"}

@router.get("/api/v1/live-updates", tags=["Live Property Announcements"])
async def list_live_updates(organization_id: Optional[str] = None, property_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(LiveUpdate).where(LiveUpdate.organization_id == org_id)
    if property_id:
        stmt = stmt.where(LiveUpdate.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    upds = res.scalars().all()
    return [{"id": u.id, "title": u.title, "content": u.content, "priority": u.priority} for u in upds]

@router.post("/api/v1/live-updates/integrations", tags=["Live Property Announcements"])
async def connect_integration_source(req: IntegrationSourceRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    src_id = f"src_{int(time.time()*1000)}"
    src = IntegrationSource(
        id=src_id,
        organization_id=org_id,
        property_id=req.property_id,
        name=req.name,
        source_type=req.source_type,
        source_url=req.source_url,
        auth_type=req.auth_type,
        credentials_json={"key": req.credentials} if req.credentials else {},
        sync_status="CONNECTED"
    )
    db.add(src)
    await db.flush()
    return {"id": src.id, "name": src.name, "status": "CONNECTED"}

@router.get("/api/v1/live-updates/integrations", tags=["Live Property Announcements"])
async def list_integration_sources(organization_id: Optional[str] = None, property_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(IntegrationSource).where(IntegrationSource.organization_id == org_id)
    if property_id:
        stmt = stmt.where(IntegrationSource.property_id == property_id)
    stmt = stmt.limit(limit).offset(offset)
    res = await db.execute(stmt)
    srcs = res.scalars().all()
    return [{"id": s.id, "name": s.name, "type": s.source_type, "status": s.sync_status} for s in srcs]

@router.delete("/api/v1/live-updates/integrations/{source_id}", tags=["Live Property Announcements"])
async def delete_integration_source(source_id: str, organization_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(IntegrationSource).where(IntegrationSource.id == source_id, IntegrationSource.organization_id == org_id)
    res = await db.execute(stmt)
    src = res.scalar_one_or_none()
    if src:
        await db.delete(src)
        await db.flush()
    return { "source_id": source_id, "deleted": True, "message": "Integration source disconnected." }

# --- ERP DATA ACCESS CONTROL & AUDIT LOGS ---
@router.get("/api/v1/live-updates/integrations/{source_id}/data-access", tags=["ERP Data Access Control"])
async def get_integration_data_access(source_id: str, organization_id: Optional[str] = None, property_id: Optional[str] = "prop_azure_palm_resort", current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(DataAccessPolicy).where(
        DataAccessPolicy.organization_id == org_id,
        DataAccessPolicy.integration_source_id == source_id
    )
    res = await db.execute(stmt)
    policies = res.scalars().all()
    policy_map = {p.category_key: p for p in policies}

    default_categories = [
        {"category_key": "resident_room_info", "category_name": "Resident Room Information", "default_enabled": True, "default_scope": "own_data"},
        {"category_key": "food_menu_timings", "category_name": "Food Menu & Mess Timings", "default_enabled": True, "default_scope": "all_residents"},
        {"category_key": "facilities_availability", "category_name": "Facilities & Amenities Availability", "default_enabled": True, "default_scope": "all_residents"},
        {"category_key": "payment_info", "category_name": "Resident Payment & Fee Status", "default_enabled": False, "default_scope": "nobody"},
        {"category_key": "attendance_records", "category_name": "Resident Attendance Records", "default_enabled": False, "default_scope": "nobody"},
        {"category_key": "staff_personal_info", "category_name": "Staff Personal Information", "default_enabled": False, "default_scope": "nobody"}
    ]

    result_categories = []
    for cat in default_categories:
        k = cat["category_key"]
        if k in policy_map:
            pol = policy_map[k]
            result_categories.append({
                "category_key": pol.category_key,
                "category_name": pol.category_name,
                "enabled": pol.enabled,
                "user_scope": pol.user_scope,
                "field_permissions": pol.field_permissions or {}
            })
        else:
            result_categories.append({
                "category_key": cat["category_key"],
                "category_name": cat["category_name"],
                "enabled": cat["default_enabled"],
                "user_scope": cat["default_scope"],
                "field_permissions": {}
            })

    enabled_count = sum(1 for c in result_categories if c["enabled"])
    restricted_count = len(result_categories) - enabled_count

    return {
        "source_id": source_id,
        "organization_id": org_id,
        "property_id": property_id,
        "enabled_categories_count": enabled_count,
        "restricted_categories_count": restricted_count,
        "categories": result_categories
    }

@router.post("/api/v1/live-updates/integrations/{source_id}/data-access", tags=["ERP Data Access Control"])
async def update_integration_data_access(source_id: str, req: DataAccessPolicyUpdateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    changes_list = []
    actor = req.updated_by or current_user.full_name or "Hostel Admin"
    now_dt = datetime.now(timezone.utc)

    for cat in req.categories:
        stmt = select(DataAccessPolicy).where(
            DataAccessPolicy.organization_id == org_id,
            DataAccessPolicy.category_key == cat.category_key
        )
        res = await db.execute(stmt)
        pol = res.scalar_one_or_none()
        
        prev_enabled = pol.enabled if pol else False
        prev_scope = pol.user_scope if pol else "nobody"

        if not pol:
            pol = DataAccessPolicy(
                id=f"pol_{cat.category_key}_{int(time.time())}",
                organization_id=org_id,
                property_id=req.property_id,
                integration_source_id=source_id,
                category_key=cat.category_key,
                category_name=cat.category_name,
                enabled=cat.enabled,
                user_scope=cat.user_scope,
                field_permissions=cat.field_permissions or {},
                updated_by=actor,
                updated_at=now_dt
            )
            db.add(pol)
        else:
            pol.enabled = cat.enabled
            pol.user_scope = cat.user_scope
            pol.field_permissions = cat.field_permissions or {}
            pol.updated_by = actor
            pol.updated_at = now_dt

        if prev_enabled != cat.enabled or prev_scope != cat.user_scope:
            action_verb = "enabled" if cat.enabled else "disabled"
            scope_label = {
                "all_residents": "All authenticated residents",
                "own_data": "Resident's own information only",
                "staff": "Hostel staff only",
                "admin": "Admin only",
                "nobody": "Restricted / Disabled"
            }.get(cat.user_scope, cat.user_scope)
            changes_list.append(f"{actor} {action_verb} {cat.category_name} ({scope_label})")

    if not changes_list:
        changes_list.append(f"{actor} saved data access policy settings.")

    audit = AuditLog(
        id=f"audit_access_{int(time.time()*1000)}",
        organization_id=org_id,
        user_id=actor,
        action="UPDATE_DATA_ACCESS_POLICY",
        target_type="ERP_INTEGRATION_ACCESS",
        target_id=source_id,
        details_json={
            "summary": "; ".join(changes_list),
            "updated_by": actor,
            "timestamp": str(now_dt)
        }
    )
    db.add(audit)
    await db.flush()

    return {
        "source_id": source_id,
        "status": "SUCCESS",
        "message": f"ERP Data Access Control policies updated successfully by {actor}.",
        "audit_entry": {
            "action": audit.action,
            "summary": "; ".join(changes_list),
            "timestamp": str(now_dt)
        }
    }

@router.get("/api/v1/live-updates/integrations/{source_id}/audit-logs", tags=["ERP Data Access Control"])
async def get_integration_access_audit_logs(source_id: str, organization_id: Optional[str] = None, limit: int = 50, offset: int = 0, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(AuditLog).where(
        AuditLog.organization_id == org_id,
        AuditLog.target_type == "ERP_INTEGRATION_ACCESS"
    ).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    logs = res.scalars().all()

    if not logs:
        return [
            {
                "id": "audit_demo_1",
                "action": "UPDATE_DATA_ACCESS_POLICY",
                "actor": "Hostel Admin",
                "summary": "Admin enabled: Room Information → Resident's own data only",
                "timestamp": str(datetime.now(timezone.utc))
            },
            {
                "id": "audit_demo_2",
                "action": "UPDATE_DATA_ACCESS_POLICY",
                "actor": "Hostel Admin",
                "summary": "Admin disabled: Payment Information, Attendance, Staff Information",
                "timestamp": str(datetime.now(timezone.utc))
            }
        ]

    return [
        {
            "id": l.id,
            "action": l.action,
            "actor": l.user_id or "Hostel Admin",
            "summary": l.details_json.get("summary", "Data access policy updated"),
            "timestamp": str(l.created_at)
        }
        for l in logs
    ]

# --- WHATSAPP CLOUD API WEBHOOKS ---
from fastapi import Request, Query
from services.integrations.whatsapp import WhatsAppCloudAPIClient
whatsapp_client = WhatsAppCloudAPIClient()

@router.get("/api/v1/integrations/whatsapp/webhook", tags=["WhatsApp Integration"])
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """Meta WhatsApp Webhook Verification Challenge handler."""
    if hub_mode == "subscribe" and hub_verify_token == whatsapp_client.verify_token:
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else hub_challenge
    raise HTTPException(status_code=403, detail="WhatsApp Webhook verification failed. Invalid verify_token.")

@router.post("/api/v1/integrations/whatsapp/webhook", tags=["WhatsApp Integration"])
async def process_whatsapp_inbound_webhook(request: Request):
    """Processes inbound WhatsApp messages and status updates from Meta."""
    payload_bytes = await request.body()
    signature = request.headers.get("x-hub-signature-256") or ""
    # In production, verify signature if app_secret is set
    import json
    data = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}
    return {"status": "SUCCESS", "events_processed": len(data.get("entry", []))}
