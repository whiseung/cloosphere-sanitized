<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher<{
		decide: {
			actionIndex: number;
			decision: { type: 'respond'; message: string };
		};
	}>();

	// HumanInTheLoopMiddleware 가 만든 action_request 한 건. ask_user 도구는
	// arguments 에 { question, choices? } 를 가진다.
	export let action: {
		name?: string;
		args?: Record<string, unknown>;
		description?: string;
	} = {};
	export let actionIndex: number = 0;
	export let pending: boolean = true;
	export let decision: 'respond' | null = null;
	export let answeredText: string = '';

	$: question = (action?.args?.question as string | undefined) ?? '';
	$: rawChoices = action?.args?.choices;
	$: choices = Array.isArray(rawChoices) ? (rawChoices as unknown[]).map((c) => String(c)) : [];

	let customText = '';
	let busy = false;

	const respondWith = (text: string) => {
		if (!pending || busy) return;
		const trimmed = text.trim();
		if (!trimmed) return;
		busy = true;
		dispatch('decide', {
			actionIndex,
			decision: { type: 'respond', message: trimmed }
		});
	};

	const handleKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			respondWith(customText);
		}
	};
</script>

<div
	class="cloo-ask-user"
	class:is-pending={pending}
	class:is-answered={decision === 'respond'}
>
	<div class="cloo-ask-user__header">
		<Badge status="info" size="sm">{$i18n.t('Question')}</Badge>
		{#if decision === 'respond'}
			<Badge status="success" size="sm">{$i18n.t('Answered')}</Badge>
		{/if}
	</div>

	{#if question}
		<div class="cloo-ask-user__question">{question}</div>
	{/if}

	{#if pending}
		{#if choices.length > 0}
			<div class="cloo-ask-user__hint">{$i18n.t('Choose an option')}</div>
			<div class="cloo-ask-user__choices">
				{#each choices as choice}
					<Button
						kind="outlined"
						size="md"
						disabled={busy}
						on:click={() => respondWith(choice)}
					>
						{choice}
					</Button>
				{/each}
			</div>
			<div class="cloo-ask-user__hint">{$i18n.t('Or type a custom answer')}</div>
		{/if}

		<div class="cloo-ask-user__input-row" on:keydown={handleKeydown}>
			<Textarea
				bind:value={customText}
				placeholder={$i18n.t('Type your answer...')}
				size="md"
				rows={2}
				autoResize
			/>
			<Button
				kind="filled"
				size="md"
				disabled={busy || customText.trim().length === 0}
				loading={busy}
				on:click={() => respondWith(customText)}
			>
				{$i18n.t('Send')}
			</Button>
		</div>
	{:else if answeredText}
		<div class="cloo-ask-user__answer">
			<div class="cloo-ask-user__answer-label">{$i18n.t('Your answer')}</div>
			<div class="cloo-ask-user__answer-text">{answeredText}</div>
		</div>
	{/if}
</div>

<style>
	.cloo-ask-user {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-3);
		margin: var(--cloo-space-2) 0;
		border: 1px solid var(--cloo-border-default);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-surface);
	}

	.cloo-ask-user.is-pending {
		border-color: var(--cloo-color-info, #2563eb);
	}

	.cloo-ask-user.is-answered {
		opacity: 0.85;
	}

	.cloo-ask-user__header {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-user__question {
		font-size: 0.95rem;
		line-height: 1.45;
		color: var(--cloo-text-primary);
		font-weight: 500;
	}

	.cloo-ask-user__hint {
		font-size: 0.75rem;
		color: var(--cloo-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.cloo-ask-user__choices {
		display: flex;
		flex-wrap: wrap;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-user__input-row {
		display: flex;
		align-items: flex-end;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-user__input-row :global(.cloo-textarea) {
		flex: 1 1 auto;
	}

	.cloo-ask-user__answer {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-1);
		padding: var(--cloo-space-2);
		background: var(--cloo-bg-default);
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
	}

	.cloo-ask-user__answer-label {
		font-size: 0.75rem;
		color: var(--cloo-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.cloo-ask-user__answer-text {
		font-size: 0.875rem;
		color: var(--cloo-text-default);
		white-space: pre-wrap;
		word-break: break-word;
	}
</style>
