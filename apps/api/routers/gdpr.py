import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import (
    User, Organization, Conversation, Message, SupportTicket,
    Reservation, AuditLog
)
from services.database.audit import record_audit_log_async, verify_audit_log_chain
from apps.api.auth import get_current_user, require_permission

router = APIRouter(prefix="/api/v1/compliance", tags=["GDPR, DPDP & Compliance"])

class DataSubjectExportRequest(BaseModel):
    guest_identifier: str  # email or phone

class DataSubjectErasureRequest(BaseModel):
    guest_identifier: str
    confirmation: bool = True

class ConsentRecordRequest(BaseModel):
    guest_identifier: str
    purpose: str = "AI Concierge Services and Booking Management"
    consent_given: bool = True

SUBPROCESSORS_LIST = [
    {
        "name": "Amazon Web Services (AWS)",
        "purpose": "Cloud Hosting, KMS Envelope Encryption, PostgreSQL RDS",
        "data_location": "Pinned by Tenant Data Residency (US / EU / IN)",
        "dpa_executed": True
    },
    {
        "name": "OpenAI / Anthropic",
        "purpose": "LLM Inference (Zero-Retention Mode)",
        "data_location": "US / EU",
        "dpa_executed": True
    },
    {
        "name": "Stripe, Inc.",
        "purpose": "Payment Processing & SaaS Billing",
        "data_location": "Global / PCI DSS Level 1",
        "dpa_executed": True
    },
    {
        "name": "Redis Labs",
        "purpose": "In-Memory Caching & Session Token Store",
        "data_location": "Pinned by Tenant Data Residency",
        "dpa_executed": True
    },
    {
        "name": "Twilio / Meta WhatsApp",
        "purpose": "Omnichannel Messaging & Telephony Gateway",
        "data_location": "Global",
        "dpa_executed": True
    }
]

@router.get("/subprocessors")
async def list_subprocessors(
    current_user: User = Depends(get_current_user)
):
    """Returns active sub-processor registry with executed Data Processing Addendums (DPAs)."""
    return {
        "status": "active",
        "dpa_version": "2026.1-enterprise",
        "subprocessors": SUBPROCESSORS_LIST
    }

@router.post("/consent")
async def record_data_subject_consent(
    req: ConsentRecordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Records verifiable consent under GDPR Article 7 / India DPDP Act 2023."""
    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="CONSENT_RECORDED",
        target_type="guest",
        target_id=req.guest_identifier,
        details={
            "purpose": req.purpose,
            "consent_given": req.consent_given,
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        db=db
    )
    return {
        "message": f"Consent successfully registered for data subject '{req.guest_identifier}'.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@router.post("/export")
async def export_data_subject_records(
    req: DataSubjectExportRequest,
    current_user: User = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db)
):
    """GDPR Article 15 Data Subject Access Request (DSAR) machine-readable export."""
    org_id = current_user.organization_id
    ident = req.guest_identifier.strip()

    # 1. Fetch Conversations matching guest identifier
    stmt_conv = select(Conversation).where(
        Conversation.organization_id == org_id,
        Conversation.channel_user_id == ident
    )
    res_conv = await db.execute(stmt_conv)
    convs = res_conv.scalars().all()
    conv_ids = [c.id for c in convs]

    # 2. Fetch Messages
    messages = []
    if conv_ids:
        stmt_msg = select(Message).where(Message.conversation_id.in_(conv_ids))
        res_msg = await db.execute(stmt_msg)
        messages = res_msg.scalars().all()

    # 3. Fetch Support Tickets
    tickets = []
    if conv_ids:
        stmt_tickets = select(SupportTicket).where(
            SupportTicket.organization_id == org_id,
            SupportTicket.conversation_id.in_(conv_ids)
        )
        res_tickets = await db.execute(stmt_tickets)
        tickets = res_tickets.scalars().all()

    # 4. Fetch Reservations
    stmt_resv = select(Reservation).where(
        Reservation.organization_id == org_id,
        Reservation.customer_email == ident
    )
    res_resv = await db.execute(stmt_resv)
    reservations = res_resv.scalars().all()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="DATA_SUBJECT_EXPORT_EXECUTED",
        target_type="guest",
        target_id=ident,
        details={"record_count": len(convs) + len(messages) + len(tickets) + len(reservations)},
        db=db
    )

    return {
        "export_metadata": {
            "organization_id": org_id,
            "guest_identifier": ident,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": "JSON-DSAR-v2"
        },
        "conversations": [{"id": c.id, "channel": c.channel, "created_at": c.created_at} for c in convs],
        "messages": [{"id": m.id, "sender_type": m.sender_type, "content": m.content, "created_at": m.created_at} for m in messages],
        "support_tickets": [{"id": t.id, "issue_summary": t.issue_summary, "status": t.status} for t in tickets],
        "reservations": [{"id": r.id, "customer_name": r.customer_name, "check_in": r.check_in} for r in reservations]
    }

@router.post("/erase")
async def erase_data_subject_records(
    req: DataSubjectErasureRequest,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """GDPR Article 17 Right to Erasure ('Right to be Forgotten')."""
    if not req.confirmation:
        raise HTTPException(status_code=400, detail="Confirmation required to execute irreversible erasure.")

    org_id = current_user.organization_id
    ident = req.guest_identifier.strip()

    # 1. Anonymize/erase conversations
    stmt_conv = select(Conversation).where(
        Conversation.organization_id == org_id,
        Conversation.channel_user_id == ident
    )
    res_conv = await db.execute(stmt_conv)
    convs = res_conv.scalars().all()
    conv_ids = [c.id for c in convs]

    if conv_ids:
        # Delete messages and support tickets
        stmt_del_msg = delete(Message).where(Message.conversation_id.in_(conv_ids))
        await db.execute(stmt_del_msg)
        stmt_del_tick = delete(SupportTicket).where(SupportTicket.conversation_id.in_(conv_ids))
        await db.execute(stmt_del_tick)
        stmt_del_conv = delete(Conversation).where(Conversation.id.in_(conv_ids))
        await db.execute(stmt_del_conv)

    # 2. Anonymize reservations (preserving revenue numbers, removing PII)
    stmt_resv = (
        update(Reservation)
        .where(
            Reservation.organization_id == org_id,
            Reservation.customer_email == ident
        )
        .values(
            customer_name="[ERASED GUEST]",
            customer_email="erased@compliance.invalid"
        )
    )
    await db.execute(stmt_resv)

    await db.flush()

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="DATA_SUBJECT_ERASURE_EXECUTED",
        target_type="guest",
        target_id=ident,
        details={"status": "erased_and_anonymized"},
        db=db
    )

    return {
        "status": "success",
        "message": f"Personal data associated with '{ident}' has been permanently deleted or anonymized."
    }

@router.get("/audit-logs/export")
async def export_audit_logs_to_siem(
    current_user: User = Depends(require_permission("audit:read")),
    db: AsyncSession = Depends(get_db)
):
    """Streams verified append-only audit trail for customer SIEM integration (Splunk, Datadog, S3)."""
    org_id = current_user.organization_id

    # Cryptographically verify the hash chain before exporting
    is_valid, count, err = await verify_audit_log_chain(org_id=org_id, db=db)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"AUDIT_CHAIN_INTEGRITY_FAILURE: Tampering detected: {err}"
        )

    stmt = select(AuditLog).where(AuditLog.organization_id == org_id).order_by(AuditLog.created_at.asc())
    res = await db.execute(stmt)
    entries = res.scalars().all()

    jsonl_lines = []
    for e in entries:
        jsonl_lines.append(json.dumps({
            "id": e.id,
            "organization_id": e.organization_id,
            "user_id": e.user_id,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "details": e.details_json,
            "prev_hash": e.prev_hash,
            "hash": e.hash,
            "created_at": e.created_at.isoformat() if e.created_at else None
        }))

    output_content = "\n".join(jsonl_lines)
    return Response(
        content=output_content,
        media_type="application/x-ndjson",
        headers={
            "X-Audit-Chain-Verified": "true",
            "X-Verified-Record-Count": str(count),
            "Content-Disposition": f"attachment; filename=audit-export-{org_id}.jsonl"
        }
    )

@router.post("/organizations/{org_id}/export-bundle")
async def export_tenant_bundle(
    org_id: str,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Generates complete data export bundle for tenant offboarding or regulatory audit."""
    if current_user.organization_id != org_id and current_user.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Forbidden: Cannot export another organization's data.")

    from services.operations.tenant_export import generate_tenant_export_bundle
    bundle = await generate_tenant_export_bundle(org_id=org_id, db=db)

    await record_audit_log_async(
        org_id=org_id,
        user_id=current_user.id,
        action="TENANT_EXPORT_BUNDLE_GENERATED",
        target_type="organization",
        target_id=org_id,
        details={"sha256_checksum": bundle["export_metadata"]["sha256_checksum"]},
        db=db
    )
    return bundle


class RetentionPurgeRequest(BaseModel):
    retention_days: Optional[int] = 90
    legal_hold: bool = False

@router.post("/retention/purge")
async def execute_retention_purge_endpoint(
    req: RetentionPurgeRequest,
    organization_id: Optional[str] = None,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Executes audited data retention purge honoring legal hold and recording cryptographic erasure proof."""
    target_org = organization_id or current_user.organization_id
    if current_user.organization_id != target_org and current_user.role != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Forbidden: Cannot purge another organization's data.")

    from services.compliance.retention_purger import retention_purger
    res = await retention_purger.execute_retention_purge(
        db=db,
        org_id=target_org,
        retention_days=req.retention_days,
        legal_hold=req.legal_hold
    )
    await db.commit()
    return res
