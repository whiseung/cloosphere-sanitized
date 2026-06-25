<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getKnowledgeGraphLinkNodeFilters,
		putKnowledgeGraphLinkNodeFilters
	} from '$lib/apis/knowledge-graph';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let kgId: string;
	export let linkId: string;
	export let linkTitle: string = '';
	/** 이 링크에 연결된 KB 목록. `filter_schema` 를 순회해서 체크박스 목록을 만든다. */
	export let linkedKbs: Array<{ id: string; name: string; meta?: any }> = [];

	type FilterRow = {
		kb_id: string;
		kb_name: string;
		slot: string;
		label: string;
		type: string;
		/** KB 에서 현재 추출 가능한 상태인지 (false 면 disabled + 힌트) */
		active: boolean;
	};

	let loading = false;
	let saving = false;
	let selected: Set<string> = new Set(); // "kb_id::slot" 조합

	// 필터 타입별 카테고리
	const HIGH_CARDINALITY = new Set(['int', 'date']);
	const NODE_ELIGIBLE_TYPES = new Set([
		'string',
		'enum',
		'collection',
		'int',
		'date'
	]);
	// glossary 는 앵커 매핑 전용 → 여기선 제외

	const keyOf = (kbId: string, slot: string) => `${kbId}::${slot}`;

	// 연결된 KB 들의 filter_schema 순회 → 후보 필터 행 생성
	$: rows = (() => {
		const out: FilterRow[] = [];
		for (const kb of linkedKbs ?? []) {
			const schema = (kb?.meta?.filter_schema ?? []) as any[];
			for (const f of schema) {
				if (!f || typeof f !== 'object') continue;
				const t = f.type;
				if (t === 'glossary') continue; // 앵커 매핑 전용
				if (!NODE_ELIGIBLE_TYPES.has(t)) continue;
				const slot = f.slot;
				if (!slot) continue;
				// "active": KB 에서 실제로 추출 가능한지 — 값이 항상 있다고 가정 (KB 필터가 켜져 있으면 추출)
				// 향후 KB 쪽에서 per-filter on/off 토글이 생기면 여기서 체크. 지금은 항상 true.
				out.push({
					kb_id: kb.id,
					kb_name: kb.name,
					slot,
					label: f.label || slot,
					type: t,
					active: true
				});
			}
		}
		return out;
	})();

	// KB 별로 그룹핑
	$: groupedRows = (() => {
		const groups: { kb_id: string; kb_name: string; rows: FilterRow[] }[] = [];
		const byId: Record<string, (typeof groups)[number]> = {};
		for (const r of rows) {
			if (!byId[r.kb_id]) {
				byId[r.kb_id] = { kb_id: r.kb_id, kb_name: r.kb_name, rows: [] };
				groups.push(byId[r.kb_id]);
			}
			byId[r.kb_id].rows.push(r);
		}
		return groups;
	})();

	$: if (show && kgId && linkId) {
		loadFilters();
	}

	const loadFilters = async () => {
		loading = true;
		try {
			const res = await getKnowledgeGraphLinkNodeFilters(
				localStorage.token,
				kgId,
				linkId
			);
			selected = new Set(
				(res.slots ?? []).map((s) => keyOf(s.kb_id, s.slot))
			);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Failed to load node settings'));
		} finally {
			loading = false;
		}
	};

	const toggleRow = (r: FilterRow) => {
		const k = keyOf(r.kb_id, r.slot);
		const next = new Set(selected);
		if (next.has(k)) next.delete(k);
		else next.add(k);
		selected = next;
	};

	const toggleKbAll = (kbId: string, turnOn: boolean) => {
		const next = new Set(selected);
		for (const r of rows.filter((x) => x.kb_id === kbId)) {
			const k = keyOf(r.kb_id, r.slot);
			if (turnOn) next.add(k);
			else next.delete(k);
		}
		selected = next;
	};

	const handleSave = async () => {
		saving = true;
		try {
			const slots = Array.from(selected).map((k) => {
				const [kb_id, slot] = k.split('::');
				return { kb_id, slot };
			});
			await putKnowledgeGraphLinkNodeFilters(
				localStorage.token,
				kgId,
				linkId,
				{ slots }
			);
			toast.success($i18n.t('Node settings saved'));
			dispatch('saved', { slots });
			show = false;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || e?.message || $i18n.t('Failed to save node settings'));
		} finally {
			saving = false;
		}
	};
</script>

<Modal bind:show size="md">
	<div class="flex flex-col gap-3 p-4 w-full">
		<div class="flex items-center justify-between">
			<div class="flex flex-col">
				<div class="text-base font-semibold text-[var(--cloo-text-primary)]">
					{$i18n.t('Node settings')}
				</div>
				{#if linkTitle}
					<div class="text-xs text-[var(--cloo-text-muted)]">{linkTitle}</div>
				{/if}
			</div>
			<button
				class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm"
				on:click={() => (show = false)}
				aria-label={$i18n.t('Close')}>✕</button
			>
		</div>

		<div class="text-xs text-[var(--cloo-text-muted)] leading-relaxed">
			{$i18n.t(
				'Select which KB filter values become nodes in this knowledge graph link. Glossary filters are already used as anchors and are not listed here.'
			)}
		</div>

		<div class="border border-gray-200 dark:border-gray-700 rounded overflow-hidden">
			<div class="max-h-[50vh] overflow-y-auto">
				{#if loading}
					<div class="flex items-center justify-center py-10">
						<Spinner className="size-5" />
					</div>
				{:else if groupedRows.length === 0}
					<div class="text-xs text-gray-500 italic px-3 py-8 text-center">
						{$i18n.t(
							'No eligible filters. Add non-glossary filters (string / enum / collection / number / date) to the linked KBs.'
						)}
					</div>
				{:else}
					{#each groupedRows as group (group.kb_id)}
						<div class="border-b border-gray-100 dark:border-gray-850 last:border-b-0">
							<div
								class="flex items-center justify-between px-3 py-2 bg-gray-50/60 dark:bg-gray-850/40"
							>
								<div class="text-xs font-semibold text-[var(--cloo-text-primary)] truncate">
									{group.kb_name}
								</div>
								<div class="flex items-center gap-2 text-[10px] text-gray-500 dark:text-gray-400">
									<button
										class="hover:text-gray-700 dark:hover:text-gray-200 underline-offset-2 hover:underline"
										on:click={() => toggleKbAll(group.kb_id, true)}
									>{$i18n.t('Select all')}</button>
									<span>/</span>
									<button
										class="hover:text-gray-700 dark:hover:text-gray-200 underline-offset-2 hover:underline"
										on:click={() => toggleKbAll(group.kb_id, false)}
									>{$i18n.t('Clear')}</button>
								</div>
							</div>
							{#each group.rows as r (r.slot)}
								{@const k = keyOf(r.kb_id, r.slot)}
								<label
									class="flex items-center gap-2 px-3 py-2 text-xs cursor-pointer hover:bg-gray-50/40 dark:hover:bg-gray-850/30"
								>
									<Checkbox
										state={selected.has(k) ? 'checked' : 'unchecked'}
										on:change={() => toggleRow(r)}
									/>
									<span class="flex-1 min-w-0">
										<span class="text-[var(--cloo-text-primary)]">{r.label}</span>
										<span class="ml-1 text-gray-400 dark:text-gray-500">· {r.slot}</span>
									</span>
									<span
										class="inline-flex items-center text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
									>
										{r.type}
									</span>
									{#if HIGH_CARDINALITY.has(r.type)}
										<span
											class="text-amber-600 dark:text-amber-400"
											title={$i18n.t(
												'Values with high cardinality (number/date) may create many nodes'
											)}>⚠</span
										>
									{/if}
								</label>
							{/each}
						</div>
					{/each}
				{/if}
			</div>
		</div>

		<div class="flex justify-end gap-2 mt-2">
			<Button kind="outlined" size="md" on:click={() => (show = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={saving} on:click={handleSave}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
</Modal>
