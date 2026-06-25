<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Document from '$lib/components/icons/Document.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher<{
		decide: { actionIndex: number; decision: { type: 'respond'; message: string } };
	}>();

	export let action: { name?: string; args?: Record<string, unknown>; description?: string } = {};
	export let actionIndex: number = 0;
	export let pending: boolean = true;
	export let decision: 'respond' | null = null;
	export let answeredText: string = '';

	type Candidate = {
		file_id: string;
		name: string;
		mime_type?: string;
		modified_time?: string | null;
		owner?: string | null;
		location?: string | null;
	};

	$: purpose = (action?.args?.purpose as string | undefined) ?? '';
	$: rawCandidates = action?.args?.candidates;
	$: candidates = Array.isArray(rawCandidates) ? (rawCandidates as Candidate[]) : [];

	let checked: Record<string, boolean> = {};
	let busy = false;

	$: selectedIds = candidates.filter((c) => checked[c.file_id]).map((c) => c.file_id);
	$: selectedCount = selectedIds.length;

	const LOCATION_LABELS: Record<string, string> = {
		my_drive: 'My Drive',
		shared_drive: 'Shared drive',
		shared_with_me: 'Shared with me'
	};
	const locationText = (loc?: string | null): string =>
		loc && LOCATION_LABELS[loc] ? $i18n.t(LOCATION_LABELS[loc]) : '';

	const metaLine = (c: Candidate): string => {
		const parts: string[] = [];
		const loc = locationText(c.location);
		if (loc) parts.push(loc);
		if (c.modified_time) parts.push(String(c.modified_time).slice(0, 10));
		if (c.owner) parts.push(c.owner);
		return parts.join(' · ');
	};

	const toggle = (id: string) => {
		if (!pending || busy) return;
		checked = { ...checked, [id]: !checked[id] };
	};

	const confirm = () => {
		if (!pending || busy || selectedCount === 0) return;
		busy = true;
		// 선택 토큰 + 명시 지시 — resume 작성 턴에서 모델이 고른 파일을 읽고 원래 요청을
		// 끝까지(메일이면 gmail_send 호출) 수행하도록.  텍스트 초안으로 끝내는 컴플라이언스
		// 이탈 방지.  파일명은 미포함(H-2 보안: file_id 토큰만 load-bearing).
		const tokens = selectedIds.map((id) => `[file_id:${id}]`).join('');
		const message =
			`User selected these files: ${tokens}\n` +
			`Read them with drive_get_contents, then complete the user's ORIGINAL request. ` +
			`If the request is to write/compose/send an email, you MUST call the gmail_send ` +
			`tool to show the editable confirmation card — do NOT output the email as plain text.`;
		dispatch('decide', { actionIndex, decision: { type: 'respond', message } });
	};

	const chooseNone = () => {
		if (!pending || busy) return;
		busy = true;
		dispatch('decide', {
			actionIndex,
			decision: {
				type: 'respond',
				message: $i18n.t('None of these files match — please search again')
			}
		});
	};

	const selectedNames = (): string[] => {
		const ids = [...(answeredText || '').matchAll(/\[file_id:([^\]]+)\]/g)].map((m) => m[1]);
		return ids.map((id) => candidates.find((c) => c.file_id === id)?.name ?? id);
	};
	$: lockedNames = !pending ? selectedNames() : [];
</script>

<div class="cloo-file-picker" class:is-pending={pending} class:is-answered={decision === 'respond'}>
	<div class="cloo-file-picker__header">
		<div class="cloo-file-picker__icon"><Document className="size-4" strokeWidth="2" /></div>
		<Badge status="info" size="sm">{$i18n.t('Select files')}</Badge>
		{#if decision === 'respond'}
			<Badge status="success" size="sm">{$i18n.t('Selected')}</Badge>
		{/if}
	</div>

	<div class="cloo-file-picker__purpose">{purpose || $i18n.t('Choose which files to use')}</div>

	{#if pending}
		<div class="cloo-file-picker__list">
			{#each candidates as c}
				{@const meta = metaLine(c)}
				<button
					type="button"
					class="cloo-file-picker__row"
					class:is-checked={checked[c.file_id]}
					aria-pressed={checked[c.file_id] ? 'true' : 'false'}
					disabled={busy}
					on:click={() => toggle(c.file_id)}
				>
					<span class="cloo-file-picker__check" aria-hidden="true">
						{#if checked[c.file_id]}✓{/if}
					</span>
					<div class="cloo-file-picker__row-icon"><Document className="size-4" strokeWidth="2" /></div>
					<div class="cloo-file-picker__row-body">
						<div class="cloo-file-picker__row-name">{c.name}</div>
						{#if meta}<div class="cloo-file-picker__row-meta">{meta}</div>{/if}
					</div>
				</button>
			{/each}
		</div>
		<div class="cloo-file-picker__actions">
			<Button kind="filled" size="md" disabled={busy || selectedCount === 0} on:click={confirm}>
				{$i18n.t('Confirm selection')}{selectedCount > 0 ? ` (${selectedCount})` : ''}
			</Button>
			<button type="button" class="cloo-file-picker__none" disabled={busy} on:click={chooseNone}>
				{$i18n.t('None of these / search again')}
			</button>
		</div>
	{:else if lockedNames.length > 0}
		<div class="cloo-file-picker__answer">
			<div class="cloo-file-picker__answer-label">{$i18n.t('Selected files')}</div>
			<ul class="cloo-file-picker__answer-list">
				{#each lockedNames as n}<li>{n}</li>{/each}
			</ul>
		</div>
	{:else if answeredText}
		<div class="cloo-file-picker__answer">
			<div class="cloo-file-picker__answer-name">{answeredText}</div>
		</div>
	{/if}
</div>

<style>
	.cloo-file-picker {
		display: flex; flex-direction: column; gap: var(--cloo-space-2);
		padding: var(--cloo-space-3); margin: var(--cloo-space-2) 0;
		border: 1px solid var(--cloo-border-default); border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-surface);
	}
	.cloo-file-picker.is-pending { border-color: var(--cloo-color-accent); }
	.cloo-file-picker.is-answered { opacity: 0.85; }
	.cloo-file-picker__header { display: flex; align-items: center; gap: var(--cloo-space-2); }
	.cloo-file-picker__icon { color: var(--cloo-color-accent); }
	.cloo-file-picker__purpose {
		font-size: 0.95rem; line-height: 1.45; color: var(--cloo-text-primary); font-weight: 500;
	}
	.cloo-file-picker__list { display: flex; flex-direction: column; gap: var(--cloo-space-2); }
	.cloo-file-picker__row {
		display: flex; align-items: flex-start; gap: var(--cloo-space-2); width: 100%;
		text-align: left; padding: var(--cloo-space-2);
		border: 1px solid var(--cloo-border-subtle); border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-default); cursor: pointer;
	}
	.cloo-file-picker__row:hover:not(:disabled) {
		border-color: var(--cloo-color-accent); background: var(--cloo-bg-neutral-hovered);
	}
	.cloo-file-picker__row.is-checked {
		border-color: var(--cloo-color-accent); background: var(--cloo-bg-neutral-hovered);
	}
	.cloo-file-picker__row:disabled { opacity: 0.6; cursor: not-allowed; }
	.cloo-file-picker__check {
		flex: 0 0 auto; width: 1.1rem; height: 1.1rem; margin-top: 2px;
		display: inline-flex; align-items: center; justify-content: center;
		border: 1.5px solid var(--cloo-border-default); border-radius: 4px;
		font-size: 0.75rem; line-height: 1; color: #fff;
	}
	.cloo-file-picker__row.is-checked .cloo-file-picker__check {
		background: var(--cloo-color-accent); border-color: var(--cloo-color-accent);
	}
	.cloo-file-picker__row-icon { color: var(--cloo-color-accent); flex: 0 0 auto; margin-top: 2px; }
	.cloo-file-picker__row-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
	.cloo-file-picker__row-name {
		font-size: 0.875rem; color: var(--cloo-text-default); font-weight: 500; word-break: break-word;
	}
	.cloo-file-picker__row-meta { font-size: 0.75rem; color: var(--cloo-text-muted); }
	.cloo-file-picker__actions { display: flex; align-items: center; gap: var(--cloo-space-3); }
	.cloo-file-picker__none {
		font-size: 0.75rem; color: var(--cloo-text-muted); background: transparent;
		border: none; cursor: pointer; padding: var(--cloo-space-1) 0; text-decoration: underline;
	}
	.cloo-file-picker__none:disabled { opacity: 0.6; cursor: not-allowed; }
	.cloo-file-picker__answer {
		display: flex; flex-direction: column; gap: var(--cloo-space-1); padding: var(--cloo-space-2);
		background: var(--cloo-bg-default); border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
	}
	.cloo-file-picker__answer-label {
		font-size: 0.75rem; color: var(--cloo-text-muted); text-transform: uppercase; letter-spacing: 0.05em;
	}
	.cloo-file-picker__answer-list { margin: 0; padding-left: 1.1rem; font-size: 0.875rem; color: var(--cloo-text-default); }
	.cloo-file-picker__answer-name { font-size: 0.875rem; color: var(--cloo-text-default); word-break: break-word; }
</style>
