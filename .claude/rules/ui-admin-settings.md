---
paths:
  - "src/lib/components/admin/Settings/**/*.svelte"
  - "src/routes/(app)/admin/settings/**/*"
---

# 관리자 설정 UI 규칙

## 14개 설정 탭
| Tab ID | 컴포넌트 | 주요 설정 |
|--------|----------|-----------|
| `general` | General.svelte | 버전, 인증, LDAP, 사용량 제한, 기능 토글 |
| `connections` | Connections.svelte | Ollama, OpenAI 연결 설정 |
| `models` | Models.svelte | 모델 CRUD, import/export, 토글 |
| `documents` | Documents.svelte | RAG 임베딩, 검색, 추출, 질문 생성 |
| `search-engine` | SearchEngine.svelte | Azure Search, Milvus, pgvector, ES |
| `web` | WebSearch.svelte | 웹 검색 프로바이더 |
| `code-execution` | CodeExecution.svelte | 코드 실행 설정 |
| `interface` | Interface.svelte | UI 커스터마이즈, 테마 |
| `audio` | Audio.svelte | STT/TTS 프로바이더 |
| `images` | Images.svelte | 이미지 생성 프로바이더 |
| `pipelines` | Pipelines.svelte | 파이프라인 설정 |
| `notifications` | Notifications.svelte | 알림 설정 |
| `branding` | Branding.svelte | 로고, 파비콘, 스플래시 이미지 |
| `license` | License.svelte | 라이선스/피처 키 등록, 티어 관리 |

## 설정 컨테이너 (Settings.svelte)
- 수직 탭 (VerticalTabs) 네비게이션
- 아이콘: 인라인 SVG 문자열 매핑 → `{@html icons[id] || ''}` 렌더링
- 탭 전환: `{#if selectedTab === 'general'} <General /> {/if}`

## 설정 폼 레이아웃 패턴

### 신규 패턴 (공통 컴포넌트 사용)
```svelte
<form class="flex flex-col h-full justify-between space-y-3 text-sm">
  <div class="space-y-2.5 overflow-y-scroll scrollbar-hidden h-full pr-1.5">
    <!-- 섹션: Form 컴포넌트 (Switch 목록) -->
    <Form
      label={$i18n.t('Features')}
      items={featureItems}
      on:change={handleFeatureChange}
    />

    <!-- 섹션: LabelBase + Selector -->
    <LabelBase label={$i18n.t('Default Role')} caption={$i18n.t('...')} size="md">
      <svelte:fragment slot="right">
        <Selector value={config.role} items={roleOptions} size="sm"
          on:change={(e) => config.role = e.detail.value} />
      </svelte:fragment>
    </LabelBase>

    <!-- 입력 필드 -->
    <Input bind:value={config.name} label={$i18n.t('Name')} size="md" />
  </div>

  <!-- 저장 버튼 -->
  <div class="flex justify-end pt-3">
    <Button kind="filled" size="md" type="submit">{$i18n.t('Save')}</Button>
  </div>
</form>
```

### 레거시 패턴 (기존 코드)
```svelte
<div class="mb-2.5 flex w-full justify-between">
  <div class="self-center text-xs font-medium">{$i18n.t('Label')}</div>
  <select bind:value={config.field} />
</div>
```
마이그레이션 시 → `<Selector>` 또는 `<LabelBase>` + `<Selector>` 조합으로 교체

## 저장 패턴 A: Event Dispatcher
```svelte
<script>
  const dispatch = createEventDispatcher();
  const submitHandler = async () => {
    const res = await updateConfig(localStorage.token, config);
    if (res) dispatch('save');
  };
</script>
```

## 저장 패턴 B: Handler Prop
```svelte
<script>
  export let saveHandler: Function;
  const updateHandler = async () => {
    const res = await updateConfig(localStorage.token, config);
    if (res) await saveHandler();
  };
</script>
```

## 부모 토스트 처리
```svelte
<General saveHandler={async () => {
  toast.success($i18n.t('Settings saved successfully!'));
  await config.set(await getBackendConfig());
}} />
```

## 공통 UI 컴포넌트 (설정 내)
- `Button`: 액션 버튼 (kind: filled/outlined/text, size: sm/md/lg)
- `Input`: 텍스트 입력 (label, caption 내장)
- `Textarea`: 멀티라인 입력 (label, caption, autoResize)
- `Selector`: 드롭다운 선택 (searchEnabled, items[])
- `LabelBase`: 레이블+캡션+right slot (Switch/Selector 배치)
- `Form`: Switch 목록 그룹 (items: FormItem[])
- `Switch`: 토글 컨트롤 (state: boolean)
- `SensitiveInput`: 비밀번호/API 키 마스킹
- `Tooltip`: 도움말 호버
- `Spinner`: 로딩 상태
- `ConfirmDialog`: 위험 작업 확인

## Connections 서브 컴포넌트
```
Connections.svelte
├── OllamaConnection.svelte
└── OpenAIConnection.svelte
```

## Models 서브 컴포넌트
```
Models.svelte
├── ModelList.svelte
├── ModelMenu.svelte
├── ConfigureModelsModal.svelte
└── ManageModelsModal.svelte
    ├── ManageOllama.svelte
    └── ManageMultipleOllama.svelte
```

## 참조 파일
- `src/lib/components/admin/Settings.svelte`: 14탭 컨테이너
- `src/lib/components/admin/Settings/General.svelte`: 일반 설정
- `src/lib/components/admin/Settings/Documents.svelte`: RAG 설정 (35KB)
- `src/lib/components/admin/Settings/Audio.svelte`: 오디오 설정 (28KB)
- `src/lib/components/admin/Settings/Images.svelte`: 이미지 설정 (34KB)
