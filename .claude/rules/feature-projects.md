---
paths:
  - "backend/open_webui/routers/projects.py"
  - "backend/open_webui/models/projects.py"
  - "src/lib/components/projects/**/*.svelte"
  - "src/lib/apis/projects/**/*.ts"
  - "src/routes/(app)/workspace/projects/**/*"
---

# 프로젝트(Projects) 규칙

## 백엔드 라우터 (`/api/v1/projects`)
| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/` | read | 사용자 프로젝트 목록 |
| POST | `/create` | 인증됨 | 생성 (Knowledge 자동 생성) |
| GET | `/{id}` | read | 상세 조회 |
| POST | `/{id}/update` | write | 수정 |
| DELETE | `/{id}/delete` | write | 삭제 (Knowledge 종속 삭제) |
| GET | `/{id}/chats` | read | 프로젝트 채팅 목록 |
| POST | `/{id}/file/add` | write | 파일 추가 (Knowledge 위임) |
| POST | `/{id}/file/remove` | write | 파일 제거 (Knowledge 위임) |
| POST | `/{id}/chat/add` | write | 채팅 연결 |
| POST | `/{id}/chat/remove` | write | 채팅 제거 |
| POST | `/{id}/share` | owner만 | 다른 사용자에게 복사 |

## DB 모델 (Project)
- `id`, `user_id`, `name`, `description`
- `knowledge_id`: 자동 생성되는 Knowledge Base ID (강한 결합)
- `instructions`: 프로젝트 커스텀 instructions
- `data`: JSON — `{"chat_ids": [...]}`
- `meta`: JSON — `color`, `icon`, `default_model_id`, `copied_from`
- `access_control`: 그룹/조직 권한

## Knowledge와의 관계 (핵심)
- **생성 시**: Knowledge 자동 생성 `"[Project] {name}"` → `knowledge_id` 설정
- **파일 관리**: Knowledge 라우터로 위임 (Project는 파일 직접 관리 안 함)
- **삭제 시**: SearchEngineKnowledge 벡터 삭제 → Knowledge 삭제 → Project 삭제
- **공유 시**: 대상 사용자별 새 Knowledge 생성 + 파일 재인덱싱

## 접근 제어
```python
# 3단계: admin 바이패스 → 소유자 → has_access(access_control)
if user.role != "admin" and project.user_id != user.id \
    and not has_access(user.id, permission, project.access_control):
    raise HTTPException(403)
```

## 프론트엔드 컴포넌트
- `CreateProject.svelte`: 생성 모달 (name, description)
- `ProjectDetail.svelte`: 상세 페이지
  - **Chat 탭**: 연결된 채팅 목록 (preview 150자)
  - **Settings 탭** (owner만): 파일 관리, 기본 모델, instructions, 공유, 삭제
  - 파일 업로드: 로컬, Google Drive, OneDrive, SharePoint

## 공유 패턴
- 공유 = 독립 복사 (access_control 공유 아님)
- 원본 파일 재인덱싱으로 새 KB에 추가
- `meta.copied_from`에 출처 기록
