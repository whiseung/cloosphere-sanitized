---
paths:
  - "backend/open_webui/routers/**/*.py"
---

# FastAPI 라우터 작성 규칙

## 임포트 패턴
```python
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.<resource> import <Resource>Form, <Resource>Model, <Resource>s
from open_webui.utils.access_control import has_access, has_permission, has_permission_min_level
from open_webui.utils.auth import get_verified_user, get_admin_user
```

## 초기화
```python
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])
router = APIRouter()
```

## CRUD 엔드포인트 패턴

### GET 목록 (읽기 권한 — 워크스페이스 리소스)
```python
@router.get("/", response_model=list[ResourceUserResponse])
async def get_resources(request: Request, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id, "workspace.<resource_type>", "read", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.UNAUTHORIZED)
    if user.role == "admin":
        return Resources.get_resources()
    return Resources.get_resources_by_user_id(user.id, "read")
```

### GET 목록 (쓰기 권한) — 편집 가능한 항목만
```python
@router.get("/list", response_model=list[ResourceUserResponse])
async def get_resource_list(user=Depends(get_verified_user)):
    if user.role == "admin":
        return Resources.get_resources()
    return Resources.get_resources_by_user_id(user.id, "write")
```

### GET 단일 조회
```python
@router.get("/{id}", response_model=Optional[ResourceModel])
async def get_resource_by_id(id: str, user=Depends(get_verified_user)):
    resource = Resources.get_resource_by_id(id)
    if resource:
        if (user.role == "admin" or resource.user_id == user.id
                or has_access(user.id, "read", resource.access_control)):
            return resource
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND)
```

### POST 생성 (쓰기 권한)
```python
@router.post("/create", response_model=Optional[ResourceModel])
async def create_resource(request: Request, form_data: ResourceForm, user=Depends(get_verified_user)):
    if user.role != "admin" and not has_permission_min_level(
        user.id, "workspace.<resource_type>", "write", request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.UNAUTHORIZED)
    resource = Resources.insert_new_resource(user.id, form_data)
    if resource:
        return resource
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MESSAGES.DEFAULT("Error creating"))
```

### POST 수정
```python
@router.post("/{id}/update", response_model=Optional[ResourceModel])
async def update_resource_by_id(id: str, request: Request, form_data: ResourceForm, user=Depends(get_verified_user)):
    resource = Resources.get_resource_by_id(id)
    if not resource:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.NOT_FOUND)
    if resource.user_id != user.id and user.role != "admin":
        if not has_access(user.id, "write", resource.access_control):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_MESSAGES.UNAUTHORIZED)
    # update logic...
```

### DELETE 삭제
```python
@router.delete("/{id}/delete", response_model=bool)
async def delete_resource_by_id(id: str, user=Depends(get_verified_user)):
    # owner 또는 admin만 삭제 가능 (그룹 접근 불가)
```

## 권한 3단계 (리소스 단위)
1. **admin 바이패스**: `user.role == "admin"` → 모든 접근 허용
2. **소유자 체크**: `resource.user_id == user.id`
3. **접근 제어**: `has_access(user.id, "read"/"write", resource.access_control)`

## 워크스페이스 권한 (카테고리 단위, 4레벨)
- `has_permission_min_level(user.id, "workspace.<type>", min_level, request.app.state.config.USER_PERMISSIONS)`
- 레벨: `none(0) < access(1) < read(2) < write(3)`
- 관례: GET 목록/상세 → `"read"`, POST 생성/수정/삭제 → `"write"`
- 알려진 타입: knowledge, knowledge_graph, dbsphere, guardrails, prompts, tools, agents (models), glossary, agent_flows
- 레거시 `has_permission()`은 "none"→False/그외→True로 여전히 유효 (하위 호환)

## main.py 등록
```python
app.include_router(resource.router, prefix="/api/v1/{resource}", tags=["{resource}"])
```

## 에러 처리
- 401: 인증/권한 실패 → `ERROR_MESSAGES.UNAUTHORIZED` 또는 `ERROR_MESSAGES.NOT_FOUND`
- 400: 작업 실패 → `ERROR_MESSAGES.DEFAULT("Custom message")`
- 404: 리소스 없음 → `ERROR_MESSAGES.NOT_FOUND`

## 참조 파일
- 표준 CRUD: `routers/knowledge.py`, `routers/glossary.py`, `routers/guardrails.py`
- 복잡한 라우터: `routers/organizations.py`, `routers/dbsphere.py`
- 에러 상수: `constants.py` → `ERROR_MESSAGES` Enum
