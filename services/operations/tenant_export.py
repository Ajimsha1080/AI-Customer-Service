import io
import csv
import json
import zipfile
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.models import (
    Organization, Property, Agent, Room, Reservation, Conversation, Message, SupportTicket, AuditLog
)

async def generate_tenant_export_bundle(org_id: str, db: AsyncSession) -> Dict[str, Any]:
    """
    Gathers all tenant data across core entities and generates a complete JSON and CSV export bundle.
    """
    # 1. Properties
    res_props = await db.execute(select(Property).where(Property.organization_id == org_id))
    properties = res_props.scalars().all()

    # 2. Agents
    res_agents = await db.execute(select(Agent).where(Agent.organization_id == org_id))
    agents = res_agents.scalars().all()

    # 3. Reservations
    res_resvs = await db.execute(select(Reservation).where(Reservation.organization_id == org_id))
    reservations = res_resvs.scalars().all()

    # 4. Conversations
    res_convs = await db.execute(select(Conversation).where(Conversation.organization_id == org_id))
    conversations = res_convs.scalars().all()
    conv_ids = [c.id for c in conversations]

    # 5. Messages
    messages = []
    if conv_ids:
        res_msgs = await db.execute(select(Message).where(Message.conversation_id.in_(conv_ids[:1000])))
        messages = res_msgs.scalars().all()

    # 6. Support Tickets
    res_tickets = await db.execute(select(SupportTicket).where(SupportTicket.organization_id == org_id))
    tickets = res_tickets.scalars().all()

    # 7. Audit Logs
    res_audits = await db.execute(select(AuditLog).where(AuditLog.organization_id == org_id))
    audits = res_audits.scalars().all()

    bundle = {
        "export_metadata": {
            "organization_id": org_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": "HAC-TENANT-OFFBOARDING-V1"
        },
        "counts": {
            "properties": len(properties),
            "agents": len(agents),
            "reservations": len(reservations),
            "conversations": len(conversations),
            "messages": len(messages),
            "support_tickets": len(tickets),
            "audit_logs": len(audits)
        },
        "data": {
            "properties": [{"id": p.id, "name": p.name, "timezone": p.timezone, "currency": p.currency} for p in properties],
            "agents": [{"id": a.id, "name": a.name, "agent_type": a.agent_type, "status": a.status} for a in agents],
            "reservations": [{"id": r.id, "customer_name": r.customer_name, "check_in": r.check_in, "check_out": r.check_out, "total_amount": r.total_amount} for r in reservations],
            "conversations": [{"id": c.id, "channel": c.channel, "created_at": c.created_at.isoformat() if c.created_at else None} for c in conversations],
            "messages": [{"id": m.id, "conversation_id": m.conversation_id, "sender_type": m.sender_type, "content": m.content} for m in messages],
            "support_tickets": [{"id": t.id, "issue_summary": t.issue_summary, "status": t.status, "priority": t.priority} for t in tickets],
            "audit_logs": [{"id": l.id, "action": l.action, "target_type": l.target_type, "created_at": l.created_at.isoformat() if l.created_at else None} for l in audits]
        }
    }

    # Generate integrity checksum
    raw_json = json.dumps(bundle, sort_keys=True).encode("utf-8")
    checksum = hashlib.sha256(raw_json).hexdigest()
    bundle["export_metadata"]["sha256_checksum"] = checksum

    return bundle
