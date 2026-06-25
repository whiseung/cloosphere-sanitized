<script lang="ts">
	import { getContext, createEventDispatcher, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { models } from '$lib/stores';

	import {
		getKnowledgeGraphLinkEdgeTypeCatalog,
		putKnowledgeGraphLinkEdgeTypeCatalog,
		recommendKnowledgeGraphLinkEdgeTypes,
		type KGEdgeTypeCatalogItem
	} from '$lib/apis/knowledge-graph';
	import { getGlossaryById } from '$lib/apis/glossary';
	import {
		DEFAULT_EDGE_TYPE_SEEDS,
		DEFAULT_EDGE_TYPE_SEED_KEYS,
		buildSeedRow
	} from './defaultEdgeTypes';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let kgId: string;
	export let linkId: string;
	export let linkTitle: string = '';
	export let glossaryId: string = '';
	export let defaultModelId: string = '';

	type Row = KGEdgeTypeCatalogItem & {
		_isNew?: boolean;
	};

	let aiModelId: string = '';
	let locked: boolean = false;
	let loading = false;
	let saving = false;
	let recommending = false;

	let items: Row[] = [];
	let initialJson = '';

	// 링크의 글로서리 카테고리 목록 (scope selector 옵션용)
	let categories: string[] = [];
	let lastLoadedGlossaryId = '';

	// Selector 용 모델 옵션 (preset/arena 제외 + 기본 옵션)
	$: modelSelectorItems = [
		{ value: '', label: $i18n.t('Default model') },
		...(($models ?? [])
			.filter((m: any) => !m?.preset && !(m?.arena ?? false))
			.map((m: any) => ({ value: m.id, label: m.name })))
	];

	// ConfirmDialog 상태 — native confirm() 대체용
	let showConfirmDialog = false;
	let confirmTitle = '';
	let confirmMessage = '';
	let confirmLabel = '';
	let confirmAction: () => void | Promise<void> = () => {};
	const askConfirm = (opts: {
		title: string;
		message: string;
		confirmLabel?: string;
		onConfirm: () => void | Promise<void>;
	}) => {
		confirmTitle = opts.title;
		confirmMessage = opts.message;
		confirmLabel = opts.confirmLabel ?? $i18n.t('Confirm');
		confirmAction = opts.onConfirm;
		showConfirmDialog = true;
	};

	const normalizeItem = (raw: KGEdgeTypeCatalogItem): Row => ({
		key: raw.key,
		display_name: raw.display_name || raw.key,
		description: raw.description || '',
		examples: raw.examples ?? [],
		source: raw.source || 'manual',
		recommendation_reason: raw.recommendation_reason ?? null,
		category: raw.category ?? null,
		src_category: raw.src_category ?? null,
		dst_category: raw.dst_category ?? null,
		created_at: raw.created_at,
		updated_at: raw.updated_at
	});

	const snapshotJson = (rows: Row[], lockedFlag: boolean) =>
		JSON.stringify({
			locked: lockedFlag,
			items: rows.map((r) => ({
				key: r.key,
				display_name: r.display_name,
				description: r.description,
				source: r.source,
				recommendation_reason: r.recommendation_reason,
				category: r.category,
				src_category: r.src_category,
				dst_category: r.dst_category
			}))
		});

	// Scope selector value ↔ (category | src/dst_category) 변환
	// value format:
	//   ""            → universal
	//   "in:약품명"    → intra (category="약품명")
	//   "x:약품명>성분명" → cross (src=약품명, dst=성분명)
	const scopeToValue = (row: Row): string => {
		if (row.src_category && row.dst_category && row.src_category !== row.dst_category) {
			return `x:${row.src_category}>${row.dst_category}`;
		}
		if (row.category) {
			return `in:${row.category}`;
		}
		return '';
	};

	const applyScopeValue = (row: Row, v: string): Row => {
		if (!v) {
			return { ...row, category: null, src_category: null, dst_category: null };
		}
		if (v.startsWith('in:')) {
			return {
				...row,
				category: v.slice(3),
				src_category: null,
				dst_category: null
			};
		}
		if (v.startsWith('x:')) {
			const [src, dst] = v.slice(2).split('>');
			return { ...row, category: null, src_category: src, dst_category: dst };
		}
		return row;
	};

	const buildScopeOptions = (): { value: string; label: string }[] => {
		const opts: { value: string; label: string }[] = [
			{ value: '', label: $i18n.t('(Universal — any category)') }
		];
		for (const cat of categories) {
			opts.push({ value: `in:${cat}`, label: `${cat} ${$i18n.t('(intra)')}` });
		}
		for (const src of categories) {
			for (const dst of categories) {
				if (src === dst) continue;
				opts.push({
					value: `x:${src}>${dst}`,
					label: `${src} → ${dst}`
				});
			}
		}
		return opts;
	};

	$: scopeOptions = categories.length > 0 ? buildScopeOptions() : [];

	$: dirty = snapshotJson(items, locked) !== initialJson;

	const loadCategories = async () => {
		if (!glossaryId || glossaryId === lastLoadedGlossaryId) return;
		try {
			const g = await getGlossaryById(localStorage.token, glossaryId);
			const entries = ((g as any)?.data?.entries ?? []) as Array<{
				category?: string | null;
			}>;
			const seen = new Set<string>();
			const cats: string[] = [];
			for (const e of entries) {
				const c = (e?.category || '').trim();
				if (c && !seen.has(c)) {
					seen.add(c);
					cats.push(c);
				}
			}
			categories = cats.sort();
			lastLoadedGlossaryId = glossaryId;
		} catch (e) {
			console.error('failed to load glossary categories', e);
			categories = [];
		}
	};

	const loadCatalog = async () => {
		loading = true;
		try {
			await loadCategories();
			const catalog = await getKnowledgeGraphLinkEdgeTypeCatalog(
				localStorage.token,
				kgId,
				linkId
			);
			items = (catalog.items || []).map(normalizeItem);
			// locked 이 null 이면 아직 저장된 적 없음 → 기본 true (추출을 카탈로그로 제한)
			locked = catalog.locked === null || catalog.locked === undefined ? true : catalog.locked;
			// 링크에 저장된 recommend_model_id 우선, 없으면 header 기본값
			aiModelId = catalog.recommend_model_id || defaultModelId || '';
			initialJson = snapshotJson(items, locked);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Failed to load edge type catalog'));
		} finally {
			loading = false;
		}
	};

	$: if (show && kgId && linkId) {
		loadCatalog();
	}

	const sourceBadgeClass = (src: string) => {
		switch (src) {
			case 'llm':
				return 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300';
			case 'manual':
				return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
			case 'filter':
				return 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300';
			default:
				return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
		}
	};

	const sourceLabel = (src: string) => {
		switch (src) {
			case 'llm':
				return $i18n.t('LLM');
			case 'manual':
				return $i18n.t('Manual');
			case 'filter':
				return $i18n.t('Filter');
			default:
				return $i18n.t('System');
		}
	};

	// Selector 값 기반 scope 변경 (Selector 는 e.detail.value 로 값을 준다)
	const handleScopeValueChange = (index: number, v: string) => {
		items = items.map((r, idx) => (idx === index ? applyScopeValue(r, v) : r));
	};

	const handleAddRow = () => {
		items = [
			...items,
			{
				key: '',
				display_name: '',
				description: '',
				examples: [],
				source: 'manual',
				recommendation_reason: null,
				category: null,
				src_category: null,
				dst_category: null,
				_isNew: true
			}
		];
	};

	const handleRemoveRow = (index: number) => {
		items = items.filter((_, i) => i !== index);
	};

	const sanitizeKey = (raw: string) =>
		raw
			.toLowerCase()
			.trim()
			.replace(/[^a-z0-9_]+/g, '_')
			.replace(/^_+|_+$/g, '');

	const validateAndCollect = (): { items: Partial<KGEdgeTypeCatalogItem>[] } | null => {
		const seen = new Set<string>();
		const out: Partial<KGEdgeTypeCatalogItem>[] = [];
		for (const row of items) {
			const key = sanitizeKey(row.key || '');
			if (!key) {
				toast.error($i18n.t('Edge type key cannot be empty'));
				return null;
			}
			if (seen.has(key)) {
				toast.error($i18n.t('Duplicate edge type key: {{key}}', { key }));
				return null;
			}
			seen.add(key);
			out.push({
				key,
				display_name: row.display_name?.trim() || key,
				description: row.description?.trim() || '',
				source: row.source || 'manual',
				recommendation_reason: row.recommendation_reason ?? null,
				category: row.category ?? null,
				src_category: row.src_category ?? null,
				dst_category: row.dst_category ?? null
			});
		}
		return { items: out };
	};

	const handleSave = async () => {
		const collected = validateAndCollect();
		if (!collected) return;
		saving = true;
		try {
			const result = await putKnowledgeGraphLinkEdgeTypeCatalog(
				localStorage.token,
				kgId,
				linkId,
				{
					items: collected.items,
					locked,
					recommend_model_id: aiModelId || null
				}
			);
			items = (result.items || []).map(normalizeItem);
			locked = !!result.locked;
			if (result.recommend_model_id !== undefined) {
				aiModelId = result.recommend_model_id || '';
			}
			initialJson = snapshotJson(items, locked);
			toast.success($i18n.t('Edge type catalog saved'));
			dispatch('saved', { items: result.items, locked: result.locked });
			show = false;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Failed to save edge type catalog'));
		} finally {
			saving = false;
		}
	};

	/**
	 * 시드 주입 — 기본 엣지 타입을 현재 items 의 최상단에 주입한다.
	 *
	 * 이미 같은 key 가 items 에 있으면 건너뛰어 사용자의 이전 편집/삭제를 존중한다.
	 * (단, 한 세션에서 사용자가 삭제한 후 같은 모달 open 상태에서 recommend 를 다시
	 * 누르면 seed 가 없으니까 re-inject 된다. 저장 후 재오픈하면 원복되지 않음 —
	 * 저장된 상태에서 seed key 가 있는지로 판단.)
	 */
	const _injectSeeds = (baseItems: Row[]): Row[] => {
		const existingKeys = new Set(baseItems.map((r) => r.key));
		const seedRows: Row[] = [];
		for (const seed of DEFAULT_EDGE_TYPE_SEEDS) {
			if (existingKeys.has(seed.key)) continue;
			const row = buildSeedRow(seed, (k) => $i18n.t(k)) as Row;
			(row as any)._isNew = true;
			seedRows.push(row);
		}
		return [...seedRows, ...baseItems];
	};

	const runRecommend = async () => {
		recommending = true;
		try {
			const candidates = await recommendKnowledgeGraphLinkEdgeTypes(
				localStorage.token,
				kgId,
				linkId,
				{
					model_id: aiModelId || undefined,
					max_candidates: 12
				}
			);
			if (!candidates.length) {
				toast.info($i18n.t('No edge type recommendations returned'));
				return;
			}

			// 기존 LLM 항목 제거, manual 유지
			const manualItems = items.filter((r) => r.source !== 'llm');
			const manualKeys = new Set(manualItems.map((r) => r.key));

			// 새 후보 추가 (manual 과 키 충돌 시 skip)
			const additions: Row[] = [];
			for (const c of candidates) {
				if (!c.key || manualKeys.has(c.key)) continue;
				additions.push({
					key: c.key,
					display_name: c.display_name || c.key,
					description: c.description || '',
					examples: [],
					source: 'llm',
					recommendation_reason: c.recommendation_reason ?? null,
					category: c.category ?? null,
					src_category: c.src_category ?? null,
					dst_category: c.dst_category ?? null,
					_isNew: true
				});
			}

			// 시드는 최상단 → LLM 추천 → manual 순서
			items = _injectSeeds([...additions, ...manualItems]);
			toast.success(
				$i18n.t('{{count}} candidates loaded', { count: additions.length })
			);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Failed to recommend edge types'));
		} finally {
			recommending = false;
		}
	};

	const handleRecommend = () => {
		const existingLlm = items.filter((r) => r.source === 'llm');
		if (existingLlm.length === 0) {
			runRecommend();
			return;
		}
		askConfirm({
			title: $i18n.t('Replace existing recommendations?'),
			message: $i18n.t(
				'This will replace {{count}} existing LLM recommendation(s). Manual entries will be kept.',
				{ count: existingLlm.length }
			),
			confirmLabel: $i18n.t('Replace'),
			onConfirm: runRecommend
		});
	};

	const handleClose = () => {
		if (!dirty) {
			show = false;
			return;
		}
		askConfirm({
			title: $i18n.t('Close without saving?'),
			message: $i18n.t('You have unsaved changes. Close anyway?'),
			confirmLabel: $i18n.t('Close'),
			onConfirm: () => {
				show = false;
			}
		});
	};
</script>

<Modal bind:show size="lg" on:close={handleClose}>
	<div class="p-5 flex flex-col gap-4">
		<!-- Header -->
		<div class="flex items-start justify-between">
			<div>
				<div class="text-lg font-semibold text-gray-900 dark:text-gray-100">
					{$i18n.t('Edge Type Settings')}
					{#if linkTitle}
						<span class="text-sm font-normal text-gray-500 dark:text-gray-400 ml-1">
							— {linkTitle}
						</span>
					{/if}
				</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
					{$i18n.t(
						'Define the edge type catalog used when extracting from this link. LLM extraction will be restricted to this catalog when locked.'
					)}
				</div>
			</div>
			<button
				type="button"
				class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={handleClose}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="size-5" />
			</button>
		</div>

		<!-- Locked 스위치 (카탈로그를 vocabulary 화이트리스트로 강제할지) -->
		<div
			class="rounded border border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-850/40 px-3 py-2.5 flex items-center justify-between gap-3"
		>
			<div class="flex-1 min-w-0">
				<div class="text-xs font-medium text-gray-700 dark:text-gray-200">
					{$i18n.t('Restrict extraction to this catalog')}
				</div>
				<div class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
					{$i18n.t(
						'When on, extraction LLM may only use edge types in this catalog. When off, the catalog is a loose vocabulary hint and new types may be added automatically during extraction.'
					)}
				</div>
			</div>
			<Switch bind:state={locked} />
		</div>

		<!-- Suggest from LLM: 설명(위) + 모델/버튼(아래) 2줄 -->
		<div
			class="rounded border border-gray-200 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-850/40 px-3 py-2.5 flex flex-col gap-2"
		>
			<div class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
				{$i18n.t(
					"Let the LLM analyze this link's glossary and KBs and propose edge type candidates. Manual entries are preserved. Use a high-performance model for better suggestions."
				)}
			</div>
			<div
				class="flex items-center gap-2 justify-end flex-wrap"
				title={$i18n.t(
					'Model used only for edge type suggestions. Entity sync uses a separate model.'
				)}
			>
				<div class="w-full sm:w-auto sm:min-w-[220px]">
					<Selector
						value={aiModelId}
						items={modelSelectorItems}
						size="sm"
						searchEnabled
						placeholder={$i18n.t('Default model')}
						portal="body"
						contentClassName="z-[10000]"
						on:change={(e) => {
							aiModelId = e.detail.value;
						}}
					/>
				</div>
				<Button
					kind="outlined"
					size="sm"
					loading={recommending}
					disabled={loading}
					on:click={handleRecommend}
				>
					<svelte:fragment slot="prefix">
						<SparklesSolid className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Suggest from LLM')}
				</Button>
			</div>
		</div>

		<!-- Catalog list -->
		<div class="border border-gray-200 dark:border-gray-700 rounded overflow-hidden">
			<div class="max-h-[50vh] overflow-y-auto">
				{#if loading}
					<div class="flex items-center justify-center py-10">
						<Spinner className="size-5" />
					</div>
				{:else if items.length === 0}
					<div class="text-xs text-gray-500 italic px-3 py-8 text-center">
						{$i18n.t('No edge types yet. Add one or get LLM recommendations.')}
					</div>
				{:else}
					{#each items as row, i (row.key + '_' + i)}
						<div
							class="flex flex-col gap-2 px-3 py-3 border-b border-gray-100 dark:border-gray-850 text-xs hover:bg-gray-50/40 dark:hover:bg-gray-850/30"
						>
							<!-- Top row: key + name + scope + source badge + delete (모두 h-8 정렬) -->
							<div class="flex items-center gap-2">
								<div class="flex-1 min-w-0">
									<Input
										bind:value={row.key}
										size="sm"
										placeholder="snake_case_key"
									/>
								</div>
								<div class="flex-1 min-w-0">
									<Input
										bind:value={row.display_name}
										size="sm"
										placeholder={$i18n.t('Display name')}
									/>
								</div>
								{#if scopeOptions.length > 0}
									<div
										class="shrink-0 w-[160px]"
										title={$i18n.t(
											'Edge type scope — universal, single category, or cross-category'
										)}
									>
										<Selector
											value={scopeToValue(row)}
											items={scopeOptions}
											size="sm"
											portal="body"
											contentClassName="z-[10000]"
											on:change={(e) => handleScopeValueChange(i, e.detail.value)}
										/>
									</div>
								{/if}
								<span
									class="h-8 inline-flex items-center text-[9px] font-semibold uppercase px-1.5 rounded shrink-0 {sourceBadgeClass(
										row.source
									)}"
								>
									{sourceLabel(row.source)}
								</span>
								<button
									type="button"
									class="h-8 w-8 flex items-center justify-center text-gray-400 hover:text-red-500 transition shrink-0"
									on:click={() => handleRemoveRow(i)}
									title={$i18n.t('Delete')}
									aria-label={$i18n.t('Delete')}
								>
									<XMark className="size-4" />
								</button>
							</div>

							<!-- Description (full width, multi-line) -->
							<div class="flex flex-col gap-1">
								<label
									class="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
								>
									{$i18n.t('Description')}
								</label>
								<textarea
									rows="2"
									class="w-full bg-transparent border border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600 focus:border-gray-400 dark:focus:border-gray-500 rounded px-2 py-1.5 outline-none text-gray-700 dark:text-gray-200 leading-relaxed resize-y"
									placeholder={$i18n.t('Describe what this edge type means and the direction it implies.')}
									bind:value={row.description}
								></textarea>
							</div>

							<!-- Recommendation reason (full width, always visible if present) -->
							{#if row.recommendation_reason}
								<div class="flex flex-col gap-1">
									<div
										class="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-violet-500 dark:text-violet-400"
									>
										<SparklesSolid className="size-3" />
										<span>{$i18n.t('Recommendation Reason')}</span>
									</div>
									<div
										class="text-[11px] italic text-gray-600 dark:text-gray-400 leading-relaxed pl-2 border-l-2 border-violet-300 dark:border-violet-800 whitespace-pre-wrap"
									>
										{row.recommendation_reason}
									</div>
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>

			<div
				class="px-3 py-2 border-t border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-850/30"
			>
				<button
					type="button"
					class="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
					on:click={handleAddRow}
				>
					<Plus className="size-3.5" strokeWidth="2.5" />
					<span>{$i18n.t('Add row')}</span>
				</button>
			</div>
		</div>

		{#if items.length > 0}
			<div class="text-[10px] text-gray-400 dark:text-gray-500">
				{$i18n.t(
					'Note: deleting an entry from the catalog does not delete existing edges that use it. Existing edges remain in the graph.'
				)}
			</div>
		{/if}

		<!-- Footer -->
		<div class="flex justify-end gap-2 pt-1">
			<Button kind="outlined" size="md" on:click={handleClose}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={saving} on:click={handleSave}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
</Modal>

<ConfirmDialog
	bind:show={showConfirmDialog}
	title={confirmTitle}
	message={confirmMessage}
	{confirmLabel}
	onConfirm={() => confirmAction()}
/>
