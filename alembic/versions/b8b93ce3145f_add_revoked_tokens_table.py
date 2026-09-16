"""Add revoked_tokens table

Revision ID: b8b93ce3145f
Revises: a7a92ad2126a
Create Date: 2026-09-17 01:45:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from services.database.session import Base
import services.database.models

revision: str = 'b8b93ce3145f'
down_revision: Union[str, Sequence[str], None] = 'a7a92ad2126a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)

def downgrade() -> None:
    op.drop_table('revoked_tokens')
