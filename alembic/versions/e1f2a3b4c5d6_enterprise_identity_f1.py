"""enterprise identity and security schema migration

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-10-13 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    # 1. New Columns on organizations
    if 'organizations' in tables:
        org_cols = {c['name'] for c in insp.get_columns('organizations')}
        if 'mfa_enforced' not in org_cols:
            op.add_column('organizations', sa.Column('mfa_enforced', sa.Boolean(), server_default='false', nullable=False))
        if 'ip_allowlist' not in org_cols:
            op.add_column('organizations', sa.Column('ip_allowlist', sa.JSON(), nullable=True))
        if 'support_access_granted_until' not in org_cols:
            op.add_column('organizations', sa.Column('support_access_granted_until', sa.DateTime(timezone=True), nullable=True))
        if 'support_access_granted_by' not in org_cols:
            op.add_column('organizations', sa.Column('support_access_granted_by', sa.String(36), nullable=True))
        if 'data_residency_region' not in org_cols:
            op.add_column('organizations', sa.Column('data_residency_region', sa.String(20), server_default='US', nullable=False))

    # 2. New Columns on users
    if 'users' in tables:
        user_cols = {c['name'] for c in insp.get_columns('users')}
        if 'custom_role_id' not in user_cols:
            op.add_column('users', sa.Column('custom_role_id', sa.String(36), nullable=True))
        if 'mfa_enabled' not in user_cols:
            op.add_column('users', sa.Column('mfa_enabled', sa.Boolean(), server_default='false', nullable=False))
        if 'mfa_secret' not in user_cols:
            op.add_column('users', sa.Column('mfa_secret', sa.String(255), nullable=True))
        if 'mfa_recovery_codes' not in user_cols:
            op.add_column('users', sa.Column('mfa_recovery_codes', sa.JSON(), nullable=True))
        if 'failed_login_attempts' not in user_cols:
            op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), server_default='0', nullable=False))
        if 'locked_until' not in user_cols:
            op.add_column('users', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        if 'email_verified' not in user_cols:
            op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default='true', nullable=False))

    # 3. New Columns on audit_logs
    if 'audit_logs' in tables:
        audit_cols = {c['name'] for c in insp.get_columns('audit_logs')}
        if 'prev_hash' not in audit_cols:
            op.add_column('audit_logs', sa.Column('prev_hash', sa.String(64), nullable=True))
        if 'hash' not in audit_cols:
            op.add_column('audit_logs', sa.Column('hash', sa.String(64), nullable=True))
            try:
                op.create_index('ix_audit_logs_hash', 'audit_logs', ['hash'])
            except Exception:
                pass

    # 4. New Table: sso_configs
    if 'sso_configs' not in tables:
        op.create_table(
            'sso_configs',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), unique=True, nullable=False),
            sa.Column('provider_type', sa.String(20), server_default='SAML', nullable=False),
            sa.Column('idp_metadata_url', sa.String(512), nullable=True),
            sa.Column('idp_entity_id', sa.String(255), nullable=True),
            sa.Column('idp_sso_url', sa.String(512), nullable=True),
            sa.Column('idp_x509_cert', sa.Text(), nullable=True),
            sa.Column('client_id', sa.String(255), nullable=True),
            sa.Column('client_secret_encrypted', sa.Text(), nullable=True),
            sa.Column('enforce_sso', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('jit_provisioning_enabled', sa.Boolean(), server_default='true', nullable=False),
            sa.Column('default_role', sa.String(50), server_default='STAFF', nullable=False),
            sa.Column('domains', sa.JSON(), nullable=True),
            sa.Column('domain_verified', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('verification_token', sa.String(64), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_sso_configs_organization_id', 'sso_configs', ['organization_id'])

    # 5. New Table: scim_tokens
    if 'scim_tokens' not in tables:
        op.create_table(
            'scim_tokens',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(100), server_default='SCIM Directory Token', nullable=False),
            sa.Column('token_hash', sa.String(64), unique=True, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_scim_tokens_organization_id', 'scim_tokens', ['organization_id'])
        op.create_index('ix_scim_tokens_token_hash', 'scim_tokens', ['token_hash'])

    # 6. New Table: user_sessions
    if 'user_sessions' not in tables:
        op.create_table(
            'user_sessions',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('organization_id', sa.String(36), nullable=False),
            sa.Column('session_token_hash', sa.String(64), unique=True, nullable=False),
            sa.Column('device_name', sa.String(255), server_default='Desktop Browser', nullable=False),
            sa.Column('ip_address', sa.String(64), nullable=True),
            sa.Column('user_agent', sa.String(512), nullable=True),
            sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('is_revoked', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_user_sessions_user_id', 'user_sessions', ['user_id'])
        op.create_index('ix_user_sessions_organization_id', 'user_sessions', ['organization_id'])
        op.create_index('ix_user_sessions_session_token_hash', 'user_sessions', ['session_token_hash'])

    # 7. New Table: custom_roles
    if 'custom_roles' not in tables:
        op.create_table(
            'custom_roles',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('permissions', sa.JSON(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_custom_roles_organization_id', 'custom_roles', ['organization_id'])

    # 8. New Table: webhook_subscriptions
    if 'webhook_subscriptions' not in tables:
        op.create_table(
            'webhook_subscriptions',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('endpoint_url', sa.String(512), nullable=False),
            sa.Column('secret_encrypted', sa.Text(), nullable=False),
            sa.Column('events', sa.JSON(), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_webhook_subscriptions_organization_id', 'webhook_subscriptions', ['organization_id'])

    # 9. New Table: webhook_delivery_logs
    if 'webhook_delivery_logs' not in tables:
        op.create_table(
            'webhook_delivery_logs',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('subscription_id', sa.String(36), sa.ForeignKey('webhook_subscriptions.id', ondelete='CASCADE'), nullable=False),
            sa.Column('organization_id', sa.String(36), nullable=False),
            sa.Column('event_type', sa.String(100), nullable=False),
            sa.Column('payload_json', sa.JSON(), nullable=True),
            sa.Column('status_code', sa.Integer(), nullable=True),
            sa.Column('response_body', sa.Text(), nullable=True),
            sa.Column('attempt_count', sa.Integer(), server_default='1', nullable=False),
            sa.Column('success', sa.Boolean(), server_default='false', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_webhook_delivery_logs_subscription_id', 'webhook_delivery_logs', ['subscription_id'])
        op.create_index('ix_webhook_delivery_logs_organization_id', 'webhook_delivery_logs', ['organization_id'])

    # 10. New Table: api_keys
    if 'api_keys' not in tables:
        op.create_table(
            'api_keys',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('organization_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('key_prefix', sa.String(16), nullable=False),
            sa.Column('key_hash', sa.String(64), unique=True, nullable=False),
            sa.Column('scopes', sa.JSON(), nullable=True),
            sa.Column('rate_limit_per_minute', sa.Integer(), server_default='60', nullable=False),
            sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_api_keys_organization_id', 'api_keys', ['organization_id'])
        op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'])

    # 11. PostgreSQL RLS Policies on New Tenant Tables
    if conn.dialect.name == "postgresql":
        tenant_tables = [
            'sso_configs', 'scim_tokens', 'user_sessions',
            'custom_roles', 'webhook_subscriptions', 'webhook_delivery_logs', 'api_keys'
        ]
        for tbl in tenant_tables:
            op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
            op.execute(f"""
                CREATE POLICY {tbl}_tenant_isolation ON {tbl}
                FOR ALL
                USING (
                    organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                    OR NULLIF(current_setting('app.is_super_admin', true), 'false') = 'true'
                )
                WITH CHECK (
                    organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                    OR NULLIF(current_setting('app.is_super_admin', true), 'false') = 'true'
                );
            """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        tenant_tables = [
            'sso_configs', 'scim_tokens', 'user_sessions',
            'custom_roles', 'webhook_subscriptions', 'webhook_delivery_logs', 'api_keys'
        ]
        for tbl in tenant_tables:
            op.execute(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl};")

    op.drop_table('api_keys')
    op.drop_table('webhook_delivery_logs')
    op.drop_table('webhook_subscriptions')
    op.drop_table('custom_roles')
    op.drop_table('user_sessions')
    op.drop_table('scim_tokens')
    op.drop_table('sso_configs')

    op.drop_index('ix_audit_logs_hash', table_name='audit_logs')
    op.drop_column('audit_logs', 'hash')
    op.drop_column('audit_logs', 'prev_hash')

    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'mfa_recovery_codes')
    op.drop_column('users', 'mfa_secret')
    op.drop_column('users', 'mfa_enabled')
    op.drop_column('users', 'custom_role_id')

    op.drop_column('organizations', 'data_residency_region')
    op.drop_column('organizations', 'support_access_granted_by')
    op.drop_column('organizations', 'support_access_granted_until')
    op.drop_column('organizations', 'ip_allowlist')
    op.drop_column('organizations', 'mfa_enforced')
