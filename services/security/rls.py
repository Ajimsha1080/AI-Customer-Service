import logging
from typing import List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine

logger = logging.getLogger("hospitality_agent_cloud.rls")

# Tables requiring strict multi-tenant Row-Level Security
RLS_TABLES: List[str] = [
    "rooms",
    "facilities",
    "restaurants",
    "activities",
    "rate_plans",
    "residents",
    "reservations",
    "conversations",
    "messages",
    "support_tickets",
    "documents",
    "document_chunks",
    "live_updates",
    "integration_sources",
    "data_access_policies",
    "audit_logs",
    "invitations",
    "usage_events"
]

def generate_rls_sql() -> str:
    """Generates PostgreSQL DDL statements for enabling RLS policies on all tenant tables."""
    ddl_statements = []
    for tbl in RLS_TABLES:
        # Enable RLS on table and enforce even for table owners
        ddl_statements.append(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")
        ddl_statements.append(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY;")
        # Drop existing policy if any
        ddl_statements.append(f"DROP POLICY IF EXISTS tenant_isolation_policy ON {tbl};")
        
        # document_chunks and messages join to parent or filter if organization_id exists
        if tbl == "document_chunks":
            policy_sql = f"""
            CREATE POLICY tenant_isolation_policy ON {tbl}
            FOR ALL
            USING (
                document_id IN (
                    SELECT id FROM documents 
                    WHERE organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )
            WITH CHECK (
                document_id IN (
                    SELECT id FROM documents 
                    WHERE organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            );
            """
        elif tbl == "messages":
            policy_sql = f"""
            CREATE POLICY tenant_isolation_policy ON {tbl}
            FOR ALL
            USING (
                conversation_id IN (
                    SELECT id FROM conversations 
                    WHERE organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            )
            WITH CHECK (
                conversation_id IN (
                    SELECT id FROM conversations 
                    WHERE organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
                )
            );
            """
        else:
            policy_sql = f"""
            CREATE POLICY tenant_isolation_policy ON {tbl}
            FOR ALL
            USING (
                organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
            )
            WITH CHECK (
                organization_id = NULLIF(current_setting('app.current_tenant_id', true), '')
            );
            """
        ddl_statements.append(policy_sql.strip())

    return "\n".join(ddl_statements)

async def apply_rls_policies(session_or_conn) -> None:
    """Applies PostgreSQL RLS statements if running on PostgreSQL."""
    sql = generate_rls_sql()
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                await session_or_conn.execute(text(stmt))
            except Exception as e:
                logger.warning(f"Failed to execute RLS statement on {session_or_conn}: {e}")
