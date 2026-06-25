"""Per-model usage limit enforcement.

데이터 모델 (4계층):
  - 전역 (config):
      usage_limit.default_daily_tokens   ← 모든 모델 fallback
      usage_limit.per_model              ← 모델별 base 한도 (전역)
  - 사용자 (user.info), 그룹 (group.meta), 조직 단위 (org_unit.meta):
      usage_limit.per_model              ← 모델별 override (boost 용도)

값 의미:
  - null/키 없음 = 상속 (상위 계층에서 결정)
  - 0           = 명시적 무제한
  - 양수        = 일일 토큰 한도

규칙: 각 Model 행 R 에 대해 (global default | global per_model[R] | user per_model[R]
| group per_model[R] | org per_model[R]) 후보 중 max(가장 관대한 값) 적용.
오버라이드는 boost 의미 (premium 한도 ↑).

Agent 호출 시 base 행만 게이트 체크. agent 한도는 chat enforce 대상에서 제외 —
실제 토큰 소비는 base 모델 풀에 합산되므로 base 한도 하나로 충분하다 (사용자에게
한 번의 메시지만 노출, agent vs base 중복 차단 방지).
"""

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from open_webui.env import SRC_LOG_LEVELS
from sqlalchemy import String

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


@dataclass
class UsageLimitResult:
    allowed: bool
    action: str  # "allow" | "warn" | "block"
    daily_limit: int
    daily_used: int
    message: str
    # 프론트엔드 i18n 용 구조화 정보 (한도 초과 시에만 채움)
    model_id: Optional[str] = None
    pct: float = 0.0
    source: str = ""

    def to_detail(self) -> dict:
        """HTTPException(detail=...) 용 dict.

        프론트는 `code` 로 i18n 키를 매핑하고, 나머지 필드를 보간 변수로 사용.
        `message` 는 i18n 미적용 클라이언트용 영문 fallback.
        """
        return {
            "code": "USAGE_LIMIT_EXCEEDED",
            "message": self.message,
            "model_id": self.model_id,
            "daily_used": self.daily_used,
            "daily_limit": self.daily_limit,
            "pct": self.pct,
            "source": self.source,
            "action": self.action,
        }


def _unwrap(value):
    """PersistentConfig → 실제 값 (이미 풀린 값이면 그대로)."""
    return value.value if hasattr(value, "value") else value


def _per_model_value(payload, model_id: str) -> Optional[int]:
    """payload (dict) 의 usage_limit.per_model[model_id] 정수값 추출.

    None 반환 = 키 없음 (상속).
    """
    if not isinstance(payload, dict):
        return None
    usage_limit = payload.get("usage_limit")
    if not isinstance(usage_limit, dict):
        return None
    per_model = usage_limit.get("per_model")
    if not isinstance(per_model, dict):
        return None
    val = per_model.get(model_id)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _collect_org_units_for_user(db, user_obj):
    """사용자가 속한 조직 단위 조회 (oauth_sub + email 매칭, 중복 제거)."""
    from open_webui.models.organization import OrganizationalUnit

    units = []
    seen_ids = set()

    if user_obj.oauth_sub:
        for unit in (
            db.query(OrganizationalUnit)
            .filter(
                OrganizationalUnit.member_ids.cast(String).like(
                    f'%"{user_obj.oauth_sub}"%'
                )
            )
            .all()
        ):
            if unit.id not in seen_ids:
                units.append(unit)
                seen_ids.add(unit.id)

    if user_obj.email:
        for unit in (
            db.query(OrganizationalUnit)
            .filter(
                OrganizationalUnit.meta.cast(String).like(
                    f'%"{user_obj.email.lower()}"%'
                )
            )
            .all()
        ):
            if unit.id not in seen_ids:
                units.append(unit)
                seen_ids.add(unit.id)

    return units


def collect_user_quota_layers(request: Request, user_id: str) -> dict:
    """사용자 한도 4계층 (전역 / 사용자 / 그룹 / 조직 단위) 을 한 번에 모아 반환.

    같은 사용자에 대해 여러 model_id 의 한도를 계산할 때 (예: usage-by-model
    리스트) DB 호출을 모델 수만큼 반복하지 않도록 미리 모아두는 헬퍼.

    Returns dict shape:
        {
            "global_per_model": dict[str, int],
            "global_default": int,
            "user_per_model": dict[str, int],
            "groups": list[(name, dict[str, int])],
            "orgs": list[(name, dict[str, int])],
        }
    """
    from open_webui.internal.db import get_db
    from open_webui.models.groups import Groups
    from open_webui.models.users import Users

    cfg = request.app.state.config
    g_per_model = _unwrap(cfg.USAGE_LIMIT_PER_MODEL) or {}
    g_default = int(_unwrap(cfg.USAGE_LIMIT_DEFAULT_DAILY_TOKENS) or 0)

    user = Users.get_user_by_id(user_id)
    user_per_model: dict = {}
    if user:
        info = user.info or {}
        ul = info.get("usage_limit") if isinstance(info, dict) else None
        if isinstance(ul, dict):
            pm = ul.get("per_model")
            if isinstance(pm, dict):
                user_per_model = pm

    groups: list[tuple[str, dict]] = []
    for group in Groups.get_groups_by_member_id(user_id):
        meta = group.meta or {}
        ul = meta.get("usage_limit") if isinstance(meta, dict) else None
        pm = ul.get("per_model") if isinstance(ul, dict) else None
        if isinstance(pm, dict) and pm:
            groups.append((group.name, pm))

    orgs: list[tuple[str, dict]] = []
    if user:
        try:
            with get_db() as db:
                for unit in _collect_org_units_for_user(db, user):
                    meta = unit.meta or {}
                    ul = meta.get("usage_limit") if isinstance(meta, dict) else None
                    pm = ul.get("per_model") if isinstance(ul, dict) else None
                    if isinstance(pm, dict) and pm:
                        orgs.append((unit.display_name or unit.name, pm))
        except Exception as e:
            log.debug("org unit limit lookup skipped: %s", e)

    return {
        "global_per_model": g_per_model,
        "global_default": g_default,
        "user_per_model": user_per_model,
        "groups": groups,
        "orgs": orgs,
    }


def resolve_limit_from_layers(layers: dict, model_id: str) -> tuple[int, str]:
    """미리 모은 layers + model_id → (limit, source). DB 호출 없음.

    값 의미: 0 = 무제한 (즉시 반환), 양수 후보 중 max 채택.
    """

    def _to_int(v) -> Optional[int]:
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    candidates: list[tuple[int, str]] = []

    # 1. 전역
    g_per = _to_int(layers["global_per_model"].get(model_id))
    if g_per is not None:
        if g_per == 0:
            return 0, "global:per_model"
        candidates.append((g_per, "global:per_model"))
    elif layers["global_default"] > 0:
        candidates.append((layers["global_default"], "global:default"))

    # 2. 사용자
    u = _to_int(layers["user_per_model"].get(model_id))
    if u is not None:
        if u == 0:
            return 0, "user"
        candidates.append((u, "user"))

    # 3. 그룹
    for name, pm in layers["groups"]:
        gv = _to_int(pm.get(model_id))
        if gv is not None:
            if gv == 0:
                return 0, f"group:{name}"
            candidates.append((gv, f"group:{name}"))

    # 4. 조직 단위
    for name, pm in layers["orgs"]:
        ov = _to_int(pm.get(model_id))
        if ov is not None:
            if ov == 0:
                return 0, f"org:{name}"
            candidates.append((ov, f"org:{name}"))

    if not candidates:
        return 0, "none"
    return max(candidates, key=lambda x: x[0])


def get_effective_daily_limit_for_model(
    request: Request, user_id: str, model_id: str
) -> tuple[int, str]:
    """(model_id 한정) 가장 관대한 한도 반환. 단일 모델 호출용 (enforce 등).

    여러 모델을 일괄 계산할 땐 `collect_user_quota_layers` +
    `resolve_limit_from_layers` 조합으로 DB 호출 1회만 하도록 권장.

    Returns:
        (limit, source). limit == 0 → 무제한.
    """
    layers = collect_user_quota_layers(request, user_id)
    return resolve_limit_from_layers(layers, model_id)


def check_quota_for_model_row(
    request: Request, user_id: str, model_row
) -> UsageLimitResult:
    """단일 Model 행에 대한 게이트. base/agent 분기 없는 통합 체크.

    카운터는 `USER_QUOTA_MESSAGE_TYPES` 만 합산 — 백그라운드 task
    (title/tags/emoji/query 생성 등) 가 사용자 quota 를 잠식하지 않도록.
    """
    from open_webui.models.usage import USER_QUOTA_MESSAGE_TYPES, Usages

    cfg = request.app.state.config

    if not bool(_unwrap(cfg.ENABLE_USAGE_LIMIT)):
        return UsageLimitResult(True, "allow", 0, 0, "")

    if model_row is None:
        return UsageLimitResult(True, "allow", 0, 0, "")

    daily_limit, source = get_effective_daily_limit_for_model(
        request, user_id, model_row.id
    )
    if daily_limit == 0:
        return UsageLimitResult(True, "allow", 0, 0, "")

    daily_used = Usages.get_user_daily_token_usage_for_model_row(
        user_id, model_row, message_types=USER_QUOTA_MESSAGE_TYPES
    )
    if daily_used < daily_limit:
        return UsageLimitResult(True, "allow", daily_limit, daily_used, "")

    exceed_action = str(_unwrap(cfg.USAGE_LIMIT_EXCEED_ACTION) or "warn")
    pct = round(daily_used / daily_limit * 100, 1) if daily_limit else 0
    # 영문 fallback (구버전 클라이언트 / 로그용). 프론트는 to_detail() 의 code 로 i18n 처리.
    message = (
        f"Daily token usage limit exceeded for model '{model_row.id}' "
        f"({daily_used:,}/{daily_limit:,} tokens, {pct}%). Source: {source}"
    )

    action = "block" if exceed_action == "block" else "warn"
    return UsageLimitResult(
        allowed=(action != "block"),
        action=action,
        daily_limit=daily_limit,
        daily_used=daily_used,
        message=message,
        model_id=model_row.id,
        pct=pct,
        source=source,
    )


def enforce_usage_limit(
    request: Request, user_id: str, user_role: str, called_model_id: Optional[str]
) -> UsageLimitResult:
    """호출 진입점.

    agent 호출이면 base 행만, 그 외엔 호출 행만 게이트한다.
    agent 호출도 `model_id=base` 로 카운팅되므로 base 한 행이면 모든 호출
    (agent 경유 + 직접) 을 한 풀로 게이트할 수 있다.
    """
    cfg = request.app.state.config
    if not bool(_unwrap(cfg.ENABLE_USAGE_LIMIT)):
        return UsageLimitResult(True, "allow", 0, 0, "")
    if user_role == "admin":
        return UsageLimitResult(True, "allow", 0, 0, "")
    if not called_model_id:
        return UsageLimitResult(True, "allow", 0, 0, "")

    from open_webui.models.models import Models

    called = Models.get_model_by_id(called_model_id)
    target_row = None
    if called is not None:
        base_id = getattr(called, "base_model_id", None)
        if base_id:
            base = Models.get_model_by_id(base_id)
            target_row = base if base is not None else None
            if target_row is None:
                # base 행이 DB 에 없으면 가상 base 행으로 카운팅 (counter 는 model_id 기준이라 OK)
                from types import SimpleNamespace

                target_row = SimpleNamespace(id=base_id, base_model_id=None)
        else:
            target_row = called

    if target_row is None:
        # 모델 행을 못 찾으면 fallback: model_id 자체로 가상 base 행
        from types import SimpleNamespace

        target_row = SimpleNamespace(id=called_model_id, base_model_id=None)

    result = check_quota_for_model_row(request, user_id, target_row)

    # agent 호출인데 게이트는 base 행에서 일어났다면, 표시용으로 'agent(base)'
    # 형식 적용. 사용자가 어떤 에이전트를 통해 호출했는지 + 어떤 base 모델 풀이
    # 한도를 잠식했는지 한눈에 파악 가능.
    if (
        result.model_id
        and called is not None
        and getattr(called, "base_model_id", None)
        and called.id != result.model_id
    ):
        result.model_id = f"{called.id} → {result.model_id}"

    return result


# Backward-compat shim: 기존 호출자(model_id 모름) 대비 (deprecated)
def check_usage_limit(
    request: Request, user_id: str, user_role: str
) -> UsageLimitResult:
    """Deprecated: 호출 시점의 model_id 를 알면 enforce_usage_limit() 사용 권장.

    model_id 미지정 시 모든 모델에 대한 통합 체크가 불가능하므로 ENABLE/admin
    전제만 검사하고 통과시킨다. 향후 호출자 일소 후 제거.
    """
    cfg = request.app.state.config
    if not bool(_unwrap(cfg.ENABLE_USAGE_LIMIT)):
        return UsageLimitResult(True, "allow", 0, 0, "")
    if user_role == "admin":
        return UsageLimitResult(True, "allow", 0, 0, "")
    return UsageLimitResult(True, "allow", 0, 0, "")
