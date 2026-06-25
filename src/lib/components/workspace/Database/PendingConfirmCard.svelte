<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import type { SqlPendingPayload } from '$lib/apis/dbsphere';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let pending: SqlPendingPayload | null = null;
	export let busy: boolean = false;
	export let onCommit: () => void | Promise<void> = () => {};
	export let onRollback: () => void | Promise<void> = () => {};

	let committing = false;
	let rolling = false;

	const handleCommit = async () => {
		if (committing || rolling || busy) return;
		committing = true;
		try {
			await onCommit();
		} finally {
			committing = false;
		}
	};

	const handleRollback = async () => {
		if (committing || rolling || busy) return;
		rolling = true;
		try {
			await onRollback();
		} finally {
			rolling = false;
		}
	};

	const formatPreview = (preview: unknown): string => {
		if (preview === null || preview === undefined) return '';
		if (typeof preview === 'string') return preview;
		try {
			return JSON.stringify(preview, null, 2);
		} catch {
			return String(preview);
		}
	};

	$: disabled = committing || rolling || busy;
</script>

{#if pending}
	<div
		class="cloo-pending-confirm border border-[var(--cloo-color-warning-border,var(--cloo-border-default))] bg-[var(--cloo-color-warning-soft,var(--cloo-bg-surface))] rounded-[var(--cloo-radius-default)] p-3 m-2"
		role="region"
		aria-label={$i18n.t('Pending confirmation')}
	>
		<div class="flex items-center gap-2 mb-2">
			<Badge status="warning" size="sm" content={$i18n.t('Pending confirmation')} />
			<span class="text-xs text-[var(--cloo-text-muted)]">
				{$i18n.t('Expires in')}: {pending.expires_in_s}s
			</span>
		</div>

		<div class="text-xs text-[var(--cloo-text-muted)] mb-1">{$i18n.t('SQL')}</div>
		<pre
			class="text-xs font-mono bg-[var(--cloo-bg-surface)] border border-[var(--cloo-border-subtle)] rounded p-2 max-h-32 overflow-auto whitespace-pre-wrap break-all"
		>{pending.sql}</pre>

		{#if pending.affected_preview !== null && pending.affected_preview !== undefined && pending.affected_preview !== ''}
			<div class="mt-2">
				<div class="text-xs text-[var(--cloo-text-muted)] mb-1">{$i18n.t('Affected rows')}</div>
				<pre
					class="text-xs font-mono bg-[var(--cloo-bg-surface)] border border-[var(--cloo-border-subtle)] rounded p-2 max-h-32 overflow-auto whitespace-pre-wrap break-all"
				>{formatPreview(pending.affected_preview)}</pre>
			</div>
		{/if}

		<div class="flex items-center justify-end gap-2 mt-3">
			<Button kind="outlined" size="sm" loading={rolling} {disabled} on:click={handleRollback}>
				{$i18n.t('Rollback')}
			</Button>
			<Button kind="filled" size="sm" status="error" loading={committing} {disabled} on:click={handleCommit}>
				{$i18n.t('Commit')}
			</Button>
		</div>
	</div>
{/if}
