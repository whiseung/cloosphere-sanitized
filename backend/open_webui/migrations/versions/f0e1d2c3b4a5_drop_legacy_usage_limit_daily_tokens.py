"""drop legacy usage_limit.daily_tokens from user/group/org_unit JSON

Revision ID: f0e1d2c3b4a5
Revises: e7dacd03eeb6
Create Date: 2026-05-06 14:30:00.000000

per-model token limit 시스템 도입에 따라 기존 단일 한도 키 폐기.

대상 테이블/JSON 경로:
  - user.info["usage_limit"]["daily_tokens"]
  - group.meta["usage_limit"]["daily_tokens"]
  - organizational_unit.meta["usage_limit"]["daily_tokens"]

각 row 의 JSON 을 파싱해 키만 제거 (다른 키는 보존). usage_limit dict 가
비게 되면 usage_limit 자체도 제거해 cleanup. 키가 이미 없으면 no-op (idempotent).

전역 config 의 usage_limit.default_daily_tokens 는 신규 스키마에서도 동일
의미로 살아남으므로 손대지 않음.
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, None] = "e7dacd03eeb6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _strip_daily_tokens(payload):
    """JSON dict 에서 usage_limit.daily_tokens 키 제거. 변경됐으면 True 반환."""
    if not isinstance(payload, dict):
        return payload, False

    usage_limit = payload.get("usage_limit")
    if not isinstance(usage_limit, dict):
        return payload, False

    if "daily_tokens" not in usage_limit:
        return payload, False

    new_usage = {k: v for k, v in usage_limit.items() if k != "daily_tokens"}
    new_payload = dict(payload)
    if new_usage:
        new_payload["usage_limit"] = new_usage
    else:
        new_payload.pop("usage_limit", None)
    return new_payload, True


def _scrub_table(conn, table: str, column: str) -> int:
    """주어진 (table, JSON column) 에서 daily_tokens 제거. 수정된 row 수 반환.

    Postgres 예약어(user, group) 가 테이블명일 수 있어 식별자는 모두 큰따옴표로 감싼다.
    SQLite 도 큰따옴표 식별자를 허용하므로 양쪽 호환.
    """
    inspector = sa.inspect(conn)
    if table not in set(inspector.get_table_names()):
        return 0
    if column not in {c["name"] for c in inspector.get_columns(table)}:
        return 0

    qt = f'"{table}"'
    qc = f'"{column}"'
    rows = conn.execute(
        sa.text(f"SELECT id, {qc} FROM {qt} WHERE {qc} IS NOT NULL")
    ).fetchall()

    updated = 0
    for row in rows:
        raw = row[1]
        if raw is None:
            continue
        try:
            payload = raw if isinstance(raw, dict) else json.loads(raw)
        except (TypeError, ValueError):
            continue
        new_payload, changed = _strip_daily_tokens(payload)
        if not changed:
            continue
        conn.execute(
            sa.text(f"UPDATE {qt} SET {qc} = :val WHERE id = :id"),
            {"val": json.dumps(new_payload), "id": row[0]},
        )
        updated += 1
    return updated


def upgrade() -> None:
    conn = op.get_bind()
    _scrub_table(conn, "user", "info")
    _scrub_table(conn, "group", "meta")
    _scrub_table(conn, "organizational_unit", "meta")


def downgrade() -> None:
    # 손실된 daily_tokens 값을 복원할 방법이 없음. no-op.
    pass
