# 관리자 설정 페이지

## 개요

검색 엔진 설정은 **관리자 > 설정 > 검색 엔진** 페이지에서 관리합니다.

## 접근 방법

1. 관리자 계정으로 로그인
2. 좌측 사이드바 → 관리자 패널
3. 설정 탭
4. **검색 엔진** 섹션

## UI 구성

### 엔진 타입 선택

```
┌─────────────────────────────────────────┐
│ Search Engine                           │
├─────────────────────────────────────────┤
│ Engine Type: [Azure AI Search     ▼]    │
│                                         │
│ • Not configured                        │
│ • Azure AI Search                       │
│ • PostgreSQL pgvector                   │
│ • Milvus                                │
│ • Elasticsearch                         │
│ • Google Vertex AI Search               │
└─────────────────────────────────────────┘
```

### Azure AI Search 설정

```
┌─────────────────────────────────────────┐
│ Azure AI Search                         │
├─────────────────────────────────────────┤
│ Endpoint                                │
│ [https://your-search.search.windows.net]│
│                                         │
│ API Key                                 │
│ [••••••••••••••••           ] [👁]      │
│                                         │
│ API Version                             │
│ [2024-07-01                            ]│
│                                         │
│ ℹ️ 임베딩은 문서 설정에서 정의한 방식으로 │
│   수행됩니다. 자동 벡터기는 사용하지     │
│   않습니다.                             │
└─────────────────────────────────────────┘
```

### PostgreSQL pgvector 설정

```
┌─────────────────────────────────────────┐
│ PostgreSQL pgvector                     │
├─────────────────────────────────────────┤
│ Host                    Port            │
│ [localhost         ]    [5432  ]        │
│                                         │
│ Database                                │
│ [postgres                              ]│
│                                         │
│ User                    Password        │
│ [postgres         ]    [••••••••] [👁]  │
└─────────────────────────────────────────┘
```

### Milvus 설정

```
┌─────────────────────────────────────────┐
│ Milvus                                  │
├─────────────────────────────────────────┤
│ Host                    Port            │
│ [localhost         ]    [19530 ]        │
│                                         │
│ User (optional)         Password (opt.) │
│ [                  ]    [        ] [👁] │
└─────────────────────────────────────────┘
```

### Elasticsearch 설정

```
┌─────────────────────────────────────────┐
│ Elasticsearch                           │
├─────────────────────────────────────────┤
│ URL                                     │
│ [http://localhost:9200                 ]│
│                                         │
│ API Key (optional)                      │
│ [                               ] [👁]  │
│                                         │
│ User (optional)         Password (opt.) │
│ [                  ]    [        ] [👁] │
│                                         │
│ CA Certificates Path (optional)         │
│ [/path/to/ca.crt                       ]│
└─────────────────────────────────────────┘
```

### Google Vertex AI Search 설정

```
┌─────────────────────────────────────────┐
│ Google Vertex AI Search                 │
├─────────────────────────────────────────┤
│ Project ID                              │
│ [your-gcp-project-id                   ]│
│                                         │
│ Location                                │
│ [us-central1                           ]│
│                                         │
│ Service Account Key (JSON)              │
│ ┌─────────────────────────────────────┐ │
│ │{                                    │ │
│ │  "type": "service_account",         │ │
│ │  "project_id": "...",               │ │
│ │  ...                                │ │
│ │}                                    │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ℹ️ Google Cloud 서비스 계정 키 JSON     │
│   파일의 내용을 붙여넣으세요.           │
└─────────────────────────────────────────┘
```

## 컴포넌트 구조

### 파일 위치

```
src/lib/components/admin/Settings/SearchEngine.svelte
```

### 주요 기능

```svelte
<script lang="ts">
  import { getSearchEngineConfig, updateSearchEngineConfig } from '$lib/apis/retrieval';
  import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

  let config: SearchEngineConfig | null = null;

  // 설정 로드
  const loadConfig = async () => {
    config = await getSearchEngineConfig(localStorage.token);
  };

  // 설정 저장
  const submitHandler = async () => {
    await updateSearchEngineConfig(localStorage.token, config);
    toast.success($i18n.t('Settings saved successfully!'));
  };

  onMount(() => loadConfig());
</script>

<form on:submit|preventDefault={submitHandler}>
  <!-- 엔진 타입 선택 -->
  <select bind:value={config.engine_type}>
    <option value="">Not configured</option>
    <option value="azure_search">Azure AI Search</option>
    ...
  </select>

  <!-- 엔진별 설정 폼 (조건부 렌더링) -->
  {#if config.engine_type === 'azure_search'}
    <!-- Azure 설정 폼 -->
  {/if}

  <button type="submit">Save</button>
</form>
```

### SensitiveInput 컴포넌트

API 키, 비밀번호 등 민감한 정보를 위한 입력 컴포넌트:

```svelte
<SensitiveInput
  placeholder={$i18n.t('Enter API Key')}
  bind:value={config.azure_api_key}
/>
```

- 기본적으로 `•••••` 마스킹
- 👁 버튼으로 표시/숨김 토글
- 붙여넣기 지원

## API 클라이언트

### 파일 위치

```
src/lib/apis/retrieval/index.ts
```

### 타입 정의

```typescript
export type SearchEngineConfig = {
  engine_type: string;
  // Azure AI Search
  azure_endpoint: string;
  azure_api_key: string;
  azure_api_version: string;
  // pgvector
  pgvector_host: string;
  pgvector_port: number;
  pgvector_database: string;
  pgvector_user: string;
  pgvector_password: string;
  // Milvus
  milvus_host: string;
  milvus_port: number;
  milvus_user: string;
  milvus_password: string;
  // Elasticsearch
  elasticsearch_url: string;
  elasticsearch_api_key: string;
  elasticsearch_user: string;
  elasticsearch_password: string;
  elasticsearch_ca_certs: string;
  // Vertex AI Search
  vertex_project_id: string;
  vertex_location: string;
  vertex_service_account_key: string;
};
```

### API 함수

```typescript
// 설정 조회
export const getSearchEngineConfig = async (token: string): Promise<SearchEngineConfig | null>

// 설정 업데이트
export const updateSearchEngineConfig = async (
  token: string,
  config: Partial<SearchEngineConfig>
)
```

## 번역 키

### 한국어 (ko-KR)

```json
{
  "Search Engine": "검색 엔진",
  "Engine Type": "엔진 타입",
  "Not configured": "설정되지 않음",
  "Endpoint": "엔드포인트",
  "API Key": "API 키",
  "API Version": "API 버전",
  "Host": "호스트",
  "Port": "포트",
  "Database": "데이터베이스",
  "User": "사용자",
  "Password": "비밀번호",
  "URL": "URL",
  "optional": "선택",
  "CA Certificates Path": "CA 인증서 경로",
  "Project ID": "프로젝트 ID",
  "Location": "위치",
  "Service Account Key (JSON)": "서비스 계정 키 JSON",
  "Embedding is performed using the settings in Documents. Auto-vectorizer is not used.": "임베딩은 문서 설정에서 정의한 방식으로 수행됩니다. 자동 벡터기는 사용하지 않습니다.",
  "Paste the contents of your Google Cloud service account key JSON file.": "Google Cloud 서비스 계정 키 JSON 파일의 내용을 붙여넣으세요."
}
```

## Settings.svelte 통합

### 탭 추가

```svelte
<!-- src/lib/components/admin/Settings.svelte -->

import SearchEngine from './Settings/SearchEngine.svelte';

<!-- 탭 버튼 -->
<button on:click={() => (selectedTab = 'search-engine')}>
  <SearchIcon />
  {$i18n.t('Search Engine')}
</button>

<!-- 탭 내용 -->
{#if selectedTab === 'search-engine'}
  <SearchEngine on:save={() => toast.success('Saved')} />
{/if}
```

## 저장 흐름

```
1. 사용자가 폼 작성 후 "Save" 클릭
           │
           ▼
2. submitHandler() 호출
   - updateSearchEngineConfig(token, config)
           │
           ▼
3. POST /api/retrieval/search-engine/config/update
   - Request body: 변경된 설정값
           │
           ▼
4. 백엔드 처리 (retrieval.py)
   - form_data 검증
   - app.state.config.SEARCH_ENGINE_* 업데이트
   - PersistentConfig가 DB에 저장
           │
           ▼
5. 응답 반환
   - { status: true, message: "..." }
           │
           ▼
6. 프론트엔드
   - toast.success() 표시
   - dispatch('save') 이벤트 발생
```

## 주의사항

### 보안

- API 키, 비밀번호는 HTTPS로만 전송
- 백엔드에서 마스킹 없이 저장 (암호화 권장)
- 프론트엔드에서는 `SensitiveInput` 컴포넌트 사용

### 설정 변경 시

- 앱 재시작 없이 즉시 적용
- 기존 연결은 다음 요청부터 새 설정 사용
- 인덱스는 자동으로 재생성되지 않음

### 테스트

설정 저장 후 검색 기능이 정상 동작하는지 확인:

1. 지식 베이스에 문서 업로드
2. 채팅에서 RAG 검색 테스트
3. 검색 결과가 정상적으로 반환되는지 확인
