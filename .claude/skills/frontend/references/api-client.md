# API 클라이언트 가이드

## 파일 위치

- **위치**: `src/lib/apis/{resource}/index.ts`
- **예시**: `src/lib/apis/chats/index.ts`, `src/lib/apis/users/index.ts`

## 기본 패턴

```typescript
import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getResource = async (token: string) => {
  let error = null;

  const res = await fetch(`${WEBUI_API_BASE_URL}/resource`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`
    }
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
```

## HTTP 메서드별 패턴

### GET 요청 (쿼리 파라미터)

```typescript
export const getItems = async (token: string, page?: number) => {
  let error = null;

  const searchParams = new URLSearchParams();
  if (page !== undefined) {
    searchParams.append('page', `${page}`);
  }

  const res = await fetch(`${WEBUI_API_BASE_URL}/items?${searchParams.toString()}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token && { authorization: `Bearer ${token}` })
    }
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
```

### POST 요청

```typescript
export const createItem = async (token: string, data: CreateItemPayload) => {
  let error = null;

  const res = await fetch(`${WEBUI_API_BASE_URL}/items/new`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`
    },
    body: JSON.stringify(data)
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
```

### DELETE 요청

```typescript
export const deleteItem = async (token: string, id: string) => {
  let error = null;

  const res = await fetch(`${WEBUI_API_BASE_URL}/items/${id}`, {
    method: 'DELETE',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      authorization: `Bearer ${token}`
    }
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
```

## 파일 업로드

```typescript
export const uploadFile = async (token: string, file: File) => {
  let error = null;

  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${WEBUI_API_BASE_URL}/files/upload`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${token}`
      // Content-Type 설정하지 않음 (FormData가 자동 설정)
    },
    body: formData
  })
    .then(async (res) => {
      if (!res.ok) throw await res.json();
      return res.json();
    })
    .catch((err) => {
      error = err;
      console.log(err);
      return null;
    });

  if (error) {
    throw error;
  }

  return res;
};
```

## 컴포넌트에서 사용

```svelte
<script lang="ts">
  import { toast } from 'svelte-sonner';
  import { getContext } from 'svelte';
  import { getItems, createItem, deleteItem } from '$lib/apis/items';

  const i18n = getContext('i18n');

  let items = [];
  let loading = false;

  const loadItems = async () => {
    loading = true;
    try {
      items = await getItems(localStorage.token);
    } catch (error) {
      toast.error($i18n.t('Failed to load items'));
    } finally {
      loading = false;
    }
  };

  const handleCreate = async (data) => {
    try {
      const newItem = await createItem(localStorage.token, data);
      items = [...items, newItem];
      toast.success($i18n.t('Item created'));
    } catch (error) {
      toast.error(error?.detail ?? $i18n.t('Failed to create item'));
    }
  };
</script>
```

## 핵심 규칙

- **토큰**: `localStorage.token`
- **authorization**: 소문자 `authorization` (대문자 `Authorization` 아님)
- **에러 표시**: `toast.error(error?.detail ?? $i18n.t('fallback message'))`
- **상수**: `WEBUI_API_BASE_URL` 사용

## 참조 파일

- `src/lib/apis/chats/index.ts` - 채팅 CRUD
- `src/lib/apis/knowledge/index.ts` - 지식 기반
- `src/lib/apis/dbsphere/index.ts` - 데이터베이스
- `src/lib/apis/configs/index.ts` - 설정
