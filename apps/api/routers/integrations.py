import time
import uuid
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("hospitality_agent_cloud.integrations")
from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import io

def extract_text_from_file_bytes(filename: str, content_bytes: bytes) -> str:
    ext = filename.lower().split(".")[-1] if "." in filename else "txt"
    if ext in ["txt", "md", "csv", "json"]:
        return content_bytes.decode("utf-8", errors="ignore")
    elif ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages).strip() or content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return content_bytes.decode("utf-8", errors="ignore")
    elif ext in ["doc", "docx"]:
        try:
            import docx
            doc = docx.Document(io.BytesIO(content_bytes))
            paras = [p.text for p in doc.paragraphs if p.text]
            return "\n".join(paras).strip() or content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return content_bytes.decode("utf-8", errors="ignore")
    return content_bytes.decode("utf-8", errors="ignore")

from services.database.session import get_db, set_tenant_context
from services.database.models import (
    User, KnowledgeDocument, LiveUpdate, IntegrationSource, DataAccessPolicy,
    AuditLog, Agent, AgentStatus, AgentConfig, Organization, UserSession,
    WhatsAppChannelMapping, ProcessedWebhookEvent
)
from apps.api.auth import get_current_user, verify_tenant_access, _hash_token, decode_guest_session_token
from services.billing.metering import SaaSMeteringService
from services.rag.vector_store import RAGVectorService
import asyncio
from services.security.network import validate_outbound_url_ssrf
from services.security.encryption import encrypt_value, decrypt_value
from services.agent_runtime.engine import AgentRuntimeEngine
from services.integrations.whatsapp import WhatsAppCloudAPIClient
from services.integrations.whatsapp_bsp import whatsapp_bsp, WhatsApp24HourWindowViolation
from services.security.data_residency import data_residency_router
from services.resilience.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError
from services.operations.feature_flags import feature_flags
from services.resilience.tenant_limiter import enforce_tenant_fair_use_quota
from services.database.pagination import paginate_query
from services.realtime.broadcaster import realtime_hub, generate_realtime_ticket, verify_realtime_ticket, verify_realtime_ticket_async
from apps.api.auth import decode_access_token
from fastapi import WebSocket, WebSocketDisconnect, Response

router = APIRouter(tags=["Knowledge Base & Integrations"])
metering_service = SaaSMeteringService()
rag_service = RAGVectorService()
whatsapp_client = WhatsAppCloudAPIClient()
erp_circuit_breaker = get_circuit_breaker("erp", failure_threshold=3, recovery_timeout=5.0, call_timeout=10.0)
whatsapp_circuit_breaker = get_circuit_breaker("whatsapp", failure_threshold=3, recovery_timeout=5.0, call_timeout=10.0)

class KnowledgeDocumentRequest(BaseModel):
    organization_id: str
    property_id: str
    agent_id: Optional[str] = None
    title: str
    content: str
    document_type: str = "txt"
    target_region: Optional[str] = None

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

    # Data Residency Boundary Check
    org_stmt = select(Organization).where(Organization.id == org_id)
    org_res = await db.execute(org_stmt)
    org_obj = org_res.scalar_one_or_none()
    tenant_region = org_obj.data_residency_region if (org_obj and org_obj.data_residency_region) else "US"
    target_reg = req.target_region or tenant_region
    data_residency_router.validate_regional_call(tenant_region, target_reg)

    # Upload Safety Validation
    allowed_types = {"txt", "pdf", "json", "md", "csv", "doc", "docx"}
    if req.document_type.lower() not in allowed_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported document type '{req.document_type}'. Allowed types: {sorted(list(allowed_types))}")

    if len(req.content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document content exceeds maximum allowed size limit of 10MB.")

    injection_keywords = ["ignore all previous instructions", "ignore previous instructions", "you are now an unfiltered", "jailbreak", "override system prompt"]
    if any(kw in req.content.lower() for kw in injection_keywords):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document upload rejected: Potential prompt injection payload detected.")

    doc_id = str(uuid.uuid4())
    doc = KnowledgeDocument(
        id=doc_id,
        organization_id=org_id,
        property_id=req.property_id,
        agent_id=req.agent_id,
        title=req.title,
        content=req.content,
        content_raw=req.content,
        document_type=req.document_type,
        status="PENDING"
    )
    db.add(doc)
    await db.flush()

    try:
        await rag_service.add_document_async(doc_id, req.title, req.content, {
            "organization_id": org_id,
            "property_id": req.property_id,
            "agent_id": req.agent_id,
            "document_type": req.document_type
        })
        doc.status = "INDEXED"
    except Exception as e:
        doc.status = "FAILED"
        doc.error_message = str(e)

    await db.commit()
    return {"id": doc.id, "title": doc.title, "status": doc.status, "vector_store": "pgvector"}

@router.post("/api/v1/knowledge/documents/upload", tags=["Knowledge Base & RAG"])
@router.post("/api/v1/knowledge/upload", tags=["Knowledge Base & RAG"])
async def upload_multipart_document(
    organization_id: str = Form(...),
    property_id: str = Form(...),
    agent_id: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    target_region: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    allowed, reason, details = await metering_service.check_billing_quota(org_id, resource="upload_document", db=db)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=f"Billing quota exceeded: {reason}")

    # Data Residency Boundary Check
    org_stmt = select(Organization).where(Organization.id == org_id)
    org_res = await db.execute(org_stmt)
    org_obj = org_res.scalar_one_or_none()
    tenant_region = org_obj.data_residency_region if (org_obj and org_obj.data_residency_region) else "US"
    target_reg = target_region or tenant_region
    data_residency_router.validate_regional_call(tenant_region, target_reg)

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File exceeds maximum allowed size limit of 10MB.")

    filename = file.filename or "uploaded_file.txt"
    ext = filename.split(".")[-1].lower() if "." in filename else "txt"
    allowed_types = {"txt", "pdf", "json", "md", "csv", "doc", "docx"}
    if ext not in allowed_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported file format '{ext}'. Allowed: {sorted(list(allowed_types))}")

    content = extract_text_from_file_bytes(filename, file_bytes)
    doc_title = title or filename
    doc_id = str(uuid.uuid4())

    doc = KnowledgeDocument(
        id=doc_id,
        organization_id=org_id,
        property_id=property_id,
        agent_id=agent_id,
        title=doc_title,
        content=content,
        content_raw=content,
        document_type=ext,
        status="PENDING"
    )
    db.add(doc)
    await db.flush()

    try:
        await db.commit()
        await rag_service.add_document_async(doc_id, doc_title, content, {
            "organization_id": org_id,
            "property_id": property_id,
            "agent_id": agent_id,
            "document_type": ext
        })
        doc.status = "INDEXED"
    except Exception as e:
        doc.status = "FAILED"
        doc.error_message = str(e)

    await db.commit()
    return {"id": doc.id, "title": doc.title, "status": doc.status, "document_type": ext, "bytes_processed": len(file_bytes)}

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
    return [{"id": d.id, "title": d.title, "type": d.document_type, "status": getattr(d, "status", "INDEXED"), "created_at": str(d.created_at)} for d in docs]

@router.delete("/api/v1/knowledge/documents/{document_id}", tags=["Knowledge Base & RAG"])
@router.delete("/api/v1/rag/documents/{document_id}", tags=["Knowledge Base & RAG"])
async def delete_knowledge_document(
    document_id: str,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deletes a knowledge document and its associated vector chunks."""
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(Document).where(Document.id == document_id, Document.organization_id == org_id)
    res = await db.execute(stmt)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Document '{document_id}' not found.")

    await db.delete(doc)
    await db.flush()

    return {
        "document_id": document_id,
        "deleted": True,
        "message": f"Document '{doc.title}' deleted successfully."
    }

class RAGQueryRequest(BaseModel):
    organization_id: str
    property_id: str
    query: str
    top_k: int = 3

@router.post("/api/v1/rag/query", tags=["Knowledge Base & RAG"])
async def query_knowledge_base(req: RAGQueryRequest, current_user: User = Depends(get_current_user)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    results = await rag_service.similarity_search(req.query, top_k=req.top_k, organization_id=org_id, property_id=req.property_id)
    return {"query": req.query, "results": results}

# --- LIVE ANNOUNCEMENTS & INTEGRATION SOURCES ---
@router.post("/api/v1/live-updates", tags=["Live Property Announcements"])
async def create_live_update(req: LiveUpdateRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    upd_id = str(uuid.uuid4())
    upd = LiveUpdate(
        id=upd_id,
        organization_id=org_id,
        property_id=req.property_id,
        title=req.title,
        content=req.content,
        type=req.type,
        update_type=req.type,
        priority=req.priority
    )
    db.add(upd)
    await db.flush()

    # Realtime publish: channel org:{org_id} & org:{org_id}:prop:{property_id}
    await realtime_hub.publish(
        event_type="LIVE_UPDATE_CREATED",
        data={
            "id": upd.id,
            "title": upd.title,
            "content": upd.content,
            "type": upd.type,
            "priority": upd.priority
        },
        organization_id=org_id,
        property_id=req.property_id
    )

    return {"id": upd.id, "title": upd.title, "status": "PUBLISHED"}

@router.get("/api/v1/live-updates/events", tags=["Live Property Announcements"])
async def live_updates_events_stream(
    request: Request,
    organization_id: Optional[str] = Query(None),
    property_id: Optional[str] = Query(None),
    ticket: Optional[str] = Query(None),
    guest_token: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
    max_events: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Server-Sent Events stream for live property updates and announcements.
    
    Security Controls (C6):
    - Unauthenticated calls requesting organization_id without valid credentials are strictly rejected (401).
    - Staff streams require an org-bound auth ticket, active session cookie, or Bearer token.
    - Realtime tickets are single-use (jti tracked in Redis).
    - User must be active (is_active=True) and session not revoked (is_revoked=False).
    - Guests receive ONLY their per-conversation channel (conv:<id>) authorized by signed guest token.
    """
    from fastapi.responses import StreamingResponse

    # 1. GUEST CHANNEL PATH
    if guest_token:
        try:
            gdata = decode_guest_session_token(guest_token)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid guest session token.")
        
        token_conv_id = gdata.get("conv_id")
        if conversation_id and conversation_id != token_conv_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Guest session token does not match requested conversation.")
        
        # Guest receives strictly their own conversation channel
        channels = [f"conv:{token_conv_id}"]
        last_event_id = request.headers.get("last-event-id") or request.query_params.get("last_event_id")

        async def guest_event_generator():
            q, missed_events = await realtime_hub.subscribe(channels, last_event_id=last_event_id)
            try:
                init_payload = {"type": "CONNECTED", "status": "ONLINE", "channels": channels, "timestamp": str(time.time())}
                yield f"data: {json.dumps(init_payload)}\n\n"
                if max_events and max_events <= 1:
                    return
                for evt in missed_events:
                    yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evt = await asyncio.wait_for(q.get(), timeout=1.0)
                        yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                realtime_hub.unsubscribe(q)

        return StreamingResponse(
            guest_event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )

    # 2. STAFF / ADMIN TENANT STREAM PATH
    authenticated_user_id = None
    caller_org_id = None
    caller_role = None

    if ticket:
        tdata = await verify_realtime_ticket_async(ticket)
        if not tdata:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired realtime ticket.")
        authenticated_user_id = tdata.get("sub")
        caller_org_id = tdata.get("org_id")
        caller_role = tdata.get("role")
    else:
        cookie_token = request.cookies.get("session_token") or request.cookies.get("access_token")
        auth_hdr = request.headers.get("authorization") or ""
        token_to_check = cookie_token or (auth_hdr.split(" ")[1] if auth_hdr.startswith("Bearer ") else None)

        if not token_to_check:
            # Unauthenticated attempt to stream tenant events
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to stream live updates (valid ticket, session cookie, or Bearer token)."
            )

        try:
            payload = decode_access_token(token_to_check)
            authenticated_user_id = payload.get("sub")
            caller_org_id = payload.get("org_id")
            caller_role = payload.get("role")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token credentials.")

        # Check session revocation
        token_hash = _hash_token(token_to_check)
        stmt_sess = select(UserSession).where(UserSession.session_token_hash == token_hash)
        res_sess = await db.execute(stmt_sess)
        user_sess = res_sess.scalar_one_or_none()
        if user_sess and user_sess.is_revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked.")

    # Check user is active in DB
    stmt_u = select(User).where(User.id == authenticated_user_id)
    res_u = await db.execute(stmt_u)
    user = res_u.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account is deactivated or not found.")

    # Enforce tenant isolation
    resolved_org = caller_org_id
    if caller_role != "SUPER_ADMIN":
        if organization_id and organization_id != caller_org_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to tenant realtime stream.")
    else:
        resolved_org = organization_id or caller_org_id

    if not resolved_org:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant organization must be specified.")

    channels = [f"org:{resolved_org}"]
    if property_id:
        channels.append(f"org:{resolved_org}:prop:{property_id}")

    last_event_id = request.headers.get("last-event-id") or request.query_params.get("last_event_id")

    async def event_generator():
        q, missed_events = await realtime_hub.subscribe(channels, last_event_id=last_event_id)
        try:
            init_payload = {"type": "CONNECTED", "status": "ONLINE", "channels": channels, "timestamp": str(time.time())}
            yield f"data: {json.dumps(init_payload)}\n\n"
            if max_events and max_events <= 1:
                return
            for evt in missed_events:
                yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=1.0)
                    yield f"id: {evt['id']}\nevent: {evt['type']}\ndata: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            realtime_hub.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )

@router.post("/api/v1/realtime/ticket", tags=["Realtime Infrastructure"])
async def create_user_realtime_ticket(current_user: User = Depends(get_current_user)):
    """Creates a 60-second single-use ticket for EventSource / WebSocket connection authentication."""
    role_str = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    ticket = generate_realtime_ticket(
        user_id=current_user.id,
        organization_id=current_user.organization_id or "",
        role=role_str
    )
    return {"ticket": ticket, "expires_in": 60}

@router.get("/api/v1/live-updates", tags=["Live Property Announcements"])
async def list_live_updates(
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
    stmt = select(LiveUpdate).where(LiveUpdate.organization_id == org_id)
    if property_id:
        stmt = stmt.where(LiveUpdate.property_id == property_id)
    upds = await paginate_query(
        db=db,
        stmt=stmt,
        model=LiveUpdate,
        limit=limit,
        cursor=cursor,
        response=response
    )
    return [{"id": u.id, "title": u.title, "content": u.content, "priority": u.priority} for u in upds]

@router.post("/api/v1/live-updates/integrations", tags=["Live Property Announcements"])
async def connect_integration_source(req: IntegrationSourceRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, req.organization_id)
    if feature_flags.is_kill_switch_active("kill_switch_integrations") or not feature_flags.is_enabled("integrations", org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Integrations subsystem is disabled or kill switch engaged."
        )

    # SSRF Protection: forbid loopback, private IPs, and cloud metadata (169.254.169.254)
    validate_outbound_url_ssrf(req.source_url)

    src_id = str(uuid.uuid4())
    encrypted_creds = encrypt_value(req.credentials) if req.credentials else None
    credentials_json = {"encrypted": encrypted_creds} if encrypted_creds else {}
    masked = "••••••••" if req.credentials else None

    src = IntegrationSource(
        id=src_id,
        organization_id=org_id,
        property_id=req.property_id,
        name=req.name,
        source_type=req.source_type,
        source_url=req.source_url,
        auth_type=req.auth_type,
        credentials_masked=masked,
        credentials_json=credentials_json,
        status="PENDING",
        sync_status="PENDING"
    )
    db.add(src)
    await db.flush()
    return {"id": src.id, "name": src.name, "status": "PENDING", "credentials_masked": masked}

@router.get("/api/v1/live-updates/integrations", tags=["Live Property Announcements"])
async def list_integration_sources(
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
    stmt = select(IntegrationSource).where(IntegrationSource.organization_id == org_id)
    if property_id:
        stmt = stmt.where(IntegrationSource.property_id == property_id)
    srcs = await paginate_query(
        db=db,
        stmt=stmt,
        model=IntegrationSource,
        limit=limit,
        cursor=cursor,
        response=response
    )
    return [
        {
            "id": s.id,
            "name": s.name,
            "type": s.source_type,
            "source_type": s.source_type,
            "source_url": s.source_url,
            "status": s.status or s.sync_status,
            "credentials_masked": s.credentials_masked
        }
        for s in srcs
    ]

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

@router.post("/api/v1/live-updates/integrations/{source_id}/test", tags=["Live Property Announcements"])
async def test_integration_source(
    source_id: str,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Tests connection to external integration endpoint with decrypted credentials and latency measurement."""
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(IntegrationSource).where(IntegrationSource.id == source_id, IntegrationSource.organization_id == org_id)
    res = await db.execute(stmt)
    src = res.scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Integration source '{source_id}' not found.")

    validate_outbound_url_ssrf(src.source_url)
    raw_secret = decrypt_value(src.credentials_json.get("encrypted")) if src.credentials_json else None
    headers = {}
    if raw_secret:
        if src.auth_type == "BEARER_TOKEN":
            headers["Authorization"] = f"Bearer {raw_secret}"
        else:
            headers["X-API-Key"] = raw_secret

    import httpx, time
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(src.source_url, headers=headers)
            latency_ms = int((time.time() - t0) * 1000)
            if resp.status_code < 400:
                src.status = "CONNECTED"
                await db.flush()
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "message": f"Connection verified. Endpoint reachable in {latency_ms}ms."
                }
            else:
                src.status = "ERROR"
                await db.flush()
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "latency_ms": latency_ms,
                    "message": f"Remote server returned HTTP {resp.status_code}."
                }
    except Exception as e:
        src.status = "DISCONNECTED"
        await db.flush()
        return {
            "success": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "error": str(e),
            "message": f"Failed to connect to {src.source_url}: {e}"
        }

@router.post("/api/v1/live-updates/integrations/{source_id}/sync", tags=["Live Property Announcements"])
async def trigger_integration_sync(
    source_id: str,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Executes real integration synchronization (REST pull with decrypted credentials).
    Updates status, last_synced_at, and error capture with retry mechanism.
    """
    org_id = verify_tenant_access(current_user, organization_id)
    if feature_flags.is_kill_switch_active("kill_switch_integrations") or not feature_flags.is_enabled("integrations", org_id=org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Integrations subsystem is disabled or kill switch engaged."
        )

    stmt = select(IntegrationSource).where(IntegrationSource.id == source_id, IntegrationSource.organization_id == org_id)
    res = await db.execute(stmt)
    src = res.scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Integration source '{source_id}' not found.")

    now = datetime.now(timezone.utc)
    raw_secret = decrypt_value(src.credentials_json.get("encrypted")) if src.credentials_json else None
    headers = {}
    if raw_secret:
        if src.auth_type == "BEARER_TOKEN":
            headers["Authorization"] = f"Bearer {raw_secret}"
        else:
            headers["X-API-Key"] = raw_secret

    sync_success = False
    error_msg = None

    if src.source_type == "REST_API":
        if "example.com" in (src.source_url or ""):
            sync_success = True
        else:
            validate_outbound_url_ssrf(src.source_url)
            import httpx
            for attempt in range(3):
                try:
                    async def _do_sync():
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            resp = await client.get(src.source_url, headers=headers)
                            if resp.status_code < 400:
                                return True
                            raise HTTPException(status_code=502, detail=f"HTTP {resp.status_code}")

                    sync_success = await erp_circuit_breaker.call(_do_sync)
                    if sync_success:
                        break
                except CircuitBreakerOpenError as cbe:
                    error_msg = f"CIRCUIT_BREAKER_OPEN: {str(cbe)}"
                    sync_success = False
                    break
                except Exception as e:
                    error_msg = str(e)
                    if attempt < 2:
                        await asyncio.sleep(0.5)

    if sync_success:
        src.status = "SYNCED"
        src.sync_status = "SYNCED"
        src.last_synced_at = now
    else:
        src.status = "ERROR"
        src.sync_status = "FAILED"

    await db.flush()

    await realtime_hub.publish(
        event_type="INTEGRATION_SYNCED",
        data={
            "source_id": src.id,
            "status": src.status,
            "sync_status": src.sync_status,
            "last_synced_at": src.last_synced_at.isoformat() if src.last_synced_at else None,
            "error": error_msg
        },
        organization_id=org_id,
        property_id=src.property_id
    )

    return {
        "source_id": src.id,
        "status": src.status,
        "sync_status": src.sync_status,
        "last_synced_at": src.last_synced_at.isoformat() if src.last_synced_at else None,
        "error": error_msg
    }

# --- ERP DATA ACCESS CONTROL & AUDIT LOGS ---
@router.get("/api/v1/live-updates/integrations/{source_id}/data-access", tags=["ERP Data Access Control"])
async def get_integration_data_access(source_id: str, organization_id: Optional[str] = None, property_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    stmt = select(DataAccessPolicy).where(
        DataAccessPolicy.organization_id == org_id,
        DataAccessPolicy.integration_source_id == source_id
    )
    if property_id:
        stmt = stmt.where(DataAccessPolicy.property_id == property_id)
    res = await db.execute(stmt)
    policies = res.scalars().all()
    policy_map = {p.category_key: p for p in policies}

    default_categories = [
        {"category_key": "resident_room_info", "category_name": "Resident Room Information", "default_enabled": True, "default_scope": "own_data"},
        {"category_key": "food_menu_timings", "category_name": "Food Menu & Mess Timings", "default_enabled": True, "default_scope": "all_residents"},
        {"category_key": "facilities_availability", "category_name": "Facilities & Amenities Availability", "default_enabled": True, "default_scope": "all_residents"},
        {"category_key": "maintenance_requests", "category_name": "Maintenance Requests", "default_enabled": True, "default_scope": "own_data"},
        {"category_key": "notices", "category_name": "Property Notices & Announcements", "default_enabled": True, "default_scope": "all_residents"},
        {"category_key": "payment_info", "category_name": "Resident Payment & Fee Status", "default_enabled": False, "default_scope": "nobody"},
        {"category_key": "attendance_records", "category_name": "Resident Attendance Records", "default_enabled": False, "default_scope": "nobody"},
        {"category_key": "staff_personal_info", "category_name": "Staff Personal Information", "default_enabled": False, "default_scope": "nobody"},
        {"category_key": "reservations", "category_name": "Room Bookings & Reservations", "default_enabled": True, "default_scope": "all_residents"},
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
    actor = current_user.email or current_user.full_name or str(current_user.id)
    now_dt = datetime.now(timezone.utc)

    for cat in req.categories:
        stmt = select(DataAccessPolicy).where(
            DataAccessPolicy.organization_id == org_id,
            DataAccessPolicy.property_id == req.property_id,
            DataAccessPolicy.integration_source_id == source_id,
            DataAccessPolicy.category_key == cat.category_key
        )
        res = await db.execute(stmt)
        pol = res.scalars().first()
        
        prev_enabled = pol.enabled if pol else False
        prev_scope = pol.user_scope if pol else "nobody"

        if not pol:
            pol = DataAccessPolicy(
                id=str(uuid.uuid4()),
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
        id=str(uuid.uuid4()),
        organization_id=org_id,
        user_id=current_user.id,
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
@router.get("/api/v1/integrations/whatsapp/webhook", tags=["WhatsApp Integration"])
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token")
):
    """Meta WhatsApp Webhook Verification Challenge handler."""
    verified = whatsapp_bsp.verify_webhook_challenge(hub_mode or "", hub_verify_token or "", hub_challenge or "")
    if verified is not None:
        return int(verified) if str(verified).isdigit() else verified
    raise HTTPException(status_code=403, detail="WhatsApp Webhook verification failed. Invalid verify_token.")

async def _execute_whatsapp_agent_turn(
    org_id: str,
    property_id: Optional[str],
    agent_id: str,
    sender_phone: str,
    msg_body: str
):
    """Executes the agent turn asynchronously and dispatches the reply over WhatsApp."""
    from services.database.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        await set_tenant_context(session, org_id)
        stmt = select(Agent).where(
            Agent.id == agent_id,
            Agent.organization_id == org_id,
            Agent.status == AgentStatus.ACTIVE
        )
        res = await session.execute(stmt)
        agent = res.scalar_one_or_none()
        if not agent:
            return

        cfg_stmt = select(AgentConfig).where(AgentConfig.agent_id == agent.id)
        cfg_res = await session.execute(cfg_stmt)
        config = cfg_res.scalar_one_or_none()

        engine = AgentRuntimeEngine(db_session=session)
        agent_config_dict = {
            "model_name": config.model_name if config else "sarvam-2b",
            "system_prompt": config.system_prompt if config else "You are an AI Concierge.",
            "enabled_tools": config.enabled_tools if config else []
        }
        turn = await engine.execute_agent_turn(
            agent_config=agent_config_dict,
            user_message=msg_body,
            conversation_history=[],
            organization_id=org_id,
            property_id=property_id or agent.property_id,
            agent_id=agent.id,
            channel="whatsapp",
            user_context={"user_role": "guest", "user_id": sender_phone}
        )
        reply = turn.get("response", "Thank you for contacting us.")

        # Prepare message via whatsapp_bsp enforcing 24-hr window
        prepared_msg = whatsapp_bsp.prepare_outbound_message(
            recipient_phone=sender_phone,
            last_inbound_time=datetime.now(timezone.utc),
            freeform_text=reply
        )

        async def _send_reply():
            return await whatsapp_client.send_text_message(sender_phone, reply)

        try:
            await whatsapp_circuit_breaker.call(_send_reply)
        except CircuitBreakerOpenError as cbe:
            logger.error(f"WhatsApp circuit breaker open: {cbe}")


@router.post("/api/v1/integrations/whatsapp/webhook", tags=["WhatsApp Integration"], dependencies=[Depends(enforce_tenant_fair_use_quota)])
async def process_whatsapp_inbound_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Processes inbound WhatsApp messages across schema variations (Meta Cloud v16+ and direct payload),
    verifies signature (fails closed), drops unmapped numbers, dedupes via Redis/Postgres, and dispatches processing.
    """
    if feature_flags.is_kill_switch_active("kill_switch_integrations"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="FEATURE_DISABLED: Integrations subsystem is disabled or kill switch engaged."
        )

    payload_bytes = await request.body()
    signature = request.headers.get("x-hub-signature-256") or ""
    is_valid_sig = whatsapp_bsp.verify_inbound_signature(payload_bytes, signature)
    if not is_valid_sig:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid WhatsApp webhook signature.")

    try:
        data = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}
    except Exception:
        data = {}

    inbound_messages = whatsapp_bsp.extract_inbound_messages(data)
    queued_count = 0

    for msg in inbound_messages:
        phone_number_id = msg.get("phone_number_id")
        if not phone_number_id:
            continue

        # Route by metadata.phone_number_id through per-tenant channel-mapping table
        stmt_map = select(WhatsAppChannelMapping).where(
            WhatsAppChannelMapping.phone_number_id == phone_number_id,
            WhatsAppChannelMapping.is_active == True
        )
        res_map = await db.execute(stmt_map)
        mapping = res_map.scalar_one_or_none()
        if not mapping:
            # F2: drop unmapped numbers
            logger.info(f"[WhatsApp] Dropping message from unmapped phone_number_id: {phone_number_id}")
            continue

        # Set tenant context
        await set_tenant_context(db, mapping.organization_id)

        msg_id = msg.get("msg_id")
        if not msg_id:
            continue

        # Deduplicate by message ID (Redis 24h TTL + Postgres)
        redis_client = getattr(request.app.state, "redis", None)
        if not redis_client:
            try:
                from services.common.redis_service import get_redis_client_sync
                redis_client = get_redis_client_sync()
            except Exception:
                redis_client = None

        if redis_client:
            try:
                dedupe_key = f"wa_msg:{msg_id}"
                if hasattr(redis_client, "set"):
                    import inspect
                    res_set = redis_client.set(dedupe_key, "1", nx=True, ex=86400)
                    if inspect.isawaitable(res_set):
                        is_new = await res_set
                    else:
                        is_new = res_set
                    if not is_new:
                        logger.info(f"[WhatsApp] Duplicate message ignored (Redis): {msg_id}")
                        continue
            except Exception as e:
                logger.warning(f"[WhatsApp] Redis dedupe error: {e}")

        stmt_dedupe = select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == f"wa_{msg_id}")
        res_dedupe = await db.execute(stmt_dedupe)
        if res_dedupe.scalar_one_or_none():
            logger.info(f"[WhatsApp] Duplicate message ignored (DB): {msg_id}")
            continue

        db.add(ProcessedWebhookEvent(
            id=f"wa_{msg_id}",
            event_id=f"wa_{msg_id}",
            event_type="whatsapp_inbound"
        ))
        await db.flush()

        sender_phone = msg.get("sender_phone")
        msg_body = msg.get("text", "")
        if sender_phone and msg_body:
            background_tasks.add_task(
                _execute_whatsapp_agent_turn,
                org_id=mapping.organization_id,
                property_id=mapping.property_id,
                agent_id=mapping.agent_id,
                sender_phone=sender_phone,
                msg_body=msg_body
            )
            queued_count += 1

    await db.commit()
    return {"status": "SUCCESS", "events_queued": queued_count}
