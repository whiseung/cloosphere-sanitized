"""kms phase 4.1 user api_key_hash

Adds an indexed SHA-256 hash column for API-key lookup and drops the
unique constraint on the now-encrypted ``user.api_key`` column.

Why: Phase 4.1 stores the API key as envelope ciphertext (non-deterministic)
in ``user.api_key`` via the ``EncryptedText`` SQLAlchemy type decorator.
Equality search on the ciphertext is impossible — the indexed
``api_key_hash`` carries the lookup key while ``api_key`` carries the
recoverable value.

Revision ID: 5f9605dd422a
Revises: e3f4a5b6c7d8
Create Date: 2026-04-29 16:23:46.862904
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f9605dd422a"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add api_key_hash column + index, drop the legacy unique constraint
    on api_key, and widen api_key from VARCHAR(255) to TEXT.

    All DDL is idempotent (inspector-guarded) so re-running against a
    partially-applied DB succeeds.

    api_key column widening: envelope ciphertext (kms:azkv-env:...) is
    typically 400-600 chars — it does not fit in the legacy VARCHAR(255).
    The widening is silent for legacy plaintext rows and required for
    Phase 4.1 encrypted writes.
    """
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "user" not in set(inspector.get_table_names()):
        return  # table not yet created — nothing to do

    existing_columns = {c["name"] for c in inspector.get_columns("user")}
    if "api_key_hash" not in existing_columns:
        op.add_column(
            "user",
            sa.Column("api_key_hash", sa.String(length=64), nullable=True),
        )

    inspector = sa.inspect(conn)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user")}
    if "ix_user_api_key_hash" not in existing_indexes:
        op.create_index(
            "ix_user_api_key_hash",
            "user",
            ["api_key_hash"],
            unique=True,
        )

    # Widen api_key to TEXT so envelope ciphertext fits. Existing rows
    # are preserved (VARCHAR → TEXT is non-destructive on Postgres /
    # SQLite). Idempotent: only run if the current column is bounded.
    inspector = sa.inspect(conn)
    cols = {c["name"]: c for c in inspector.get_columns("user")}
    api_key_col = cols.get("api_key", {})
    api_key_type = api_key_col.get("type")
    # Postgres reports VARCHAR/String with `length`; TEXT has length=None.
    if api_key_type is not None and getattr(api_key_type, "length", None):
        op.alter_column(
            "user",
            "api_key",
            existing_type=api_key_type,
            type_=sa.Text(),
            existing_nullable=True,
        )

    # Drop the legacy unique constraint on api_key — envelope ciphertext is
    # non-deterministic so a unique constraint on the encrypted column is
    # both impossible to satisfy after migration and meaningless. The
    # api_key_hash unique index now enforces key uniqueness.
    inspector = sa.inspect(conn)
    unique_constraints = inspector.get_unique_constraints("user")
    for uc in unique_constraints:
        if uc.get("column_names") == ["api_key"]:
            try:
                op.drop_constraint(uc["name"], "user", type_="unique")
            except Exception:
                pass
    # SQLite / some Postgres setups expose unique as an index instead.
    inspector = sa.inspect(conn)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user")}
    for idx_name in ("user_api_key_key", "ix_user_api_key"):
        if idx_name in existing_indexes:
            try:
                op.drop_index(idx_name, table_name="user")
            except Exception:
                pass


def downgrade() -> None:
    """Reverse: drop the hash column + index. The api_key column type
    change (String → EncryptedText) is application-level (TypeDecorator)
    and needs no schema downgrade."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "user" not in set(inspector.get_table_names()):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user")}
    if "ix_user_api_key_hash" in existing_indexes:
        op.drop_index("ix_user_api_key_hash", table_name="user")

    existing_columns = {c["name"] for c in inspector.get_columns("user")}
    if "api_key_hash" in existing_columns:
        op.drop_column("user", "api_key_hash")
