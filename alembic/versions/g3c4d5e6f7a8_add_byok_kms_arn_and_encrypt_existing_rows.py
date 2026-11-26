"""Add byok_kms_arn to organizations and encrypt existing plaintext secrets

Revision ID: g3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-11-26 12:40:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from services.security.encryption import encrypt_value

revision: str = 'g3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    org_cols = [c["name"] for c in inspector.get_columns("organizations")]
    if "byok_kms_arn" not in org_cols:
        op.add_column("organizations", sa.Column("byok_kms_arn", sa.String(512), nullable=True))

    # Encrypt existing plaintext rows in users.mfa_secret
    user_rows = bind.execute(sa.text("SELECT id, organization_id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL")).fetchall()
    for row in user_rows:
        sec = row[2]
        if sec and not sec.startswith("env:"):
            enc = encrypt_value(sec, org_id=row[1])
            bind.execute(sa.text("UPDATE users SET mfa_secret = :enc WHERE id = :uid"), {"enc": enc, "uid": row[0]})

    # Encrypt existing plaintext rows in sso_configs.client_secret_encrypted
    sso_rows = bind.execute(sa.text("SELECT id, organization_id, client_secret_encrypted FROM sso_configs WHERE client_secret_encrypted IS NOT NULL")).fetchall()
    for row in sso_rows:
        sec = row[2]
        if sec and not sec.startswith("env:"):
            enc = encrypt_value(sec, org_id=row[1])
            bind.execute(sa.text("UPDATE sso_configs SET client_secret_encrypted = :enc WHERE id = :sid"), {"enc": enc, "sid": row[0]})

    # Encrypt existing plaintext rows in webhook_subscriptions.secret_encrypted
    wh_rows = bind.execute(sa.text("SELECT id, organization_id, secret_encrypted FROM webhook_subscriptions WHERE secret_encrypted IS NOT NULL")).fetchall()
    for row in wh_rows:
        sec = row[2]
        if sec and not sec.startswith("env:"):
            enc = encrypt_value(sec, org_id=row[1])
            bind.execute(sa.text("UPDATE webhook_subscriptions SET secret_encrypted = :enc WHERE id = :wid"), {"enc": enc, "wid": row[0]})

def downgrade() -> None:
    op.drop_column("organizations", "byok_kms_arn")
