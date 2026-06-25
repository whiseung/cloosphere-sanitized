"""Remove agent_flow and flow_execution tables (no longer used)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2025-02-03

"""

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    # Drop tables if they exist (they may have been created by a previous migration)
    # These tables are no longer used - flows are now stored in the model table
    conn = op.get_bind()

    # Check and drop flow_execution table
    if conn.dialect.has_table(conn, "flow_execution"):
        op.drop_index(
            "ix_flow_execution_created_at", table_name="flow_execution", if_exists=True
        )
        op.drop_index(
            "ix_flow_execution_status", table_name="flow_execution", if_exists=True
        )
        op.drop_index(
            "ix_flow_execution_user_id", table_name="flow_execution", if_exists=True
        )
        op.drop_index(
            "ix_flow_execution_flow_id", table_name="flow_execution", if_exists=True
        )
        op.drop_table("flow_execution")

    # Check and drop agent_flow table
    if conn.dialect.has_table(conn, "agent_flow"):
        op.drop_index(
            "ix_agent_flow_updated_at", table_name="agent_flow", if_exists=True
        )
        op.drop_index("ix_agent_flow_user_id", table_name="agent_flow", if_exists=True)
        op.drop_table("agent_flow")


def downgrade():
    # No downgrade - these tables are deprecated
    pass
