<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Input from '$lib/components/common/Input.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher<{
		decide: {
			actionIndex: number;
			decision: { type: 'respond'; message: string };
		};
	}>();

	// HumanInTheLoopMiddleware 가 만든 action_request 한 건. ask_user_form 도구는
	// arguments 에 { fields: [{key, question, type, choices?, required, allow_custom}], title?, intro? }
	// 를 가진다. 카드 1개 = action 1개 = respond decision 1개 (message 는 {key:answer} JSON).
	export let action: {
		name?: string;
		args?: Record<string, unknown>;
		description?: string;
	} = {};
	export let actionIndex: number = 0;
	export let pending: boolean = true;
	export let decision: 'respond' | null = null;
	export let answeredText: string = '';

	type FormField = {
		key: string;
		question: string;
		type?: string;
		choices?: string[];
		required?: boolean;
		allow_custom?: boolean;
	};

	$: rawFields = action?.args?.fields;
	$: fields = (Array.isArray(rawFields) ? rawFields : []) as FormField[];
	$: title = (action?.args?.title as string | undefined) ?? '';
	$: intro = (action?.args?.intro as string | undefined) ?? '';

	// key → 사용자 입력 값. choice/text 모두 최종 문자열을 여기에 담는다.
	let values: Record<string, string> = {};
	let initialized = false;
	let busy = false;

	$: if (!initialized && fields.length) {
		const seed: Record<string, string> = {};
		for (const f of fields) seed[f.key] = '';
		values = seed;
		initialized = true;
	}

	$: requiredKeys = fields.filter((f) => f.required !== false).map((f) => f.key);
	$: requiredDone = requiredKeys.filter(
		(k) => (values[k] ?? '').toString().trim().length > 0
	).length;
	$: allRequiredDone = requiredKeys.length === 0 || requiredDone >= requiredKeys.length;

	const isChoice = (f: FormField) =>
		f.type === 'choice' && Array.isArray(f.choices) && f.choices.length > 0;

	const pickChoice = (key: string, choice: string) => {
		if (!pending || busy) return;
		values = { ...values, [key]: choice };
	};

	const submitAll = () => {
		if (!pending || busy || !allRequiredDone) return;
		busy = true;
		const payload: Record<string, string> = {};
		for (const f of fields) {
			const v = (values[f.key] ?? '').toString().trim();
			if (v) payload[f.key] = v;
		}
		dispatch('decide', {
			actionIndex,
			decision: { type: 'respond', message: JSON.stringify(payload) }
		});
	};

	const handleKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
			e.preventDefault();
			submitAll();
		}
	};

	// 제출 후 요약 뷰 — answeredText(JSON) 를 key→question 라벨로 풀어 표시.
	type AnsweredPair = { label: string; value: string };
	const parseAnswered = (txt: string): AnsweredPair[] => {
		if (!txt) return [];
		let obj: any;
		try {
			obj = JSON.parse(txt);
		} catch {
			return [{ label: '', value: txt }];
		}
		if (!obj || typeof obj !== 'object') return [{ label: '', value: String(txt) }];
		return Object.entries(obj).map(([k, v]) => ({
			label: fields.find((f) => f.key === k)?.question ?? k,
			value: String(v)
		}));
	};
	$: answeredPairs = parseAnswered(answeredText);
</script>

<div class="cloo-ask-form" class:is-pending={pending} class:is-answered={decision === 'respond'}>
	<div class="cloo-ask-form__header">
		<span class="cloo-ask-form__title">{title || $i18n.t('A few details to proceed')}</span>
		<Badge status="info" size="sm">{$i18n.t('Question')}</Badge>
		{#if decision === 'respond'}
			<Badge status="success" size="sm">{$i18n.t('Answered')}</Badge>
		{:else}
			<Badge status="default" size="sm">{fields.length} {$i18n.t('items')}</Badge>
		{/if}
	</div>

	{#if intro}
		<div class="cloo-ask-form__intro">{intro}</div>
	{/if}

	{#if pending}
		<div class="cloo-ask-form__fields" on:keydown={handleKeydown}>
			{#each fields as field, i}
				<div
					class="cloo-ask-form__field"
					class:is-done={(values[field.key] ?? '').toString().trim().length > 0}
				>
					<div class="cloo-ask-form__q">
						<span class="cloo-ask-form__num">{i + 1}.</span>
						<span>
							{field.question}
							{#if field.required !== false}
								<span class="cloo-ask-form__req">*</span>
							{:else}
								<span class="cloo-ask-form__opt">({$i18n.t('optional')})</span>
							{/if}
						</span>
					</div>

					{#if isChoice(field)}
						<div class="cloo-ask-form__choices">
							{#each field.choices ?? [] as choice}
								<Button
									kind={values[field.key] === choice ? 'filled' : 'outlined'}
									size="md"
									disabled={busy}
									on:click={() => pickChoice(field.key, choice)}
								>
									{choice}
								</Button>
							{/each}
						</div>
						{#if field.allow_custom !== false}
							<Input
								bind:value={values[field.key]}
								placeholder={$i18n.t('Or type a custom answer')}
								size="md"
								disabled={busy}
							/>
						{/if}
					{:else}
						<Textarea
							bind:value={values[field.key]}
							placeholder={$i18n.t('Type your answer...')}
							size="md"
							rows={2}
							autoResize
							disabled={busy}
						/>
					{/if}
				</div>
			{/each}
		</div>

		<div class="cloo-ask-form__footer">
			<span class="cloo-ask-form__progress">
				{$i18n.t('Required')}
				<b>{requiredDone}</b> / <b>{requiredKeys.length}</b>
			</span>
			<Button
				kind="filled"
				size="md"
				disabled={busy || !allRequiredDone}
				loading={busy}
				on:click={submitAll}
			>
				{$i18n.t('Send all')}
			</Button>
		</div>
	{:else if answeredPairs.length > 0}
		<div class="cloo-ask-form__answers">
			{#each answeredPairs as pair}
				<div class="cloo-ask-form__answer">
					{#if pair.label}
						<div class="cloo-ask-form__answer-label">{pair.label}</div>
					{/if}
					<div class="cloo-ask-form__answer-text">{pair.value}</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.cloo-ask-form {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-3);
		padding: var(--cloo-space-3);
		margin: var(--cloo-space-2) 0;
		border: 1px solid var(--cloo-border-default);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-surface);
	}

	.cloo-ask-form.is-pending {
		border-color: var(--cloo-color-info, #2563eb);
	}

	.cloo-ask-form.is-answered {
		opacity: 0.85;
	}

	.cloo-ask-form__header {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-form__title {
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--cloo-text-primary);
		margin-right: auto;
	}

	.cloo-ask-form__intro {
		font-size: 0.875rem;
		line-height: 1.5;
		color: var(--cloo-text-default);
		padding-bottom: var(--cloo-space-2);
		border-bottom: 1px solid var(--cloo-border-subtle);
	}

	.cloo-ask-form__fields {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-form__field {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-3);
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-default);
	}

	.cloo-ask-form__field.is-done {
		border-color: var(--cloo-color-success, #16a34a);
	}

	.cloo-ask-form__q {
		display: flex;
		align-items: baseline;
		gap: var(--cloo-space-1);
		font-size: 0.9rem;
		font-weight: 500;
		color: var(--cloo-text-primary);
		line-height: 1.45;
	}

	.cloo-ask-form__num {
		flex: none;
		font-variant-numeric: tabular-nums;
		color: var(--cloo-text-muted);
		font-weight: 600;
		font-size: 0.8rem;
	}

	.cloo-ask-form__req {
		color: var(--cloo-danger-solid, #dc2626);
		font-weight: 700;
	}

	.cloo-ask-form__opt {
		font-size: 0.75rem;
		color: var(--cloo-text-muted);
		font-weight: 500;
	}

	.cloo-ask-form__choices {
		display: flex;
		flex-wrap: wrap;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-form__footer {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-3);
		padding-top: var(--cloo-space-2);
		border-top: 1px solid var(--cloo-border-subtle);
	}

	.cloo-ask-form__progress {
		font-size: 0.8rem;
		color: var(--cloo-text-muted);
		margin-right: auto;
	}

	.cloo-ask-form__progress b {
		color: var(--cloo-text-primary);
	}

	.cloo-ask-form__answers {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
	}

	.cloo-ask-form__answer {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-1);
		padding: var(--cloo-space-2);
		background: var(--cloo-bg-default);
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
	}

	.cloo-ask-form__answer-label {
		font-size: 0.75rem;
		color: var(--cloo-text-muted);
	}

	.cloo-ask-form__answer-text {
		font-size: 0.875rem;
		color: var(--cloo-text-default);
		white-space: pre-wrap;
		word-break: break-word;
	}
</style>
