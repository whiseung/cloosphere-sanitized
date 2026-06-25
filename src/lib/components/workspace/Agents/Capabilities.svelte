<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { config } from '$lib/stores';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import { getImageConnectionsList } from '$lib/apis/images';

	type I18nStore = Readable<{
		t: (key: string) => string;
	}>;
	type CapabilityKey = 'web_search' | 'image_generation' | 'gmail' | 'calendar' | 'drive';

	const i18n = getContext<I18nStore>('i18n');
	const capabilityKeys: CapabilityKey[] = [
		'web_search',
		'image_generation',
		'gmail',
		'calendar',
		'drive'
	];

	const helpText: Record<string, string> = {
		web_search: $i18n.t('Enables web search for retrieving up-to-date information'),
		image_generation: $i18n.t('Enables image generation using AI models'),
		gmail: $i18n.t(
			'Allows this agent to draft / send Gmail (sensitive scope, HITL preview required)'
		),
		calendar: $i18n.t(
			'Allows this agent to view and create Google Calendar events (HITL preview required for creation)'
		),
		drive: $i18n.t(
			'Allows this agent to search Google Drive, read file contents, and create Google Docs (HITL preview required for creation)'
		)
	};

	const labelMap: Record<string, string> = {
		web_search: $i18n.t('Web Search'),
		image_generation: $i18n.t('Image Generation'),
		gmail: $i18n.t('Gmail'),
		calendar: $i18n.t('Google Calendar'),
		drive: $i18n.t('Google Drive')
	};

	const stateDescriptions: Record<string, string> = {
		off: $i18n.t('Feature hidden in chat'),
		on: $i18n.t('Enabled by default, user can disable'),
		user: $i18n.t('Shown in chat, user must enable')
	};
	const stateItems = [
		{ value: 'off', label: $i18n.t('Disabled') },
		{ value: 'on', label: $i18n.t('Default On') },
		{ value: 'user', label: $i18n.t('Default Off') }
	];

	// show_reasoning 은 노출 "수준" 토글 — 순서: 간략 / 상세 / 없음. 기본 brief.
	//  brief    : 기존 단순 상태표시(툴 이름) — 모든 에이전트 기본
	//  detailed : 라이브 "추론 과정" 윈도우(자연어 단계)
	//  off      : 표시 안 함
	const showReasoningItems = [
		{ value: 'brief', label: $i18n.t('Brief') },
		{ value: 'detailed', label: $i18n.t('Detailed') },
		{ value: 'off', label: $i18n.t('None') }
	];
	const showReasoningDescriptions: Record<string, string> = {
		brief: $i18n.t('Tool name only (default)'),
		detailed: $i18n.t('Live reasoning steps'),
		off: $i18n.t('Hidden')
	};

	/** Normalize show_reasoning level. 기본 brief; legacy on/true → detailed. */
	function normalizeShowReasoning(val: string | boolean | undefined): string {
		if (val === true || val === 'on' || val === 'detailed') return 'detailed';
		if (val === false || val === 'off' || val === 'none') return 'off';
		return 'brief';
	}

	// grounding 은 엄격 근거 준수 모드 — binary(on/off). 명시값(on/off)만 존중하고,
	// 미설정은 컨텍스트 기본(groundingDefaultOn — 에이전트=true / 기본 모델=false)을
	// 따른다. 이 컴포넌트는 여러 에디터(AgentEditor/ModelEditor)가 공유하므로,
	// 에디터가 grounding 을 미설정으로 둬도 기본이 올바르게 표시되도록 prop 으로 받는다.
	function normalizeGrounding(val: string | boolean | undefined): boolean {
		if (val === false || val === 'off') return false;
		if (val === true || val === 'on') return true;
		return groundingDefaultOn;
	}
	const groundingDescriptions: Record<'on' | 'off', string> = {
		on: $i18n.t('Answers stay grounded in connected sources; says so when data is missing'),
		off: $i18n.t('Falls back to general knowledge when connected sources do not cover the question')
	};

	// ask_user(HITL) — 정보 부족/의도 모호 시 에이전트가 사용자에게 되묻는 도구.
	// binary(on/off), **기본 off(opt-in)**. legacy 'user'/true 도 on 으로 취급.
	function normalizeAskUser(val: string | boolean | undefined): boolean {
		return val === true || val === 'on' || val === 'user';
	}
	const askUserDescriptions: Record<'on' | 'off', string> = {
		on: $i18n.t('Asks you back when a key detail is missing or the request is ambiguous'),
		off: $i18n.t('Proceeds without asking back')
	};

	export let capabilities: Record<string, string | boolean> = {};

	// grounding 미설정 시 적용할 컨텍스트 기본값. 에이전트(preset=true)=true(on),
	// 기본 모델(preset=false)=false(off). 부모 에디터가 preset 으로 전달한다.
	export let groundingDefaultOn: boolean = true;

	export let webSearchConfig: {
		result_count: number | null;
		domain_filter_list: string[] | null;
	} = {
		result_count: null,
		domain_filter_list: null
	};

	export let imageGenerationConfig: {
		connection_ids: number[];
		names: string[];
	} = {
		connection_ids: [],
		names: []
	};

	/** Normalize legacy boolean values to string enum */
	function normalizeCapValue(val: string | boolean | undefined): string {
		if (val === true) return 'on';
		if (val === false || val === undefined || val === null) return 'off';
		if (['off', 'on', 'user'].includes(val)) return val;
		return 'off';
	}

	// Normalize on mount
	$: {
		for (const key of capabilityKeys) {
			const normalized = normalizeCapValue(capabilities[key]);
			if (capabilities[key] !== normalized) {
				capabilities[key] = normalized;
			}
		}
	}

	// 관리자 패널(연결)에서 활성화한 Google 통합만 capability 로 노출한다.
	// gmail/calendar/drive 는 admin 의 enable_* 플래그(= admin 토글 AND Google OAuth 설정)가
	// true 일 때만 편집 행을 보여준다. 관리자가 끈 기능은 채팅 InputMenu 에서도
	// 'admin_off' 로 숨겨지므로(googleBlockReason), 편집기에서도 동일하게 숨긴다.
	// web_search / image_generation 은 기존 동작 유지(항상 노출).
	const adminFlagMap: Record<string, string> = {
		gmail: 'enable_gmail',
		calendar: 'enable_calendar',
		drive: 'enable_drive'
	};
	$: configFeatures = ($config?.features ?? {}) as Record<string, boolean | undefined>;
	$: visibleCapabilityKeys = capabilityKeys.filter((cap) => {
		const flag = adminFlagMap[cap];
		return flag ? !!configFeatures[flag] : true;
	});

	let domainFilterText = webSearchConfig.domain_filter_list?.join(', ') ?? '';

	function syncDomainFilter() {
		const trimmed = domainFilterText.trim();
		if (trimmed === '') {
			webSearchConfig.domain_filter_list = null;
		} else {
			webSearchConfig.domain_filter_list = trimmed
				.split(',')
				.map((d) => d.trim())
				.filter((d) => d.length > 0);
		}
	}

	function handleResultCountInput(event: Event) {
		const target = event.currentTarget;
		if (!(target instanceof HTMLInputElement)) return;

		webSearchConfig.result_count = target.value ? parseInt(target.value, 10) : null;
	}

	let imageConnections: { idx: number; name: string; engine: string; model: string }[] = [];

	// Admin-level gating: a capability toggle is only shown when its integration is
	// actually enabled in admin settings — Web Search (Admin > Settings > Web
	// Search), Gmail/Calendar/Drive (Admin > Settings > Connections > Google
	// Workspace), and Image Generation (Admin > Settings > Images, AND at least one
	// image service connected). Flags come from $config.features (/api/config).
	$: capabilityEnabled = {
		web_search: $config?.features?.enable_web_search ?? false,
		image_generation:
			($config?.features?.enable_image_generation ?? false) && imageConnections.length > 0,
		gmail: $config?.features?.enable_gmail ?? false,
		calendar: $config?.features?.enable_calendar ?? false,
		drive: $config?.features?.enable_drive ?? false
	} as Record<CapabilityKey, boolean>;
	$: visibleCapabilityKeys = capabilityKeys.filter((key) => capabilityEnabled[key]);

	function toggleImageConnection(conn: { idx: number; name: string }) {
		const idx = imageGenerationConfig.connection_ids.indexOf(conn.idx);
		if (idx >= 0) {
			imageGenerationConfig.connection_ids = imageGenerationConfig.connection_ids.filter(
				(id) => id !== conn.idx
			);
			imageGenerationConfig.names = imageGenerationConfig.names.filter(
				(_, i) => i !== idx
			);
		} else {
			imageGenerationConfig.connection_ids = [
				...imageGenerationConfig.connection_ids,
				conn.idx
			];
			imageGenerationConfig.names = [...imageGenerationConfig.names, conn.name];
		}
	}

	onMount(async () => {
		try {
			imageConnections = await getImageConnectionsList(localStorage.token);
		} catch (e) {
			// Image connections not available
		}
	});
</script>

<div class="capabilities">
	<div class="capabilities__heading">
		<h3>{$i18n.t('Capabilities')}</h3>
		<p>{$i18n.t('Choose which chat capabilities are exposed by default for this agent.')}</p>
	</div>

	<div class="capabilities__panel">
		{#each visibleCapabilityKeys as capability}
			<div class="capabilities__row">
				<LabelBase
					label={labelMap[capability] ?? capability}
					caption={helpText[capability] ?? stateDescriptions[normalizeCapValue(capabilities[capability])]}
					size="md"
				>
					<svelte:fragment slot="right">
						<div class="capabilities__selector-wrap">
							<Selector
								value={normalizeCapValue(capabilities[capability])}
								items={stateItems}
								searchEnabled={false}
								size="md"
								ariaLabel={labelMap[capability] ?? capability}
								on:change={(event) => {
									capabilities[capability] = event.detail.value;
								}}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>

				<div class="capabilities__state-copy">
					{stateDescriptions[normalizeCapValue(capabilities[capability])]}
				</div>
			</div>
		{/each}

		<div class="capabilities__row">
			<LabelBase
				label={$i18n.t('Show Reasoning')}
				caption={$i18n.t(
					"Show the agent's tool calls (arguments / results) and thinking as collapsible blocks before the answer"
				)}
				size="md"
			>
				<svelte:fragment slot="right">
					<div class="capabilities__selector-wrap">
						<Selector
							value={normalizeShowReasoning(capabilities.show_reasoning)}
							items={showReasoningItems}
							searchEnabled={false}
							size="md"
							ariaLabel={$i18n.t('Show Reasoning')}
							on:change={(event) => {
								capabilities.show_reasoning = event.detail.value;
							}}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>

			<div class="capabilities__state-copy">
				{showReasoningDescriptions[normalizeShowReasoning(capabilities.show_reasoning)]}
			</div>
		</div>

		<div class="capabilities__row">
			<LabelBase
				label={$i18n.t('Grounding')}
				caption={$i18n.t(
					'Restrict answers to the connected data sources (knowledge bases, databases, tools).'
				)}
				size="md"
			>
				<svelte:fragment slot="right">
					<Switch
						state={normalizeGrounding(capabilities.grounding)}
						ariaLabel={$i18n.t('Grounding')}
						on:change={(event) => {
							capabilities.grounding = event.detail ? 'on' : 'off';
						}}
					/>
				</svelte:fragment>
			</LabelBase>

			<div class="capabilities__state-copy">
				{normalizeGrounding(capabilities.grounding)
					? groundingDescriptions.on
					: groundingDescriptions.off}
			</div>
		</div>

		<div class="capabilities__row">
			<LabelBase
				label={$i18n.t('Ask the User')}
				caption={$i18n.t(
					'Lets the agent ask you back (with buttons or free text) when a critical piece of info is missing or the request is ambiguous'
				)}
				size="md"
			>
				<svelte:fragment slot="right">
					<Switch
						state={normalizeAskUser(capabilities.ask_user)}
						ariaLabel={$i18n.t('Ask the User')}
						on:change={(event) => {
							capabilities.ask_user = event.detail ? 'on' : 'off';
						}}
					/>
				</svelte:fragment>
			</LabelBase>

			<div class="capabilities__state-copy">
				{normalizeAskUser(capabilities.ask_user)
					? askUserDescriptions.on
					: askUserDescriptions.off}
			</div>
		</div>
	</div>

	{#if capabilityEnabled.web_search && normalizeCapValue(capabilities.web_search) !== 'off'}
		<div class="capabilities__subpanel">
			<div class="capabilities__field">
				<div class="capabilities__field-label">{$i18n.t('Result Count')}</div>
				<input
					type="number"
					min="1"
					max="20"
					class="capabilities__field-input"
					placeholder={$i18n.t('Default (from admin settings)')}
					value={webSearchConfig.result_count ?? ''}
					on:input={handleResultCountInput}
				/>
			</div>
			<div class="capabilities__field">
				<div class="capabilities__field-label">{$i18n.t('Domain Filter')}</div>
				<input
					type="text"
					class="capabilities__field-input"
					placeholder={$i18n.t('e.g. example.com, docs.example.com')}
					bind:value={domainFilterText}
					on:input={syncDomainFilter}
					on:blur={syncDomainFilter}
				/>
			</div>
		</div>
	{/if}

	{#if capabilityEnabled.image_generation && normalizeCapValue(capabilities.image_generation) !== 'off'}
		<div class="capabilities__subpanel">
			<div class="capabilities__field-label">{$i18n.t('Image Generation Models')}</div>
			<div class="capabilities__checkbox-list">
				{#each imageConnections as conn}
					<button
						type="button"
						class="capabilities__checkbox-row"
						on:click={() => toggleImageConnection(conn)}
					>
						<Checkbox
							state={imageGenerationConfig.connection_ids.includes(conn.idx)
								? 'checked'
								: 'unchecked'}
						/>
						<span class="capabilities__engine">{conn.engine}</span>
						<span class="truncate">{conn.name}</span>
					</button>
				{/each}
			</div>
			{#if imageGenerationConfig.connection_ids.length === 0}
				<div class="capabilities__empty-note">
					{$i18n.t('No model selected. All models will be available.')}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.capabilities {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.capabilities__heading {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.capabilities__heading h3 {
		margin: 0;
		font-size: 1rem;
		line-height: 1.5rem;
		font-weight: 600;
		color: var(--cloo-text-primary);
	}

	.capabilities__heading p {
		margin: 0;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	.capabilities__panel,
	.capabilities__subpanel {
		display: flex;
		flex-direction: column;
		padding: 0.5rem 1.5rem;
		border: 1px solid var(--cloo-border-default);
		border-radius: 0.75rem;
		background: var(--cloo-bg-surface);
	}

	.capabilities__row + .capabilities__row {
		border-top: 1px solid var(--cloo-border-subtle);
	}

	.capabilities__row {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
		padding-block: 0.5rem;
	}

	.capabilities__selector-wrap {
		width: 100%;
	}

	/* label+caption 칸이 남는 공간을 모두 차지하게 해 가운데 빈 공간을 없애고
	   캡션이 좁은 칼럼에 갇혀 어색하게 줄바꿈되는 것을 방지한다 (≈ 75:25). */
	.capabilities__row :global(.cloo-label-base__left) {
		flex: 1 1 auto;
		min-width: 0;
	}

	.capabilities__row :global(.cloo-label-base__right) {
		flex: 0 0 25%;
		justify-content: flex-end;
	}

	/* 좁은 caption 칸에서 한글이 음절 단위로 깨지지 않도록 단어(공백) 경계에서만
	   줄바꿈한다 (LabelBase 기본 word-break: break-word 오버라이드). */
	.capabilities__row :global(.cloo-label-base__caption) {
		word-break: keep-all;
	}

	.capabilities__state-copy {
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
		word-break: keep-all;
	}

	.capabilities__subpanel {
		gap: 0.75rem;
	}

	.capabilities__field {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.capabilities__field-label {
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
		color: var(--cloo-text-primary);
	}

	.capabilities__field-input {
		width: 100%;
		padding: 0.625rem 0.75rem;
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-default);
		color: var(--cloo-text-default);
		font-size: 0.875rem;
		line-height: 1.25rem;
		outline: none;
	}

	.capabilities__checkbox-list {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.capabilities__checkbox-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.625rem 0.75rem;
		border: 1px solid var(--cloo-border-subtle);
		border-radius: 0.75rem;
		background: var(--cloo-bg-default);
		color: var(--cloo-text-default);
		text-align: left;
	}

	.capabilities__engine {
		flex-shrink: 0;
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 600;
		color: var(--cloo-color-info);
	}

	.capabilities__empty-note {
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	@media (max-width: 767px) {
		.capabilities__row :global(.cloo-label-base__left),
		.capabilities__row :global(.cloo-label-base__right) {
			flex: 1 1 auto;
		}
	}
</style>
