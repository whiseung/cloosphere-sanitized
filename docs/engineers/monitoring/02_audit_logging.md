# Audit Logging (감사 로깅)

## 1. 개요

Audit Logging은 Cloosphere에서 발생하는 중요한 사용자 활동을 기록합니다. 보안 감사, 규정 준수, 문제 추적에 활용됩니다.

## 2. 데이터베이스 모델

### Audit Log 테이블

```python
# backend/open_webui/models/audit_log.py

class AuditLog(Base):
    __tablename__ = "log_audit"

    id = Column(String, primary_key=True)           # UUID
    user_id = Column(String)                         # 활동 수행 사용자
    action = Column(String)                          # 수행된 작업
    resource_type = Column(String)                   # 리소스 유형
    resource_id = Column(String, nullable=True)      # 리소스 ID
    details = Column(JSON, nullable=True)            # 상세 정보
    ip_address = Column(String, nullable=True)       # 클라이언트 IP
    user_agent = Column(String, nullable=True)       # 브라우저 정보
    created_at = Column(BigInteger)                  # 발생 시간
```

### Action 유형

| Action | 설명 |
|--------|------|
| `login` | 로그인 |
| `logout` | 로그아웃 |
| `login_failed` | 로그인 실패 |
| `create` | 리소스 생성 |
| `update` | 리소스 수정 |
| `delete` | 리소스 삭제 |
| `access` | 리소스 접근 |
| `export` | 데이터 내보내기 |
| `import` | 데이터 가져오기 |
| `permission_change` | 권한 변경 |
| `settings_change` | 설정 변경 |

### Resource Type

| Resource Type | 설명 |
|---------------|------|
| `user` | 사용자 |
| `chat` | 채팅 |
| `knowledge` | 지식베이스 |
| `dbsphere` | 데이터베이스 연결 |
| `glossary` | 용어집 |
| `model` | 모델/에이전트 |
| `tool` | 도구 |
| `group` | 그룹 |
| `organization` | 조직 |
| `settings` | 시스템 설정 |

### Details 필드 예시

```python
# 리소스 생성
details = {
    "name": "My Knowledge Base",
    "description": "문서 기반 지식베이스"
}

# 리소스 수정
details = {
    "changes": {
        "name": {"old": "Old Name", "new": "New Name"},
        "description": {"old": "...", "new": "..."}
    }
}

# 권한 변경
details = {
    "access_control": {
        "read": {"group_ids": ["team-a", "team-b"]},
        "write": {"group_ids": ["team-a-leads"]}
    }
}

# 로그인 실패
details = {
    "reason": "invalid_password",
    "attempt_count": 3
}
```

## 3. Audit Logger 유틸리티

### 기본 사용

```python
# backend/open_webui/utils/audit_logger.py

from open_webui.models.audit_log import AuditLogs

def log_audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str = None,
    details: dict = None,
    request: Request = None,
):
    """감사 로그 기록"""
    ip_address = None
    user_agent = None

    if request:
        ip_address = get_client_ip(request)
        user_agent = request.headers.get("user-agent")

    AuditLogs.insert_new_log(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def get_client_ip(request: Request) -> str:
    """클라이언트 IP 추출"""
    # X-Forwarded-For 헤더 확인 (프록시/로드밸런서)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # X-Real-IP 헤더 확인
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip

    # 직접 연결 IP
    return request.client.host if request.client else None
```

### 라우터에서 사용

```python
# backend/open_webui/routers/knowledge.py

from open_webui.utils.audit_logger import log_audit

@router.post("/", response_model=KnowledgeModel)
async def create_knowledge(
    form_data: KnowledgeForm,
    request: Request,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.insert_new_knowledge(user.id, form_data)

    # 감사 로그 기록
    log_audit(
        user_id=user.id,
        action="create",
        resource_type="knowledge",
        resource_id=knowledge.id,
        details={"name": knowledge.name},
        request=request,
    )

    return knowledge


@router.delete("/{id}")
async def delete_knowledge(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
):
    knowledge = Knowledges.get_knowledge_by_id(id)
    if not knowledge:
        raise HTTPException(404, "Not found")

    Knowledges.delete_knowledge_by_id(id)

    # 감사 로그 기록
    log_audit(
        user_id=user.id,
        action="delete",
        resource_type="knowledge",
        resource_id=id,
        details={"name": knowledge.name},
        request=request,
    )

    return {"success": True}
```

### 인증에서 사용

```python
# backend/open_webui/routers/auths.py

@router.post("/signin")
async def signin(
    form_data: SigninForm,
    request: Request,
):
    user = authenticate_user(form_data.email, form_data.password)

    if not user:
        # 로그인 실패 기록
        log_audit(
            user_id=form_data.email,  # 이메일을 사용자 ID로
            action="login_failed",
            resource_type="auth",
            details={"reason": "invalid_credentials"},
            request=request,
        )
        raise HTTPException(401, "Invalid credentials")

    # 로그인 성공 기록
    log_audit(
        user_id=user.id,
        action="login",
        resource_type="auth",
        request=request,
    )

    return create_token(user)
```

## 4. API 엔드포인트

### 라우터

```python
# backend/open_webui/routers/audit_logs.py

router = APIRouter()

@router.get("/", response_model=AuditLogResponse)
async def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    action: str = None,
    resource_type: str = None,
    user_id: str = None,
    start_date: int = None,
    end_date: int = None,
    user=Depends(get_admin_user),
):
    """감사 로그 목록 조회 (관리자 전용)"""
    logs = AuditLogs.get_logs(
        skip=(page - 1) * limit,
        limit=limit,
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )
    total = AuditLogs.count_logs(
        action=action,
        resource_type=resource_type,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "items": logs,
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.post("/export")
async def export_audit_logs(
    filters: AuditLogFilters,
    user=Depends(get_admin_user),
):
    """감사 로그 CSV 내보내기"""
    logs = AuditLogs.get_logs(
        skip=0,
        limit=10000,  # 최대 10,000건
        **filters.model_dump(exclude_none=True),
    )

    # CSV 생성
    csv_content = generate_csv(logs)

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit-logs-{int(time.time())}.csv"
        }
    )


@router.get("/actions")
async def get_action_types(user=Depends(get_admin_user)):
    """사용 가능한 Action 유형 목록"""
    return {
        "actions": [
            "login", "logout", "login_failed",
            "create", "update", "delete",
            "access", "export", "import",
            "permission_change", "settings_change",
        ]
    }


@router.get("/resource-types")
async def get_resource_types(user=Depends(get_admin_user)):
    """사용 가능한 Resource Type 목록"""
    return {
        "resource_types": [
            "user", "chat", "knowledge", "dbsphere",
            "glossary", "model", "tool", "group",
            "organization", "settings",
        ]
    }
```

## 5. 프론트엔드

### AuditLogs 컴포넌트

```svelte
<!-- src/lib/components/admin/Monitoring/AuditLogs.svelte -->
<script lang="ts">
  import { getAuditLogs, exportAuditLogs } from '$lib/apis/audit_logs';
  import { saveAs } from 'file-saver';

  let logs = [];
  let page = 1;
  let total = 0;
  let filters = {
    action: '',
    resource_type: '',
    user_id: '',
    start_date: null,
    end_date: null
  };

  async function loadLogs() {
    const result = await getAuditLogs(localStorage.token, page, 50, filters);
    logs = result.items;
    total = result.total;
  }

  async function handleExport() {
    const blob = await exportAuditLogs(localStorage.token, filters);
    saveAs(blob, `audit-logs-${Date.now()}.csv`);
  }
</script>

<!-- 필터 영역 -->
<div class="filters">
  <select bind:value={filters.action}>
    <option value="">모든 Action</option>
    <option value="create">Create</option>
    <option value="update">Update</option>
    <option value="delete">Delete</option>
    <option value="login">Login</option>
    <!-- ... -->
  </select>

  <select bind:value={filters.resource_type}>
    <option value="">모든 Resource</option>
    <option value="knowledge">Knowledge</option>
    <option value="chat">Chat</option>
    <!-- ... -->
  </select>

  <DateRangePicker bind:start={filters.start_date} bind:end={filters.end_date} />

  <button on:click={loadLogs}>조회</button>
  <button on:click={handleExport}>CSV 내보내기</button>
</div>

<!-- 로그 테이블 -->
<table>
  <thead>
    <tr>
      <th>시간</th>
      <th>사용자</th>
      <th>Action</th>
      <th>Resource</th>
      <th>IP</th>
      <th>상세</th>
    </tr>
  </thead>
  <tbody>
    {#each logs as log}
      <tr>
        <td>{formatDate(log.created_at)}</td>
        <td>{log.user_id}</td>
        <td><Badge>{log.action}</Badge></td>
        <td>{log.resource_type} / {log.resource_id}</td>
        <td>{log.ip_address}</td>
        <td>
          <button on:click={() => showDetails(log)}>보기</button>
        </td>
      </tr>
    {/each}
  </tbody>
</table>

<!-- 페이지네이션 -->
<Pagination bind:page total={total} limit={50} on:change={loadLogs} />
```

### API 클라이언트

```typescript
// src/lib/apis/audit_logs/index.ts

export const getAuditLogs = async (
  token: string,
  page: number = 1,
  limit: number = 50,
  filters?: AuditLogFilters
): Promise<AuditLogResponse> => {
  const params = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString()
  });

  if (filters?.action) params.append('action', filters.action);
  if (filters?.resource_type) params.append('resource_type', filters.resource_type);
  if (filters?.user_id) params.append('user_id', filters.user_id);
  if (filters?.start_date) params.append('start_date', filters.start_date.toString());
  if (filters?.end_date) params.append('end_date', filters.end_date.toString());

  const res = await fetch(`${WEBUI_API_BASE_URL}/audit_logs/?${params}`, {
    headers: { authorization: `Bearer ${token}` }
  });
  if (!res.ok) throw await res.json();
  return res.json();
};


export const exportAuditLogs = async (
  token: string,
  filters?: AuditLogFilters
): Promise<Blob> => {
  const res = await fetch(`${WEBUI_API_BASE_URL}/audit_logs/export`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(filters || {})
  });
  if (!res.ok) throw await res.json();
  return res.blob();
};
```

## 6. 데이터 보존

### 자동 정리

```python
# backend/open_webui/tasks/cleanup.py

async def cleanup_old_audit_logs():
    """오래된 감사 로그 삭제"""
    retention_days = int(os.getenv("AUDIT_RETENTION_DAYS", "90"))
    cutoff_date = int(time.time()) - (retention_days * 24 * 60 * 60)

    with get_db() as db:
        deleted = db.query(AuditLog).filter(
            AuditLog.created_at < cutoff_date
        ).delete()

        db.commit()
        log.info(f"Deleted {deleted} old audit logs")
```

### 스케줄러 등록

```python
# backend/open_webui/main.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(
        cleanup_old_audit_logs,
        "cron",
        hour=3,  # 매일 새벽 3시
        minute=0,
    )
    scheduler.start()
```

## 7. 보안 고려사항

### 민감 정보 마스킹

```python
def sanitize_details(details: dict) -> dict:
    """민감 정보 마스킹"""
    sensitive_keys = ["password", "api_key", "secret", "token"]
    sanitized = {}

    for key, value in details.items():
        if any(s in key.lower() for s in sensitive_keys):
            sanitized[key] = "***MASKED***"
        elif isinstance(value, dict):
            sanitized[key] = sanitize_details(value)
        else:
            sanitized[key] = value

    return sanitized
```

### 접근 제어

- 감사 로그 조회: 관리자(`admin` role)만 가능
- 감사 로그 삭제: 불가능 (데이터 무결성)
- 감사 로그 수정: 불가능 (데이터 무결성)
