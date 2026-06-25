# FastAPI 라우터 작성 가이드

## 파일 위치

- **위치**: `backend/open_webui/routers/{resource}.py`
- **예시**: `routers/knowledge.py`, `routers/organizations.py`

## 기본 패턴

```python
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from typing import Optional

from open_webui.utils.auth import get_verified_user, get_admin_user
from open_webui.utils.access_control import has_access
from open_webui.models.items import Items, ItemModel, ItemForm, ItemResponse

router = APIRouter()


############################
# 목록 조회
############################

@router.get("/", response_model=list[ItemModel])
async def get_items(user=Depends(get_verified_user)):
    """사용자의 아이템 목록 조회"""
    return Items.get_items_by_user_id(user.id)


@router.get("/list", response_model=list[ItemModel])
async def get_items_list(user=Depends(get_verified_user)):
    """접근 가능한 모든 아이템 목록 (공유 포함)"""
    items = Items.get_all_items()
    return [
        item for item in items
        if item.user_id == user.id or has_access(
            user.id, type="read", access_control=item.access_control
        )
    ]


############################
# 단일 조회
############################

@router.get("/{id}", response_model=ItemModel)
async def get_item_by_id(id: str, user=Depends(get_verified_user)):
    """아이템 상세 조회"""
    item = Items.get_item_by_id(id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )

    # 권한 검사
    if item.user_id != user.id and not has_access(
        user.id, type="read", access_control=item.access_control
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    return item


############################
# 생성
############################

@router.post("/", response_model=ItemModel)
async def create_item(form_data: ItemForm, user=Depends(get_verified_user)):
    """새 아이템 생성"""
    item = Items.insert_new_item(user.id, form_data)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create item"
        )

    return item


############################
# 수정
############################

@router.post("/{id}", response_model=ItemModel)
async def update_item(
    id: str,
    form_data: ItemForm,
    user=Depends(get_verified_user)
):
    """아이템 수정 (POST 사용 - 프로젝트 컨벤션)"""
    item = Items.get_item_by_id(id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )

    # 권한 검사 (소유자 또는 write 권한)
    if item.user_id != user.id and not has_access(
        user.id, type="write", access_control=item.access_control
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    updated_item = Items.update_item_by_id(id, form_data)
    return updated_item


############################
# 삭제
############################

@router.delete("/{id}")
async def delete_item(id: str, user=Depends(get_verified_user)):
    """아이템 삭제"""
    item = Items.get_item_by_id(id)

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found"
        )

    # 소유자만 삭제 가능
    if item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    result = Items.delete_item_by_id(id)
    return {"success": result}
```

## 권한 검사 패턴

### 인증 의존성

```python
from open_webui.utils.auth import (
    get_current_user,      # 토큰 파싱만
    get_verified_user,     # role in {user, admin} 필수
    get_admin_user,        # role == admin 필수
)

# 일반 사용자 전용
@router.get("/")
async def user_endpoint(user=Depends(get_verified_user)):
    pass

# 관리자 전용
@router.get("/admin")
async def admin_endpoint(user=Depends(get_admin_user)):
    pass
```

### 리소스 권한 검사

```python
from open_webui.utils.access_control import has_access

@router.get("/{id}")
async def get_item(id: str, user=Depends(get_verified_user)):
    item = Items.get_item_by_id(id)

    # 1. 소유자 확인
    if item.user_id == user.id:
        return item

    # 2. 공유 권한 확인
    if has_access(user.id, type="read", access_control=item.access_control):
        return item

    # 3. 관리자 확인
    if user.role == "admin":
        return item

    raise HTTPException(status_code=403, detail="Permission denied")
```

## 요청/응답 모델

### Pydantic Form 모델

```python
from pydantic import BaseModel, Field
from typing import Optional

class ItemForm(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    data: Optional[dict] = None
    access_control: Optional[dict] = None


class ItemUpdateForm(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ItemResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    user_id: str
    created_at: int
    updated_at: int

    class Config:
        from_attributes = True
```

### 응답 형식

```python
# 성공 응답
@router.post("/")
async def create_item(...) -> ItemModel:
    return item  # Pydantic 모델 직접 반환

# 간단한 성공/실패
@router.delete("/{id}")
async def delete_item(...):
    return {"success": True}

# 에러 응답
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Item not found"  # 프론트엔드에서 error?.detail로 접근
)
```

## 파일 업로드

```python
from fastapi import File, UploadFile, Form

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    name: str = Form(None),
    user=Depends(get_verified_user)
):
    """파일 업로드"""
    # 파일 크기 검사
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large"
        )

    # 파일 타입 검사
    allowed_types = ["application/pdf", "text/plain", "application/json"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}"
        )

    # 파일 저장 로직...
    return {"filename": file.filename, "size": len(contents)}
```

## 스트리밍 응답

```python
from fastapi.responses import StreamingResponse
import asyncio

@router.post("/generate")
async def generate_stream(
    form_data: GenerateForm,
    user=Depends(get_verified_user)
):
    """스트리밍 응답 (SSE)"""

    async def event_generator():
        for i in range(10):
            yield f"data: {i}\n\n"
            await asyncio.sleep(0.1)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

## 쿼리 파라미터

```python
from typing import Optional

@router.get("/search")
async def search_items(
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    sort: str = "created_at",
    order: str = "desc",
    user=Depends(get_verified_user)
):
    """검색 및 페이지네이션"""
    offset = (page - 1) * limit

    items = Items.search_items(
        user_id=user.id,
        query=q,
        offset=offset,
        limit=limit,
        sort=sort,
        order=order
    )

    return {
        "items": items,
        "page": page,
        "limit": limit,
        "total": Items.count_items(user_id=user.id, query=q)
    }
```

## Request 객체 사용

```python
from fastapi import Request

@router.get("/config")
async def get_config(request: Request, user=Depends(get_verified_user)):
    """앱 설정 접근"""
    config = request.app.state.config
    return {
        "enable_web_search": config.ENABLE_WEB_SEARCH,
        "rag_top_k": config.RAG_TOP_K
    }
```

## BackgroundTasks

```python
from fastapi import BackgroundTasks

def process_in_background(item_id: str):
    """백그라운드 작업"""
    # 시간이 오래 걸리는 작업...
    pass

@router.post("/")
async def create_item(
    form_data: ItemForm,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user)
):
    item = Items.insert_new_item(user.id, form_data)

    # 백그라운드에서 추가 처리
    background_tasks.add_task(process_in_background, item.id)

    return item
```

## main.py에 등록

```python
# backend/open_webui/main.py

from open_webui.routers import items

# 라우터 등록
app.include_router(items.router, prefix="/api/v1/items", tags=["items"])

# 관리자 전용 라우터
app.include_router(
    admin_items.router,
    prefix="/api/v1/admin/items",
    tags=["admin:items"]
)
```

## 참조 파일

실제 프로젝트 라우터 참고:

| 라우터 | 특징 |
|--------|------|
| `routers/knowledge.py` (23KB) | 기본 CRUD + 파일 연동 |
| `routers/organizations.py` (17KB) | 복잡한 계층 구조, 동기화 |
| `routers/dbsphere.py` (24KB) | DB 연결, 쿼리 실행 |
| `routers/retrieval.py` (72KB) | RAG, 파일 처리, 임베딩 |
| `routers/openai.py` (30KB) | 스트리밍, 프록시 |
| `routers/auths.py` (30KB) | 인증, OAuth |
