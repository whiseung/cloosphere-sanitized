<script lang="ts" context="module">
	export type ExtractionMode = 'extracted' | 'memory';

	export type ExtractedTableRow = {
		id: string;
		name: string;
		column_count?: number;
		description?: string | null;
	};

	export type MemoryRow = {
		memory_id: string;
		entity_type: string;
		title: string;
		subtitle?: string | null;
		/** 생성자 구분 (sql_memory): llm_auto | user_manual | schema_extraction | unknown */
		origin?: string | null;
		/** 참조(주입) 이벤트 수 — sql_memory 에만. LLM 실사용/품질 지표 아님. */
		use_count?: number | null;
		last_used_at?: number | null;
		/** 생성자 이메일 — 자동저장 few-shot 은 질문한 사용자의 이메일. */
		user_email?: string | null;
		/** 생성자 표시값 — system 또는 이메일. */
		creator?: string | null;
		/** 최종수정자(이메일)·최종수정일(ISO). */
		last_modified_by?: string | null;
		last_modified_at?: string | null;
	};
</script>

<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Button from '$lib/components/common/Button.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let mode: ExtractionMode = 'extracted';
	export let loading: boolean = false;
	export let canWrite: boolean = false;

	export let extractedTables: ExtractedTableRow[] = [];
	export let memoryItems: MemoryRow[] = [];
	/** 메모리 탭 테이블 필터(현재 선택된 table_name, null=전체). 드롭다운 value 반영용. */
	export let memoryTableFilter: string | null = null;
	/** Optional: table_name → linked memory count, fed by parent for the
	 * "N memories" hint on each extracted row. */
	export let memoryCountByTable: Record<string, number> = {};
	/** Optional: authoritative entity_type → total count, fed by parent from
	 * the stats endpoint. When provided, the filter chips show these totals
	 * instead of counting the (paginated) `memoryItems`, so counts stay correct
	 * even when the list is capped. */
	export let memoryTotals: Record<string, number> = {};
	/** Relationship-graph trigger. Rendered ungated (independent of `canWrite` and
	 * memory presence) so read-only viewers can open the ERD modal. `relationshipsReady`
	 * = schema has been extracted; `relationshipCount` = number of edges. */
	export let relationshipCount: number = 0;
	export let relationshipsReady: boolean = false;

	// 테이블 필터 드롭다운 옵션 — '전체' + 추출된 테이블 목록.
	$: tableOptions = [
		{ value: '', label: $i18n.t('All tables') },
		...extractedTables.map((t) => ({ value: t.name, label: t.name }))
	];

	// Memory tab entity_type filter — 'all' or a specific entity_type.
	let memoryFilter: string = 'all';

	// Stable ordering for the chip group so it doesn't reshuffle as counts
	// change. Includes "all" first.
	const MEMORY_TYPE_ORDER: string[] = [
		'ddl_schema',
		'sql_memory',
		'documentation',
		'sql_example'
	];

	$: memoryCounts = (() => {
		const counts: Record<string, number> = {};
		if (Object.keys(memoryTotals).length > 0) {
			let all = 0;
			for (const t of MEMORY_TYPE_ORDER) counts[t] = memoryTotals[t] ?? 0;
			for (const v of Object.values(memoryTotals)) all += v;
			counts.all = all;
			return counts;
		}
		counts.all = memoryItems.length;
		for (const t of MEMORY_TYPE_ORDER) counts[t] = 0;
		for (const m of memoryItems) {
			counts[m.entity_type] = (counts[m.entity_type] ?? 0) + 1;
		}
		return counts;
	})();

	$: filteredMemoryItems =
		memoryFilter === 'all'
			? memoryItems
			: memoryItems.filter((m) => m.entity_type === memoryFilter);

	// 퓨샷(sql_memory)만 볼 때 정렬: 최신순(backend created_at desc 기본) /
	// 참조순(use_count desc). stable sort 라 참조 동률이면 최신순이 유지된다.
	let memorySort: 'recent' | 'refs' = 'recent';
	$: showSortControl = memoryFilter === 'sql_memory' && filteredMemoryItems.length > 0;
	$: displayMemoryItems =
		memoryFilter === 'sql_memory' && memorySort === 'refs'
			? [...filteredMemoryItems].sort((a, b) => (b.use_count ?? 0) - (a.use_count ?? 0))
			: filteredMemoryItems;

	// Delete-table flow uses ConfirmDialog (consistent with rest of workspace)
	// instead of the blocking browser `confirm()`.
	let confirmDeleteShow = false;
	let pendingDeleteId = '';
	let pendingDeleteName = '';
	$: confirmDeleteMessage = $i18n
		.t("Remove '{{name}}' from extracted tables? This will delete all related memory data.")
		.replace('{{name}}', pendingDeleteName);

	const handleDeleteTable = (id: string, name: string) => {
		pendingDeleteId = id;
		pendingDeleteName = name;
		confirmDeleteShow = true;
	};
	const confirmDeleteTable = () => {
		dispatch('deleteTable', { id: pendingDeleteId, name: pendingDeleteName });
	};

	// Delete-memory flow — 동일하게 ConfirmDialog 로 확인 후 삭제 (다이렉트 삭제 방지).
	let confirmDeleteMemoryShow = false;
	let pendingDeleteMemoryId = '';
	let pendingDeleteMemoryTitle = '';
	$: confirmDeleteMemoryMessage = $i18n
		.t("Delete '{{name}}'? This cannot be undone.")
		.replace('{{name}}', pendingDeleteMemoryTitle);

	const handleDeleteMemory = (id: string, title: string) => {
		pendingDeleteMemoryId = id;
		pendingDeleteMemoryTitle = title;
		confirmDeleteMemoryShow = true;
	};
	const confirmDeleteMemory = () => {
		dispatch('deleteMemory', pendingDeleteMemoryId);
	};

	const entityBadgeStatus = (type: string): 'info' | 'success' | 'warning' | 'accent' => {
		switch (type) {
			case 'ddl_schema':
				return 'info';
			case 'sql_memory':
				return 'success';
			case 'documentation':
				return 'warning';
			case 'sql_example':
				return 'accent';
			default:
				return 'info';
		}
	};

	const entityLabel = (type: string): string => {
		switch (type) {
			case 'ddl_schema':
				return $i18n.t('DDL Schema');
			case 'sql_memory':
				return $i18n.t('SQL Few-shot');
			case 'documentation':
				return $i18n.t('Documentation');
			case 'sql_example':
				return $i18n.t('SQL Example');
			default:
				return type;
		}
	};

	// 생성자 구분 라벨 — embed short-circuit 으로 '최초 producer 기준' 고정.
	const originLabel = (origin?: string | null): string => {
		switch (origin) {
			case 'llm_auto':
				return $i18n.t('Auto');
			case 'user_manual':
				return $i18n.t('Manual');
			case 'schema_extraction':
				return $i18n.t('Extracted');
			default:
				return $i18n.t('Unknown');
		}
	};
</script>

<div class="cloo-extraction-tabs">
	{#if relationshipsReady || (mode === 'memory' && tableOptions.length > 1)}
		<!-- Relationship ERD trigger (read-only) + 메모리 탭 테이블 필터 드롭다운. -->
		<div class="cloo-extraction-tabs__rel mb-3 flex items-center gap-2 flex-wrap">
			{#if relationshipsReady}
				<button
					type="button"
					class="cloo-chip"
					on:click={() => dispatch('openRelationships')}
					title={$i18n.t('View table relationships')}
				>
					<svg viewBox="0 0 16 16" fill="none" class="size-3.5" aria-hidden="true">
						<rect x="1.5" y="2.5" width="5" height="4" rx="1" stroke="currentColor" stroke-width="1.2" />
						<rect x="9.5" y="9.5" width="5" height="4" rx="1" stroke="currentColor" stroke-width="1.2" />
						<path d="M6.5 4.5h2.5a1 1 0 0 1 1 1v4" stroke="currentColor" stroke-width="1.2" />
					</svg>
					<span>{$i18n.t('Relationships')}</span>
					<span class="cloo-chip__count">{relationshipCount}</span>
				</button>
			{/if}
			{#if mode === 'memory' && tableOptions.length > 1}
				<div class="cloo-table-filter">
					<Selector
						value={memoryTableFilter ?? ''}
						items={tableOptions}
						size="sm"
						searchEnabled
						placeholder={$i18n.t('Filter by table')}
						on:change={(e) =>
							dispatch('selectMemoryTable', { tableName: e.detail.value || null })}
					/>
				</div>
			{/if}
		</div>
	{/if}
	{#if loading}
		<div class="flex justify-center py-8">
			<Spinner className="size-5" />
		</div>
	{:else if mode === 'extracted'}
		{#if extractedTables.length === 0}
			<div class="flex flex-col items-center justify-center py-8 text-center">
				<p class="text-xs text-[var(--cloo-text-tertiary)]">
					{$i18n.t('No schemas extracted yet')}
				</p>
				<p class="text-[10px] text-[var(--cloo-text-tertiary)] mt-1">
					{$i18n.t('Test connection and extract schema')}
				</p>
			</div>
		{:else}
			<div class="flex flex-col">
				{#each extractedTables as table (table.id)}
					{@const memCount = memoryCountByTable[table.name] ?? 0}
					<div class="cloo-extraction-tabs__row group flex flex-col px-3 py-3 rounded">
						<div class="flex items-center gap-2">
							<span class="text-sm font-medium text-[var(--cloo-text-primary)] truncate flex-1">
								{table.name}
							</span>
							{#if table.column_count !== undefined}
								<span class="text-xs text-[var(--cloo-text-tertiary)] shrink-0">
									{table.column_count} {$i18n.t('cols')}
								</span>
							{/if}
							{#if memCount > 0}
								<!-- D: linked memory count → click jumps to Memory tab
								     pre-filtered to this table (dispatched event).
								     We display this even on hover-collapsed rows so
								     curation progress is always visible. -->
								<!-- svelte-ignore a11y-click-events-have-key-events -->
								<!-- svelte-ignore a11y-no-static-element-interactions -->
								<button
									type="button"
									class="cloo-mem-pill"
									on:click|stopPropagation={() =>
										dispatch('jumpToMemory', { tableName: table.name })}
									title={$i18n.t('Show linked memories')}
								>
									<span class="cloo-mem-pill__dot" />
									<span>{memCount} {$i18n.t('memories')}</span>
								</button>
							{/if}
							{#if canWrite}
								<Button
									kind="text"
									size="sm"
									className="opacity-0 group-hover:opacity-100 transition-opacity"
									on:click={() => handleDeleteTable(table.id, table.name)}
								>
									{$i18n.t('Remove')}
								</Button>
							{/if}
						</div>
						{#if table.description}
							<p class="text-xs text-[var(--cloo-text-tertiary)] mt-1 line-clamp-2">
								{table.description}
							</p>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{:else if mode === 'memory'}
		<!-- C: entity_type filter chips. Hidden until there's at least one
		     memory to filter — otherwise the chip row dominates an empty
		     state. Counts are tabular-numeric so the chips don't jitter as
		     memory is added/deleted. -->
		{#if memoryItems.length > 0}
			<div class="cloo-extraction-tabs__chips flex items-center gap-1.5 mb-3 flex-wrap">
				<button
					type="button"
					class="cloo-chip"
					class:is-active={memoryFilter === 'all'}
					on:click={() => (memoryFilter = 'all')}
				>
					<span>{$i18n.t('All')}</span>
					<span class="cloo-chip__count">{memoryCounts.all}</span>
				</button>
				{#each MEMORY_TYPE_ORDER as t}
					{#if memoryCounts[t] > 0}
						<button
							type="button"
							class="cloo-chip"
							class:is-active={memoryFilter === t}
							on:click={() => (memoryFilter = t)}
						>
							<span>{entityLabel(t)}</span>
							<span class="cloo-chip__count">{memoryCounts[t]}</span>
						</button>
					{/if}
				{/each}
				{#if canWrite}
					<div class="ml-auto flex items-center gap-1.5">
						<Button kind="outlined" size="sm" on:click={() => dispatch('cleanupUnused')}>
							{$i18n.t('Clean up unused')}
						</Button>
						<Button kind="filled" size="sm" on:click={() => dispatch('createMemory')}>
							{$i18n.t('Add Memory')}
						</Button>
					</div>
				{/if}
			</div>
		{:else if canWrite}
			<div class="flex items-center justify-end gap-2 mb-3">
				<Button kind="filled" size="sm" on:click={() => dispatch('createMemory')}>
					{$i18n.t('Add Memory')}
				</Button>
			</div>
		{/if}
		{#if memoryItems.length > 0 || canWrite}
			<!-- Area divider: separates the add/filter controls from the memory
			     list below, mirroring the DB All tab. Full-bleed (-mx-6). -->
			<div class="-mx-6 border-t border-[var(--cloo-border-subtle)] mb-3"></div>
		{/if}
		{#if showSortControl}
			<!-- 퓨샷만 볼 때 정렬: 최신순 / 참조순 -->
			<div class="flex items-center gap-1.5 mb-3">
				<span class="text-xs text-[var(--cloo-text-tertiary)]">{$i18n.t('Sort')}</span>
				<button
					type="button"
					class="cloo-chip"
					class:is-active={memorySort === 'recent'}
					on:click={() => (memorySort = 'recent')}
				>
					{$i18n.t('Newest')}
				</button>
				<button
					type="button"
					class="cloo-chip"
					class:is-active={memorySort === 'refs'}
					on:click={() => (memorySort = 'refs')}
				>
					{$i18n.t('Most referenced')}
				</button>
			</div>
		{/if}
		{#if memoryItems.length === 0}
			<div class="flex flex-col items-center justify-center py-8 text-center">
				<p class="text-xs text-[var(--cloo-text-tertiary)]">
					{$i18n.t('No memories yet')}
				</p>
			</div>
		{:else if filteredMemoryItems.length === 0}
			<div class="flex flex-col items-center justify-center py-8 text-center">
				<p class="text-xs text-[var(--cloo-text-tertiary)]">
					{$i18n.t('No memories in this category')}
				</p>
			</div>
		{:else}
			<div class="flex flex-col">
				{#each displayMemoryItems as item (item.memory_id)}
					<!-- svelte-ignore a11y-click-events-have-key-events -->
					<!-- svelte-ignore a11y-no-static-element-interactions -->
					<div
						class="cloo-extraction-tabs__row group flex items-center gap-2 px-3 py-2.5 rounded cursor-pointer"
						on:click={() => dispatch('openMemory', item.memory_id)}
					>
						<Badge
							status={entityBadgeStatus(item.entity_type)}
							size="sm"
							content={entityLabel(item.entity_type)}
						/>
						{#if item.origin || item.entity_type === 'documentation'}
							<span class="cloo-origin-tag shrink-0" title={$i18n.t('Creator')}>
								{originLabel(item.origin || 'user_manual')}
							</span>
						{/if}
						<div class="flex-1 min-w-0">
							<div class="text-sm text-[var(--cloo-text-primary)] truncate">
								{item.title}
							</div>
							{#if item.subtitle}
								<div class="text-xs text-[var(--cloo-text-tertiary)] truncate mt-0.5">
									{item.subtitle}
								</div>
							{/if}
						</div>
						{#if item.use_count != null}
							<span
								class="cloo-use-count shrink-0"
								title={$i18n.t('Injection events (retrieval), not LLM usage')}
							>
								{item.use_count}
								{$i18n.t('refs')}
							</span>
						{/if}
						{#if canWrite}
							<Button
								kind="text"
								size="sm"
								className="opacity-0 group-hover:opacity-100 transition-opacity"
								on:click={(e) => {
									e.stopPropagation();
									handleDeleteMemory(item.memory_id, item.title);
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</div>

<ConfirmDialog
	bind:show={confirmDeleteShow}
	title={$i18n.t('Remove extracted table')}
	message={confirmDeleteMessage}
	onConfirm={confirmDeleteTable}
/>

<ConfirmDialog
	bind:show={confirmDeleteMemoryShow}
	title={$i18n.t('Delete memory')}
	message={confirmDeleteMemoryMessage}
	onConfirm={confirmDeleteMemory}
/>

<style>
	.cloo-extraction-tabs__row:hover {
		background-color: var(--cloo-surface-hover);
	}

	.cloo-chip {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 26px;
		padding: 0 10px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-default, #1a1a1a);
		font-size: 12px;
		line-height: 1;
		cursor: pointer;
		transition: background-color 100ms ease, border-color 100ms ease, color 100ms ease;
	}
	.cloo-chip:hover {
		background: var(--cloo-surface-hover, #f5f5f7);
	}
	.cloo-chip.is-active {
		background: var(--cloo-text-default, #1a1a1a);
		color: var(--cloo-bg-surface, #fff);
		border-color: var(--cloo-text-default, #1a1a1a);
	}
	.cloo-chip__count {
		opacity: 0.65;
		font-variant-numeric: tabular-nums;
		font-size: 11px;
	}
	.cloo-chip.is-active .cloo-chip__count {
		opacity: 0.7;
	}

	.cloo-mem-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 22px;
		padding: 0 8px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		background: var(--cloo-bg-surface, #fff);
		color: var(--cloo-text-muted, #6b7280);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		cursor: pointer;
		flex-shrink: 0;
		transition: background-color 100ms ease, color 100ms ease, border-color 100ms ease;
	}
	.cloo-mem-pill:hover {
		background: var(--cloo-color-info-soft, #dbeafe);
		color: var(--cloo-color-info, #155dfc);
		border-color: var(--cloo-color-info, #155dfc);
	}
	.cloo-mem-pill__dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: currentColor;
		opacity: 0.7;
	}

	.cloo-table-filter {
		min-width: 200px;
		max-width: 280px;
	}

	.cloo-origin-tag {
		font-size: 10px;
		line-height: 1;
		padding: 2px 6px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		color: var(--cloo-text-muted, #6b7280);
		white-space: nowrap;
	}


	.cloo-use-count {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 11px;
		line-height: 1;
		color: var(--cloo-text-muted, #6b7280);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
</style>
