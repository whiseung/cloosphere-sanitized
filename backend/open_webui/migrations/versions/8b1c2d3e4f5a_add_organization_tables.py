"""Add organization tables

Revision ID: 8b1c2d3e4f5a
Revises: ca81bd47c050
Create Date: 2025-01-30 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b1c2d3e4f5a"
down_revision: Union[str, None] = "7ade7295f584"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Organization 테이블 생성
    op.create_table(
        "organization",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_index("ix_organization_tenant_id", "organization", ["tenant_id"])

    # OrganizationalUnit 테이블 생성
    op.create_table(
        "organizational_unit",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.Integer(), default=0, nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("member_ids", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_organizational_unit_organization_id",
        "organizational_unit",
        ["organization_id"],
    )
    op.create_index(
        "ix_organizational_unit_parent_id", "organizational_unit", ["parent_id"]
    )
    op.create_index(
        "ix_organizational_unit_external_id", "organizational_unit", ["external_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organizational_unit_external_id", table_name="organizational_unit"
    )
    op.drop_index("ix_organizational_unit_parent_id", table_name="organizational_unit")
    op.drop_index(
        "ix_organizational_unit_organization_id", table_name="organizational_unit"
    )
    op.drop_table("organizational_unit")

    op.drop_index("ix_organization_tenant_id", table_name="organization")
    op.drop_table("organization")
