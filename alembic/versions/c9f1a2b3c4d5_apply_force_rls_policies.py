"""Apply FORCE ROW LEVEL SECURITY policies across tenant tables

Revision ID: c9f1a2b3c4d5
Revises: b8b93ce3145f
Create Date: 2026-10-13 15:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from services.security.rls import generate_rls_sql

revision: str = 'c9f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'b8b93ce3145f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    if dialect_name == "postgresql":
        sql = generate_rls_sql()
        for stmt in sql.split(";"):
            stmt_clean = stmt.strip()
            if stmt_clean:
                op.execute(sa.text(stmt_clean))

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        from services.security.rls import RLS_TABLES
        for tbl in RLS_TABLES:
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))
            op.execute(sa.text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY;"))
            op.execute(sa.text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;"))
