<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import {
		getUnusedDbSphereMemories,
		bulkDeleteDbSphereMemories,
		type UnusedMemoryItem
	} from '$lib/apis/dbsphere';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let dbsphereId = '';
	export let canWrite = false;

	let loading = false;
	let deleting = false;
	let items: UnusedMemoryItem[] = [];
	let loggingReady = false;
	let graceDays = 180;
	let selected: Record<string, boolean> = {};
	let confirmShow = false;

	$: selectedIds = Object.keys(selected).filter((k) => selected[k]);
	$: allSelected = items.length > 0 && selectedIds.length === items.length;
	$: confirmMessage = $i18n
		.t('Delete {{count}} selected few-shots? This cannot be undone.')
		.replace('{{count}}', String(selectedIds.length));

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

	const load = async () => {
		if (!dbsphereId) return;
		loading = true;
		selected = {};
		try {
			const res = await getUnusedDbSphereMemories(localStorage.token, dbsphereId);
			if (res && res.success) {
				items = res.memories ?? [];
				loggingReady = res.logging_ready;
				graceDays = res.grace_days ?? 14;
			} else {
				items = [];
				loggingReady = false;
			}
		} catch (e) {
			toast.error((e as string) || $i18n.t('Failed to load unused few-shots'));
			items = [];
			loggingReady = false;
		}
		loading = false;
	};

	const toggleOne = (id: string) => {
		selected = { ...selected, [id]: !selected[id] };
	};

	const toggleAll = () => {
		if (allSelected) {
			selected = {};
		} else {
			const next: Record<string, boolean> = {};
			for (const it of items) next[it.memory_id] = true;
			selected = next;
		}
	};

	const handleDelete = async () => {
		if (selectedIds.length === 0) return;
		deleting = true;
		try {
			const res = await bulkDeleteDbSphereMemories(localStorage.token, dbsphereId, selectedIds);
			const deleted = res?.deleted ?? 0;
			toast.success(
				$i18n.t('{{count}} few-shots deleted').replace('{{count}}', String(deleted))
			);
			dispatch('deleted');
			await load();
		} catch (e) {
			toast.error((e as string) || $i18n.t('Failed to delete few-shots'));
		}
		deleting = false;
	};

	// show 가 true 로 바뀔 때만 로드.
	let lastShow = false;
	$: if (show && !lastShow) {
		lastShow = true;
		load();
	} else if (!show && lastShow) {
		lastShow = false;
	}
</script>

<Modal bind:show size="md">
	<div class="px-5 py-4 flex flex-col gap-3 text-[var(--cloo-text-default)]">
		<div class="flex items-center justify-between">
			<div class="text-lg font-semibold">{$i18n.t('Clean up unused few-shots')}</div>
			<button
				type="button"
				class="text-[var(--cloo-text-tertiary)] hover:text-[var(--cloo-text-default)]"
				on:click={() => (show = false)}
				aria-label={$i18n.t('Close')}
			>
				✕
			</button>
		</div>

		<!-- 거짓 안심 방지 caveat (H-S2-2): 참조횟수는 품질 지표가 아님 + 수동검토 강조. -->
		<div
			class="text-xs rounded-[var(--cloo-radius-default)] px-3 py-2 leading-relaxed"
			style="background: var(--cloo-color-warning-soft, #fef9c3); color: var(--cloo-text-default);"
		>
			{$i18n.t(
				'"Unused" means never retrieved into a prompt — not LLM-verified as useless. Recently added few-shots may simply have had no matching question yet. Review before deleting.'
			)}
			<br />
			{$i18n.t('Only SQL Few-shots are listed; DDL/Documentation are auto-referenced.')}
		</div>

		{#if loading}
			<div class="flex justify-center py-10"><Spinner className="size-5" /></div>
		{:else if !loggingReady}
			<div class="flex flex-col items-center justify-center py-10 text-center gap-1">
				<p class="text-sm text-[var(--cloo-text-default)]">
					{$i18n.t('Not enough reference data yet')}
				</p>
				<p class="text-xs text-[var(--cloo-text-tertiary)]">
					{$i18n
						.t('Reference logging needs about {{days}} days of data before this is reliable.')
						.replace('{{days}}', String(graceDays))}
				</p>
			</div>
		{:else if items.length === 0}
			<div class="flex flex-col items-center justify-center py-10 text-center">
				<p class="text-sm text-[var(--cloo-text-tertiary)]">
					{$i18n.t('No unused few-shots to clean up')}
				</p>
			</div>
		{:else}
			<div class="flex items-center gap-2 px-1">
				<Checkbox
					state={allSelected ? 'checked' : 'unchecked'}
					on:change={toggleAll}
				/>
				<span class="text-xs text-[var(--cloo-text-tertiary)]">
					{$i18n.t('Select all')} ({items.length})
				</span>
			</div>
			<div class="flex flex-col gap-1 max-h-[48vh] overflow-y-auto">
				{#each items as it (it.memory_id)}
					<!-- svelte-ignore a11y-click-events-have-key-events -->
					<!-- svelte-ignore a11y-no-static-element-interactions -->
					<div
						class="flex items-start gap-2 px-2 py-2 rounded cursor-pointer hover:bg-[var(--cloo-surface-hover)]"
						on:click={() => toggleOne(it.memory_id)}
					>
						<div class="pt-0.5">
							<Checkbox state={selected[it.memory_id] ? 'checked' : 'unchecked'} />
						</div>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2">
								<span class="text-sm text-[var(--cloo-text-primary)] truncate">
									{it.content || '-'}
								</span>
								{#if it.origin}
									<span class="cloo-origin-tag shrink-0">{originLabel(it.origin)}</span>
								{/if}
							</div>
							{#if it.sql}
								<div class="text-xs text-[var(--cloo-text-tertiary)] truncate mt-0.5 font-mono">
									{it.sql}
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<div class="flex items-center justify-end gap-2 mt-1">
			<Button kind="outlined" size="md" on:click={() => (show = false)}>
				{$i18n.t('Cancel')}
			</Button>
			{#if canWrite}
				<Button
					kind="filled"
					size="md"
					status="error"
					disabled={selectedIds.length === 0}
					loading={deleting}
					on:click={() => (confirmShow = true)}
				>
					{$i18n.t('Delete selected')} ({selectedIds.length})
				</Button>
			{/if}
		</div>
	</div>
</Modal>

<ConfirmDialog
	bind:show={confirmShow}
	title={$i18n.t('Delete few-shots')}
	message={confirmMessage}
	onConfirm={handleDelete}
/>

<style>
	.cloo-origin-tag {
		font-size: 10px;
		line-height: 1;
		padding: 2px 6px;
		border-radius: 999px;
		border: 1px solid var(--cloo-border-subtle, #e3e4e9);
		color: var(--cloo-text-muted, #6b7280);
		white-space: nowrap;
	}
</style>
