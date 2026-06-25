---
paths:
  - "src/lib/apis/**/*.ts"
---

# API 클라이언트 작성 규칙

## 기본 패턴
```typescript
import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getResources = async (token: string) => {
  let error = null;
  const res = await fetch(`${WEBUI_API_BASE_URL}/resources`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`  // 소문자 authorization
    }
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      return null;
    });

  if (error) throw error;
  return res;
};
```

## 핵심 규칙
- `WEBUI_API_BASE_URL` 상수 사용 (직접 URL 하드코딩 금지)
- `authorization: \`Bearer ${token}\`` — 소문자 `authorization`
- 에러: `let error = null` → catch에서 할당 → 함수 끝에서 throw
- 토큰: `localStorage.token` (컴포넌트에서 전달)

## POST 요청
```typescript
export const createResource = async (token: string, data: ResourceForm) => {
  // body: JSON.stringify(data)
  // Content-Type: application/json
};
```

## 파일 업로드
```typescript
const formData = new FormData();
formData.append('file', file);
// Content-Type 헤더 생략 (브라우저 자동 설정)
```

## 타입 정의
```typescript
export type Resource = ResourceForm & {
  id: string;
  user_id: string;
  created_at: number;
  updated_at: number;
  user?: UserResponse;
};
```

## 컴포넌트 사용 패턴
```svelte
try {
  const result = await createResource(localStorage.token, formData);
  toast.success($i18n.t('Created successfully'));
} catch (e) {
  toast.error(e?.detail || $i18n.t('Error'));
}
```

## 에러 메시지 추출
- `extractErrorMessage()` 헬퍼: detail 객체/배열/문자열 처리
- 서버: `error?.detail` 메시지

## 참조 파일
- `apis/knowledge/index.ts`: 표준 CRUD 패턴
- `apis/index.ts` (31KB): 공통 유틸리티
- `apis/streaming/index.ts`: SSE 스트리밍
