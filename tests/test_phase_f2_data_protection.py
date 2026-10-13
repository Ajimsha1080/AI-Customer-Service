import os
import uuid
import json
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from apps.api.main import app
from apps.api.config import settings
from services.database.models import User, Organization, UserRole, Conversation, Message, AuditLog
from apps.api.auth import create_access_token
from services.security.encryption import encryption_service
from services.security.pii_masker import pii_engine
from services.security.data_residency import data_residency_router
from services.compliance.retention_purger import retention_purger
from services.database.audit import record_audit_log_async, verify_audit_log_chain
from scripts.backup_restore_drill import run_backup_restore_drill

client = TestClient(app, base_url="http://testserver")

def test_kms_envelope_encryption_byok_and_rotation():
    """F2.1 KMS-backed envelope encryption, AES-256-GCM, tenant BYOK, and key rotation."""
    secret_text = "Guest Passport: P12345678, VIP Room 402 Key: master-secret-8877"
    
    # 1. Standard envelope encryption
    envelope = encryption_service.encrypt(secret_text)
    assert envelope.startswith("env:")
    assert secret_text not in envelope  # Ciphertext hides plaintext completely

    decrypted = encryption_service.decrypt(envelope)
    assert decrypted == secret_text

    # 2. Per-Tenant Bring-Your-Own-Key (BYOK) for Enterprise tier
    test_org_id = f"org_byok_{uuid.uuid4().hex[:8]}"
    tenant_custom_kek_hex = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    encryption_service.register_tenant_byok(test_org_id, tenant_custom_kek_hex)

    byok_envelope = encryption_service.encrypt(secret_text, org_id=test_org_id)
    assert byok_envelope.startswith("env:")

    # Decrypting with correct BYOK succeeds
    byok_decrypted = encryption_service.decrypt(byok_envelope, org_id=test_org_id)
    assert byok_decrypted == secret_text

    # Decrypting without tenant BYOK (using platform default KEK) fails
    with pytest.raises(Exception):
        encryption_service.decrypt(byok_envelope, org_id="different_org")

    # 3. Key Rotation Procedure
    new_org_id = f"org_rotated_{uuid.uuid4().hex[:8]}"
    new_kek_hex = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
    encryption_service.register_tenant_byok(new_org_id, new_kek_hex)

    rotated_envelope = encryption_service.rotate_envelope(
        byok_envelope,
        old_org_id=test_org_id,
        new_org_id=new_org_id
    )
    assert rotated_envelope.startswith("env:")
    assert encryption_service.decrypt(rotated_envelope, org_id=new_org_id) == secret_text

def test_pii_redaction_and_model_provider_zero_retention():
    """F2.2 Redact PII in prompts/logs, mask transcripts, provider allowlist, zero retention flags."""
    raw_text = (
        "Hello, my email is john.doe@luxuryresort.com and phone is +1-555-839-2819. "
        "Credit card: 4111-2222-3333-4444. API key: sk-live-99887766554433221100."
    )

    # 1. Strict redaction
    redacted = pii_engine.redact_pii(raw_text, mode="redact")
    assert "[REDACTED_EMAIL]" in redacted
    assert "john.doe@luxuryresort.com" not in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "555-839-2819" not in redacted
    assert "[REDACTED_CARD]" in redacted
    assert "4111-2222-3333-4444" not in redacted
    assert "[REDACTED_SECRET]" in redacted
    assert "sk-live" not in redacted

    # 2. Masking mode (for transcripts)
    masked = pii_engine.redact_pii(raw_text, mode="mask")
    assert "j***e@luxuryresort.com" in masked
    assert "***-***-2819" in masked

    # 3. Model provider allowlist
    allowed = pii_engine.check_provider_allowed("OPENAI", org_allowed_providers=["OPENAI", "ANTHROPIC"])
    assert allowed is True
    blocked = pii_engine.check_provider_allowed("UNKNOWN_MODEL_HOST", org_allowed_providers=["OPENAI"])
    assert blocked is False

    # 4. Zero-retention compliance flags
    headers = pii_engine.get_zero_retention_headers()
    assert headers["X-Zero-Data-Retention"] == "true"
    assert headers["X-Enterprise-Privacy-Mode"] == "strict"

def test_tenant_data_residency_boundary_enforcement():
    """F2.3 Tenant legal region pinning (EU / IN / US) and cross-border transfer block."""
    eu_cfg = data_residency_router.get_region_config("EU")
    assert "eu-central-1" in eu_cfg["db_cluster"]
    assert "eu.api.anthropic.com" in eu_cfg["llm_endpoint"]

    us_cfg = data_residency_router.get_region_config("US")
    assert "us-east-1" in us_cfg["db_cluster"]

    in_cfg = data_residency_router.get_region_config("IN")
    assert "ap-south-1" in in_cfg["db_cluster"]

    # In-region call passes
    assert data_residency_router.validate_regional_call("EU", "EU") is True

    # Cross-border call (EU tenant data routed to US infrastructure) raises 403 violation
    with pytest.raises(Exception) as exc_info:
        data_residency_router.validate_regional_call("EU", "US")
    assert "DATA_RESIDENCY_VIOLATION" in str(exc_info.value)

@pytest.mark.asyncio
async def test_retention_purger_job_and_legal_hold(db_session):
    """F2.4 Scheduled retention purge, deleted records, legal hold protection, and cryptographic erasure proof."""
    org_id = f"org_ret_{uuid.uuid4().hex[:8]}"
    org = Organization(id=org_id, name="Retention Org", slug=f"ret-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    # Create old expired conversation (120 days ago)
    old_time = datetime.now(timezone.utc) - timedelta(days=120)
    old_conv = Conversation(
        id=f"conv_old_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        property_id="prop_azure_palm_resort",
        agent_id="agt_hostel_01",
        channel="WEB",
        created_at=old_time
    )
    db_session.add(old_conv)
    await db_session.flush()

    old_msg = Message(
        id=f"msg_old_{uuid.uuid4().hex[:6]}",
        conversation_id=old_conv.id,
        sender_type="GUEST",
        content="Old chat history from 120 days ago",
        created_at=old_time
    )
    db_session.add(old_msg)
    await db_session.commit()

    # Case 1: Legal Hold Active -> Purge is skipped, records preserved
    skipped_res = await retention_purger.execute_retention_purge(
        db=db_session,
        org_id=org_id,
        retention_days=90,
        legal_hold=True
    )
    assert skipped_res["status"] == "skipped"
    assert skipped_res["reason"] == "LEGAL_HOLD_ACTIVE"

    # Verify conversation still exists
    stmt_check = select(Conversation).where(Conversation.id == old_conv.id)
    res_check = await db_session.execute(stmt_check)
    assert res_check.scalar_one_or_none() is not None

    # Case 2: Legal Hold Lifted -> Expired records permanently purged
    purged_res = await retention_purger.execute_retention_purge(
        db=db_session,
        org_id=org_id,
        retention_days=90,
        legal_hold=False
    )
    assert purged_res["status"] == "completed"
    assert purged_res["purged_conversations"] >= 1
    assert "erasure_proof_hash" in purged_res

    # Verify conversation is deleted
    res_after = await db_session.execute(stmt_check)
    assert res_after.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_immutable_hash_chained_audit_log_and_tamper_detection(db_session):
    """F2.6 Append-only SHA-256 hash-chained audit log with tamper detection."""
    org_id = f"org_audit_{uuid.uuid4().hex[:8]}"

    # Record 3 sequential audit entries
    e1 = await record_audit_log_async(org_id=org_id, action="USER_LOGIN", target_type="user", target_id="u1", db=db_session)
    e2 = await record_audit_log_async(org_id=org_id, action="CONFIG_CHANGE", target_type="org", target_id=org_id, db=db_session)
    e3 = await record_audit_log_async(org_id=org_id, action="DATA_EXPORT", target_type="guest", target_id="g1", db=db_session)
    await db_session.commit()

    # Chain links must match previous entry's hash
    assert e2.prev_hash == e1.hash
    assert e3.prev_hash == e2.hash

    # Verify intact chain
    is_valid, count, err = await verify_audit_log_chain(org_id=org_id, db=db_session)
    assert is_valid is True
    assert count == 3
    assert err is None

    # Simulate malicious DB tampering: alter action in entry 2
    stmt_tamper = update(AuditLog).where(AuditLog.id == e2.id).values(action="TAMPERED_ACTION")
    await db_session.execute(stmt_tamper)
    await db_session.commit()

    # Re-verify chain -> Tampering must be immediately caught
    tampered_valid, tampered_idx, err_msg = await verify_audit_log_chain(org_id=org_id, db=db_session)
    assert tampered_valid is False
    assert "Tampered entry detected" in err_msg

@pytest.mark.asyncio
async def test_gdpr_dsar_export_erasure_consent_and_siem(db_session):
    """F2.5 GDPR Article 15 DSAR export, Article 17 erasure, consent tracking, sub-processors, and SIEM."""
    # Register org
    email = f"gdpr_{uuid.uuid4().hex[:8]}@enterprise.test"
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "StrongPassword_GDPR_2026!",
        "full_name": "GDPR Admin"
    })
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    org_id = reg.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {token}"}

    guest_email = f"guest_{uuid.uuid4().hex[:8]}@guest.com"

    # 1. Record Consent
    c_res = client.post("/api/v1/compliance/consent", headers=headers, json={
        "guest_identifier": guest_email,
        "purpose": "Hospitality Concierge"
    })
    assert c_res.status_code == 200

    # 2. Sub-processor registry
    sub_res = client.get("/api/v1/compliance/subprocessors", headers=headers)
    assert sub_res.status_code == 200
    assert len(sub_res.json()["subprocessors"]) >= 4

    # 3. Create guest conversation
    conv = Conversation(
        id=f"conv_gdpr_{uuid.uuid4().hex[:6]}",
        organization_id=org_id,
        property_id="prop_azure_palm_resort",
        agent_id="agt_hostel_01",
        channel_user_id=guest_email,
        channel="WEB"
    )
    db_session.add(conv)
    await db_session.commit()

    msg = Message(
        id=f"msg_gdpr_{uuid.uuid4().hex[:6]}",
        conversation_id=conv.id,
        sender_type="GUEST",
        content="Please reserve dinner table tonight."
    )
    db_session.add(msg)
    await db_session.commit()

    # 4. Data Subject Export (DSAR)
    exp_res = client.post("/api/v1/compliance/export", headers=headers, json={
        "guest_identifier": guest_email
    })
    assert exp_res.status_code == 200
    exp_data = exp_res.json()
    assert len(exp_data["conversations"]) >= 1
    assert len(exp_data["messages"]) >= 1

    # 5. Right to Erasure
    erase_res = client.post("/api/v1/compliance/erase", headers=headers, json={
        "guest_identifier": guest_email,
        "confirmation": True
    })
    assert erase_res.status_code == 200

    # Verify conversation was deleted
    exp_res2 = client.post("/api/v1/compliance/export", headers=headers, json={
        "guest_identifier": guest_email
    })
    assert len(exp_res2.json()["conversations"]) == 0

    # 6. SIEM Export with verified hash chain
    siem_res = client.get("/api/v1/compliance/audit-logs/export", headers=headers)
    assert siem_res.status_code == 200
    assert siem_res.headers.get("X-Audit-Chain-Verified") == "true"
    assert "DATA_SUBJECT_ERASURE_EXECUTED" in siem_res.text

def test_disaster_recovery_backup_and_restore_drill():
    """F2.7 Scripted backup snapshot, AES-256-GCM encryption, cross-region replication, and PITR restore drill."""
    report = run_backup_restore_drill()
    assert report["status"] == "DRILL_PASSED"
    assert report["checksum_match"] is True
    assert report["integrity_check"] == "ok"
    assert report["measured_rto_seconds"] >= 0.0
    assert report["measured_rpo_seconds"] == 0.0
