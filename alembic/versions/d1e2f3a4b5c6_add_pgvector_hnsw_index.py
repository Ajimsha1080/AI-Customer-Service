"""add pgvector extension and hnsw index

Revision ID: d1e2f3a4b5c6
Revises: c9f1a2b3c4d5
Create Date: 2026-10-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw 
            ON document_chunks 
            USING hnsw (embedding vector_cosine_ops);
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw;")
