"""add whatsapp channel mappings table

Revision ID: f1a2b3c4d5e6
Revises: e1f2a3b4c5d6
Create Date: 2026-11-26 01:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    if "whatsapp_channel_mappings" not in tables:
        op.create_table(
            "whatsapp_channel_mappings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("phone_number_id", sa.String(64), nullable=False, unique=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("property_id", sa.String(36), sa.ForeignKey("properties.id", ondelete="CASCADE"), nullable=True),
            sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
        )
        op.create_index("ix_wa_mapping_org_id", "whatsapp_channel_mappings", ["organization_id"])
        op.create_index("ix_wa_mapping_phone_number_id", "whatsapp_channel_mappings", ["phone_number_id"])
        op.create_index("ix_wa_mapping_agent_id", "whatsapp_channel_mappings", ["agent_id"])

def downgrade() -> None:
    op.drop_table("whatsapp_channel_mappings")
