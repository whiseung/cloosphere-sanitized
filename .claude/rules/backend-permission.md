# 권한 모델 규칙 (Cloosphere)

Cloosphere 권한은 두 개의 독립 축으로 구성된다. 혼동 방지를 위해 신규 리소스 추가 시 이 문서를 먼저 읽을 것.

## 두 축 분리

| 축 | 이름 | 저장 위치 | 레벨 도메인 | 판정 함수 |
|---|---|---|---|---|
| **1. Feature Permission** (카테고리 gate) | `workspace.*`, `features.*`, `admin.*`, `chat.*`, `sharing.*` | `group.permissions` JSON (Group 모델) | `none`, `access`, `read`, `write` 4단계 (또는 boolean) | `has_permission_min_level()`, `has_permission()` |
| **2. Resource Permission** (row-level) | `access_control` 필드 | 각 리소스 테이블의 `access_control` JSON 컬럼 | `read`, `write` 2단계만 실사용 (null = public) | `has_access()` |

두 축은 **AND로 평가**한다: Feature에서 카테고리 접근이 허용되고 + 해당 리소스의 access_control에도 허용되어야 최종 허용.

## Feature Permission — 4단계 레벨

`PERMISSION_LEVELS = {"none": 0, "access": 1, "read": 2, "write": 3}` (access_control.py L10).

| 레벨 | 의미 (권장) |
|---|---|
| `none` | 카테고리 메뉴/기능 자체 차단 |
| `access` | (드물게 사용) 기능은 쓸 수 있지만 세부 리스트는 못 봄 |
| `read` | 카테고리의 리소스 조회/사용 |
| `write` | 카테고리의 리소스 생성/수정/삭제 |

**컨벤션**: `access` 레벨은 Feature Permission 전용. Resource Permission의 `access_control` 필드에서는 사용하지 않는다 (코드베이스 전체에서 `read`/`write` 2단계만 실사용 중).

## Resource Permission — 2단계 실사용

`access_control` JSON 스키마:

```json
{
  "read":  { "group_ids": [...], "user_ids": [...], "org_unit_ids": [...] },
  "write": { "group_ids": [...], "user_ids": [...], "org_unit_ids": [...] }
}
```

- `null` (컬럼값이 NULL) → **공개** (모든 로그인 사용자 `read` 허용)
- `{}` (빈 dict) → **비공개** (소유자와 admin만)
- `has_access(user_id, type, access_control)`가 3축 전부 체크 — group / user / org_unit / organization

## 라우터 2단계 체크 패턴 (표준)

```python
# Step 1: Feature Permission (카테고리 gate)
if user.role != "admin" and not has_permission_min_level(
    user.id, "workspace.<resource>", "read", request.app.state.config.USER_PERMISSIONS
):
    raise HTTPException(status_code=401, detail=ERROR_MESSAGES.UNAUTHORIZED)

# Step 2: Resource Permission (row-level)
if user.role == "admin":
    items = Resources.get_resources()
else:
    items = Resources.get_resources_by_user_id(user.id, "read")
```

`get_resources_by_user_id`는 내부적으로 `has_access()`를 호출해 소유자 + access_control 기반 필터링.

## 예시 1 — KB 라우터 (Feature + Resource 2단계)

```python
# routers/knowledge.py:57-93
@router.get("/", response_model=list[KnowledgeUserResponse])
async def get_knowledge(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id, "workspace.knowledge", "read",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(status_code=403)

    if user.role == "admin":
        return Knowledges.get_knowledge_bases()
    return Knowledges.get_knowledge_bases_by_user_id(user.id, "read")
```

## 예시 2 — 에이전트 실행 시 Glossary 필터 (KB 패턴)

에이전트가 private glossary를 붙여놓고 public으로 공개되면 타 사용자가 데이터 유출 가능. 실행 시점에 `user_id` 기준 재필터:

```python
# extension_modules/agent/unified_agent.py
if self._enable_glossary:
    glossary_ids = self.agent_config.get_glossary_ids()
    user_id = self.metadata.get("user_id", "")
    if user_id and glossary_ids:
        user = Users.get_user_by_id(user_id)
        if user and user.role != "admin":
            allowed = {
                g.id
                for g in Glossaries.get_glossaries_by_user_id(user_id, "read")
            }
            blocked = [gid for gid in glossary_ids if gid not in allowed]
            if blocked:
                logger.warning("User %s blocked from glossaries %s", user_id, blocked)
            glossary_ids = [gid for gid in glossary_ids if gid in allowed]
```

## 신규 리소스 추가 체크리스트

1. **모델**: `access_control = Column(JSON, nullable=True)` + `get_<resource>s_by_user_id(user_id, permission)` 메서드 (KB/DB/Glossary 모델 참조).
2. **라우터**: 2단계 체크 패턴 — feature gate + row-level filter.
3. **config.py**: `DEFAULT_USER_PERMISSIONS["workspace"]`에 키 추가 (복수형 리소스 명).
4. **admin Permissions UI**: `Permissions.svelte`의 `defaultPermissions.workspace` 객체 + 드롭다운 행 추가 + i18n `"<Resource> Access"` 키 등록.
5. **에이전트 실행 경로**: 해당 리소스가 UnifiedAgent / AgentFlow / React Agent 등에서 user_id 컨텍스트로 로드된다면 실행 중 재필터 적용.

## 참조

- `backend/open_webui/utils/access_control.py` — `has_permission`, `has_permission_min_level`, `has_access`, `PERMISSION_LEVELS`
- `backend/open_webui/config.py` L1685+ — `DEFAULT_USER_PERMISSIONS` 구조
- `backend/open_webui/routers/knowledge.py`, `routers/dbsphere.py`, `routers/schedules.py` — 2단계 체크 표준 구현
- `backend/open_webui/models/knowledge.py`, `models/glossary.py` — `get_<resource>s_by_user_id` 구현
- `backend/extension_modules/agent/unified_agent.py` — 에이전트 실행 시 필터 패턴
