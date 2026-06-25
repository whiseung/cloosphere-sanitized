---
paths:
  - "src/lib/components/workspace/**/*.svelte"
  - "src/routes/(app)/workspace/**/*"
---

# 워크스페이스 UI 규칙

## 구성 영역
```
workspace/
├── Agents/           # 에이전트 편집기
├── Knowledge/        # 지식베이스 관리
├── Database/         # DbSphere 관리
├── AgentFlows/       # 플로우 빌더
├── Glossary/         # 용어집 관리
├── Guardrails/       # 가드레일 편집기
├── Tools/            # 도구/툴킷 편집기
├── Prompts/          # 프롬프트/명령어 편집기
├── Projects/         # 프로젝트 관리 (→ src/lib/components/projects/)
└── common/           # AccessControl, ValvesModal 등
```

> **참고**: Projects 컴포넌트는 `src/lib/components/projects/`에 위치. 상세 규칙은 `feature-projects.md` 참조.

## AgentEditor.svelte (1000+줄, 핵심 편집기)
- **기능 체크박스 없음** — 리소스 연결 여부로 에이전트 기능 자동 결정 (UnifiedAgent)
- **폼 데이터**: id, name, base_model_id, meta(description, tags, capabilities), params(system, format_prompt, temperature...)
- **프롬프트 2종**: "작업 프롬프트"(system) + "답변 포멧 프롬프트"(format_prompt) — 항상 표시
- **리소스 연결 섹션**: knowledge / dbspheres / knowledge_graphs / glossaries / toolConnections / guardrailsList
- **저장 시**: legacy 플래그(`enable_kbsphere`, `enable_dbsphere`)는 `delete`로 정리
- **이미지 업로드**: Canvas 리사이즈 (250x250px)
- **ID 자동 생성**: 이름에서 자동 생성
- **JSON 미리보기 토글**: 폼 데이터 확인용

## 셀렉터 패턴 (공통)
```svelte
<Selector on:select={(e) => {
  const item = e.detail;
  if (!selectedArray.find(x => x.id === item.id)) {
    selectedArray = [...selectedArray, item];
  }
}}>
  <button>{$i18n.t('Select')}</button>
</Selector>
```
- Fuse.js 검색 필터링
- DropdownMenu.Item 클릭 → select 이벤트 디스패치
- 중복 추가 방지

## 선택 항목 표시 패턴
```svelte
{#each selectedArray as item}
  <FileItem
    file={item} name={item.name}
    dismissible
    on:dismiss={() => { selectedArray = selectedArray.filter(...); }}
  />
{/each}
```

## GuardrailEditor.svelte (650줄)
- **규칙 기반 감지**: PII 타입(email, credit_card, ip, mac, url, api_key) + 전략(block/redact/mask/hash)
- **커스텀 패턴**: 정규식 이름+패턴 입력
- **차단 단어 리스트**
- **LLM Judge**: 모델 선택 + 판단 프롬프트 + pass/block 예시
- **적용 대상**: Input/Output 체크박스 분리
- **테스트 섹션**: 실시간 가드레일 테스트 + 위반 보고

## GlossaryDetail.svelte (690줄)
- **2패널 레이아웃**: 좌측(입력폼: 용어, 동의어, 설명, 예시) + 우측(스크롤 목록 + Fuse.js 검색)
- **Import/Export**: JSON 형식 검증
- **동기화 버튼**: 검색 엔진 동기화 + 상태 토스트

## FlowBuilder.svelte (400+줄, @xyflow/svelte)
- **노드 타입 레지스트리**: flowInput, flowOutput, agent, model, condition, transform, router, aggregator, humanInput, subflow, guardrail, errorHandler, notification
- **상태 관리**: `nodes: writable<Node[]>`, `edges: writable<Edge[]>`, `selectedNode`
- **`collectStateKeys()`**: 노드 타입별 출력 키 수집 (model→response+JSON필드, agent→response, transform→outputKey)
- **드래그 API**: `event.dataTransfer.setData('application/reactflow', type)`

## ToolkitEditor.svelte
- CodeEditor 컴포넌트로 도구 코드 편집
- 보일러플레이트 코드 생성 지원

## PromptEditor.svelte (150+줄)
- 제목 → 명령어 자동 생성 (영숫자 + 하이픈만: `/^[a-zA-Z0-9-]+$/`)
- Content textarea + AccessControlModal

## AccessControl 공통 패턴
```typescript
accessControl = {
  read: { group_ids: [], user_ids: [], org_unit_ids: [] },
  write: { group_ids: [], user_ids: [], org_unit_ids: [] }
}
```
- `AccessControlModal.svelte` → `AccessControl.svelte` 래퍼
- `lastAccessControlJson` 변경 감지로 불필요한 저장 방지
- Agent, Guardrail, Glossary, Tools, Prompts, Database 공통 사용

## 검색+필터 패턴 (Fuse.js)
```typescript
let fuse = new Fuse(items, { keys: ['name', 'description'] });
$: filteredItems = query && fuse
  ? fuse.search(query).map(e => e.item)
  : items;
```

## 폼 제출 패턴
```typescript
const submitHandler = async () => {
  loading = true;
  await updateResource(localStorage.token, id, formData);
  toast.success($i18n.t('Updated'));
  loading = false;
};
```

## onMount 데이터 로드 패턴
```typescript
onMount(async () => {
  const resource = await getResourceById(localStorage.token, id);
  if (resource) { /* 폼 채우기 */ }
  else { goto('/workspace/...'); }
});
```

## 참조 파일
- `src/lib/components/workspace/Agents/AgentEditor.svelte`: 에이전트 편집기
- `src/lib/components/workspace/Guardrails/GuardrailEditor.svelte`: 가드레일 편집기
- `src/lib/components/workspace/Glossary/GlossaryDetail.svelte`: 용어집 상세
- `src/lib/components/workspace/AgentFlows/FlowBuilder.svelte`: 플로우 빌더
- `src/lib/components/workspace/common/AccessControlModal.svelte`: 접근 제어
