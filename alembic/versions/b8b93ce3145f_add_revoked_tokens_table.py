"""Add revoked_tokens table

Revision ID: b8b93ce3145f
Revises: a7a92ad2126a
Create Date: 2026-09-17 01:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b8b93ce3145f'
down_revision: Union[str, Sequence[str], None] = 'a7a92ad2126a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('revoked_tokens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_revoked_tokens_token'), 'revoked_tokens', ['token'], unique=True)

def downgrade() -> None:
    op.drop_index(op.f('ix_revoked_tokens_token'), table_name='revoked_tokens')
    op.drop_table('revoked_tokens')
