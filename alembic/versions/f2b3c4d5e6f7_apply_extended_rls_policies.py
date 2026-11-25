"""Apply extended RLS policies to all tenant tables

Revision ID: f2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-11-26 01:42:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from services.security.rls import generate_rls_sql, RLS_TABLES

revision: str = 'f2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
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
        for tbl in RLS_TABLES:
            op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};"))
            op.execute(sa.text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY;"))
            op.execute(sa.text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY;"))
