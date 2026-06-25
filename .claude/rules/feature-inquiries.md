---
paths:
  - "backend/open_webui/routers/inquiries.py"
  - "backend/open_webui/models/inquiry.py"
  - "src/lib/components/common/InquiryModal.svelte"
  - "src/lib/components/admin/Users/Inquiries.svelte"
  - "src/lib/apis/inquiries/**/*.ts"
---

# 관리자 문의(Inquiries) 규칙

## 백엔드 라우터 (`/api/v1/inquiries`)
| 메서드 | 경로 | 권한 | 설명 |
|--------|------|------|------|
| GET | `/types` | 누구나 | 문의 타입/서브타입 반환 |
| POST | `/` | 인증됨 | 문의 생성 (status: open) |
| GET | `/me` | 인증됨 | 내 문의 조회 |
| GET | `/list` | admin | 전체 문의 (필터링 지원) |
| GET | `/stats` | admin | 상태별 개수 |
| POST | `/{id}` | admin | 상태/답변 수정 |
| POST | `/{id}/close` | 본인만 | 문의 닫기 |
| DELETE | `/{id}` | admin | 삭제 |

## DB 모델 (Inquiry)
- `id`, `user_id` (인덱스), `title`
- `type` (인덱스): usage_limit, feature, bug, account, other
- `subtype`: 타입별 세부 분류
- `content`: Text
- `status` (인덱스): open → in_progress → resolved → closed
- `admin_note`: 관리자 답변
- `created_at` (인덱스), `updated_at`

## 문의 타입 체계
```python
INQUIRY_TYPES = {
    "usage_limit": ["limit_increase", "limit_check"],
    "feature": ["chat", "agent", "knowledge", "database", "tool"],
    "bug": ["chat_error", "agent_error", "upload_error", "other_error"],
    "account": ["permission_request", "account_issue"],
    "other": ["improvement", "other"]
}
```

## 상태 흐름
```
Open → In Progress → Resolved → (사용자가) Closed
```
- 관리자가 직접 Closed로 변경 시 경고 (사용자가 결과 확인 불가)
- 사용자는 본인 문의만 close 가능

## 프론트엔드

### InquiryModal.svelte (사용자)
- 2개 탭: "New Inquiry" (작성) + "My Inquiries" (히스토리)
- 타입 → 서브타입 캐스케이딩 드롭다운
- 관리자 답변: 파란색 배경 "Admin Response" 섹션
- 녹색 배지: admin_note 있고 status != 'closed' 인 수
- `loadBadgeCount()` export 함수

### Inquiries.svelte (관리자)
- 칸반 뷰 (SortableJS 드래그앤드롭) + 리스트 뷰
- 4개 열: Open, In Progress, Resolved, Closed
- 상세 모달: 상태 드롭다운 + admin_note 텍스트에어리어
- Closed 직접 드래그 시 경고 토스트 + 롤백

### UserMenu 배지 (Sidebar)
- "Contact Admin" 메뉴 (관리자 아닌 사용자에게만)
- 녹색 점 배지: 미확인 답변 존재 시
