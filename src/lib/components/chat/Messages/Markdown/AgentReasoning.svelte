<script context="module" lang="ts">
	// 스트리밍 중 메시지 content 가 매 청크마다 통째로 replace 되며 마크다운이
	// 재파싱·재렌더된다. 그때 이 컴포넌트가 재생성돼도 사용자의 펼침/접힘 선택을
	// 잃지 않도록 모듈 전역에 보존한다 (key = 안정적 블록 id).
	const openOverrides = new Map<string, boolean>();
</script>

<script lang="ts">
	import { getContext, afterUpdate } from 'svelte';
	import { slide } from 'svelte/transition';
	import type { Readable } from 'svelte/store';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	type I18nStore = Readable<{ t: (key: string, opts?: Record<string, unknown>) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	type Step = {
		kind: 'tool' | 'text';
		tool?: string;
		arg?: string;
		result?: string;
		text?: string;
	};

	// 전용 side-channel(message.reasoning) 로 받은 구조화 데이터.
	// message.content 와 무관 — 우리 챗 UI 에서만 렌더한다.
	export let reasoning: { steps?: Step[]; done?: boolean; duration?: number } | null = null;
	export let id = ''; // 펼침 상태 보존 키 (메시지 단위 안정 id)

	$: steps = reasoning?.steps ?? [];
	$: done = reasoning?.done === true;
	$: duration = reasoning?.duration ?? 0;

	// 도구 → 아이콘 + 현지화 라벨
	const TOOL_MAP: Record<string, { icon: string; key: string }> = {
		kg_search_concepts: { icon: '🔍', key: 'Knowledge graph search' },
		kg_explore_context: { icon: '🕸️', key: 'Knowledge graph exploration' },
		kg_resolve_term: { icon: '🔍', key: 'Term lookup' },
		kg_neighbors: { icon: '🕸️', key: 'Graph neighbors' },
		kg_find_related_tables: { icon: '🗂️', key: 'Find related tables' },
		kg_search_documents: { icon: '📄', key: 'Document search' },
		kg_fetch_data: { icon: '📊', key: 'Fetch data' },
		kg_fetch_document: { icon: '📄', key: 'Fetch document' },
		knowledge_handler: { icon: '📚', key: 'Knowledge base search' },
		run_sql_read: { icon: '📊', key: 'SQL query' },
		run_sql: { icon: '📊', key: 'SQL query' },
		web_search: { icon: '🌐', key: 'Web search' },
		code_interpreter: { icon: '💻', key: 'Code execution' },
		create_pptx: { icon: '📑', key: 'Create presentation' },
		create_docx: { icon: '📝', key: 'Create document' },
		create_xlsx: { icon: '📊', key: 'Create spreadsheet' }
	};
	function toolIcon(tool: string): string {
		return TOOL_MAP[tool]?.icon ?? '🔧';
	}
	function toolLabel(tool: string): string {
		const m = TOOL_MAP[tool];
		return m ? $i18n.t(m.key) : tool;
	}
	function stepText(s: Step): string {
		if (s.kind === 'tool') {
			const lbl = toolLabel(s.tool ?? '');
			return s.arg ? `${lbl} · ${s.arg}` : lbl;
		}
		return s.text ?? '';
	}
	$: currentText = steps.length ? stepText(steps[steps.length - 1]) : $i18n.t('Reasoning…');

	// 펼침/접힘 — `open` 은 순수 파생값(직접 대입 없음)이라 재렌더/재마운트에도 안정적.
	// 우선순위: 사용자가 이 인스턴스에서 토글한 값(userOpen) > 모듈 전역에 보존된
	// 선택(openOverrides) > 자동(스트리밍 중 펼침 / 완료 시 접힘).
	let userOpen: boolean | undefined = undefined;
	let full = false; // 전체 보기(5줄 윈도우 해제)

	$: open =
		userOpen !== undefined
			? userOpen
			: id && openOverrides.has(id)
				? !!openOverrides.get(id)
				: !done;
	$: windowed = open && !done && !full; // 5줄 라이브 윈도우 적용 여부

	function toggle() {
		userOpen = !open; // 현재 표시 상태의 반대
		if (id) openOverrides.set(id, userOpen);
	}

	// 스트리밍 중 자동 스크롤(맨 아래)
	let winEl: HTMLDivElement;
	afterUpdate(() => {
		if (winEl && windowed) winEl.scrollTop = winEl.scrollHeight;
	});
</script>

<div
	class="agent-reason my-1.5 w-full overflow-hidden rounded-xl border border-gray-200 bg-gray-50 text-sm dark:border-gray-800 dark:bg-gray-900"
>
	<!-- 헤더: 접힘 상태에서도 현재 추론 한 줄 라이브 -->
	<button
		type="button"
		class="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-850"
		on:click={toggle}
	>
		<span class="flex w-4 shrink-0 justify-center">
			{#if done}
				<span class="font-bold text-green-500">✓</span>
			{:else}
				<Spinner className="size-3.5" />
			{/if}
		</span>
		<span
			class="min-w-0 flex-1 truncate {done
				? 'font-medium text-gray-500 dark:text-gray-400'
				: 'text-gray-700 dark:text-gray-200'}"
		>
			{#if done}
				{$i18n.t('Reasoning')}
				<span class="text-gray-400 dark:text-gray-500">
					· {duration
						? $i18n.t('{{count}} steps · {{duration}}s', {
								count: steps.length,
								duration
							})
						: $i18n.t('{{count}} steps', { count: steps.length })}
				</span>
			{:else}
				<span class="shimmer">{currentText}</span>
			{/if}
		</span>
		<span class="shrink-0 text-gray-400">
			{#if open}
				<ChevronUp className="size-3.5" strokeWidth="2.5" />
			{:else}
				<ChevronDown className="size-3.5" strokeWidth="2.5" />
			{/if}
		</span>
	</button>

	{#if open}
		<div
			class="border-t border-gray-200 px-3 py-2.5 dark:border-gray-800"
			transition:slide={{ duration: 150 }}
		>
			<div class="relative">
				<div bind:this={winEl} class="reason-lines {windowed ? 'reason-win' : ''}">
					{#each steps as s, i}
						<div
							class="reason-line {i === steps.length - 1 && !done
								? 'text-gray-800 dark:text-gray-100'
								: 'text-gray-500 dark:text-gray-400'}"
						>
							{#if s.kind === 'tool'}
								<span class="reason-chip">
									<span>{toolIcon(s.tool ?? '')}</span>
									<span>{toolLabel(s.tool ?? '')}</span>
								</span>
								{#if s.arg}<span class="text-gray-600 dark:text-gray-300">"{s.arg}"</span>{/if}
								{#if s.result}
									<div class="reason-result">↳ {s.result}</div>
								{/if}
							{:else}
								{s.text}
							{/if}
						</div>
					{/each}
				</div>
				{#if windowed}
					<div class="reason-fade"></div>
				{/if}
			</div>

			<div class="mt-2 flex items-center gap-3">
				{#if !done}
					<button
						type="button"
						class="text-xs text-blue-500 hover:underline"
						on:click|stopPropagation={() => (full = !full)}
					>
						{full ? $i18n.t('Show less') : $i18n.t('Show all')}
					</button>
				{/if}
				<span class="ml-auto text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('{{count}} steps', { count: steps.length })}
				</span>
			</div>
		</div>
	{/if}
</div>

<style>
	.reason-lines {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.reason-win {
		max-height: 8.8em; /* ~5 lines */
		overflow-y: auto;
		scrollbar-width: none;
	}
	.reason-win::-webkit-scrollbar {
		display: none;
	}
	.reason-line {
		font-size: 13px;
		line-height: 1.5;
		word-break: break-word;
	}
	.reason-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		vertical-align: middle;
		margin-right: 5px;
		padding: 1px 7px;
		font-size: 12px;
		border-radius: 7px;
		border: 1px solid var(--cloo-border-default, #e5e7eb);
		background: var(--cloo-bg-surface, #fff);
	}
	:global(.dark) .reason-chip {
		border-color: #374151;
		background: #1f2430;
	}
	.reason-result {
		margin-top: 2px;
		padding-left: 4px;
		font-size: 11.5px;
		color: #9aa0ad;
		white-space: pre-wrap;
		word-break: break-word;
	}
	/* 5줄 윈도우 상단 페이드 ("위에 더 있음" 표시) */
	.reason-fade {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 1.6em;
		pointer-events: none;
		background: linear-gradient(rgb(249, 250, 251), transparent);
	}
	:global(.dark) .reason-fade {
		background: linear-gradient(rgb(17, 24, 39), transparent);
	}
	.shimmer {
		background: linear-gradient(90deg, #8b91a0 35%, #c8cedd 50%, #8b91a0 65%);
		background-size: 200% 100%;
		-webkit-background-clip: text;
		background-clip: text;
		color: transparent;
		animation: reason-sh 1.7s linear infinite;
	}
	@keyframes reason-sh {
		to {
			background-position: -200% 0;
		}
	}
</style>
