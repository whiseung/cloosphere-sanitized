> Last Updated: 2026-04-08

# 04. Glossary 프론트엔드

## 1. 컴포넌트 구조

```
src/lib/components/workspace/Glossary/
├── CreateGlossary.svelte       # 신규 생성 폼 (name, description, access_control)
└── GlossaryDetail.svelte       # 상세 편집 (2패널: 입력폼 + 용어 리스트, ~690 lines)

src/lib/components/workspace/Agents/
└── Glossary.svelte             # Agent 편집기의 Glossary 선택 섹션

src/lib/components/workspace/AgentFlows/nodes/
└── GlossaryNode.svelte         # AgentFlow 노드 (Glossary를 플로우에 배치)
```

### `GlossaryDetail.svelte` (690 lines, 2패널 레이아웃)

워크스페이스의 `/workspace/glossary/[id]` 페이지에서 사용되는 메인 편집 UI.

**레이아웃**:
- **좌측 패널** — 입력 폼 (term, synonyms, description, example, category)
- **우측 패널** — entries 목록 (Fuse.js 기반 실시간 검색 + 스크롤)

**주요 상태**:

| State | Type | 설명 |
|---|---|---|
| `glossary` | `GlossaryModel` | 현재 편집 중인 Glossary |
| `entries` | `Entry[]` | `glossary.data.entries` 참조 |
| `selectedEntry` | `Entry \| null` | 좌측 폼에 로드된 entry |
| `searchQuery` | `string` | Fuse.js 검색 쿼리 |
| `fuse` | `Fuse<Entry>` | 실시간 필터링 인스턴스 |
| `syncing` | `boolean` | 검색 엔진 동기화 중 플래그 |

**Entry 필드 (실제 코드 기준)**:

```typescript
interface GlossaryEntry {
  id: string;            // UUID (프론트엔드가 생성, 백엔드 저장)
  term: string;          // 용어명 (필수)
  synonyms: string[];    // 동의어/별칭 (tag input)
  description: string;   // 설명 (필수)
  example: string;       // 사용 예시 (선택)
  category?: string;     // 카테고리 (선택, dropdown/input)
}
```

> **주의**: 과거 문서에 나오는 `aliases` / `definition` 필드명은 구 용어이며 실제 코드는 `synonyms` / `description`을 사용합니다.

**주요 기능**:
- **추가/수정**: 좌측 폼 작성 → 저장 버튼 → `entries` 배열 업데이트 → `updateGlossaryById()` 호출
- **삭제**: 우측 리스트 항목의 delete 버튼 → `entries`에서 제거 → 서버 업데이트
- **검색**: Fuse.js로 term/synonyms/description 필드에서 실시간 필터링
- **Import**: JSON 파일 업로드 → 검증 후 `entries`에 병합
- **Export**: `entries` 배열을 JSON 파일로 다운로드
- **동기화**: `POST /{id}/sync` 호출 버튼 → 검색 엔진 재색인
- **Access Control**: `AccessControlModal` 열기

### `CreateGlossary.svelte`

간단한 생성 폼 — `name`, `description`, `access_control`만 입력. 저장 후 `/workspace/glossary/{id}` 로 이동하여 상세 편집 유도.

### `Glossary.svelte` (Agent 편집기 섹션)

Agent 편집기 내부에서 `getGlossaryList()` (write 권한 기준)로 선택 가능한 Glossary 목록을 로드하고, 에이전트의 `meta.glossary_ids` 배열에 선택된 Glossary ID를 저장.

### `GlossaryNode.svelte` (AgentFlow 노드)

AgentFlow 플로우 빌더에서 배치할 수 있는 Glossary 노드. 노드 설정에서 Glossary를 선택하면 flow 실행 시점에 해당 Glossary의 검색 결과가 downstream 노드로 전달된다.

## 2. API 클라이언트

**파일**: `src/lib/apis/glossary/index.ts`

| 함수 | 엔드포인트 |
|---|---|
| `createNewGlossary(token, form)` | `POST /create` |
| `getGlossaries(token)` | `GET /` |
| `getGlossaryList(token)` | `GET /list` |
| `getGlossaryById(token, id)` | `GET /{id}` |
| `updateGlossaryById(token, id, form)` | `POST /{id}/update` |
| `syncGlossary(token, id)` | `POST /{id}/sync` |
| `getLinkedAgentsByGlossaryId(token, id)` | `GET /{id}/linked-agents` |
| `deleteGlossaryById(token, id)` | `DELETE /{id}/delete` |

## 3. 다국어 (i18n)

| 키 | 설명 |
|---|---|
| `Glossary` | 메뉴/페이지 제목 |
| `Add term` | 용어 추가 버튼 |
| `Term` / `Synonyms` / `Description` / `Example` / `Category` | 필드 라벨 |
| `Import JSON` / `Export JSON` | 가져오기/내보내기 |
| `Sync to Search Engine` | 검색 엔진 동기화 |
| `No terms found` | 검색 결과 없음 |
| `Term required` | 필수 필드 에러 |

## 4. 스타일링

모든 입력 필드는 공통 컴포넌트 (`Input`, `Button`, `Selector`, `Tabs`, `Switch`) 기반. `--cloo-*` CSS 변수 자동 적용으로 `dark:` 수동 지정 최소화. 2패널 레이아웃은 Tailwind `grid grid-cols-[400px_1fr] gap-4` 패턴.

## 5. 확장 시 주의사항

- **새 필드 추가**: `Entry` interface 확장 → `GlossaryDetail.svelte` 폼에 필드 추가 → 백엔드 `GlossaryEntryInput` Pydantic 모델에 필드 추가 → `GlossaryIndexService.index_entries()`가 새 필드를 검색 엔진 스키마에 포함하도록 수정 → 마이그레이션 필요 없음 (JSON 필드라서)
- **검색 엔진 스키마 변경**: `extension_modules/search_engine/schemas.py::create_glossary_config()` 수정 → 기존 인덱스 재생성 필요 → 사용자에게 `POST /{id}/sync` 안내
- **AgentFlow 노드 확장**: `GlossaryNode.svelte`에 입/출력 핸들 추가 → `FlowBuilder.svelte`의 node registry에 등록 → `collectStateKeys()`에 output 키 추가
