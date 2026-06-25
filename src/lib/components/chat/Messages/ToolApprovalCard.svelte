<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher<{
		decide: {
			actionIndex: number;
			decision: { type: 'approve' | 'reject'; message?: string };
		};
	}>();

	// langgraph HumanInTheLoopMiddleware 의 ActionRequest 한 건. 키는:
	// { name: str, args: dict, description?: str } — `arguments` 가 아님 주의.
	export let action: { name?: string; args?: Record<string, unknown>; description?: string } = {};
	export let actionIndex: number = 0;
	export let pending: boolean = true;
	export let decision: 'approve' | 'reject' | null = null;

	let busy: 'approve' | 'reject' | null = null;

	const handleApprove = () => {
		if (!pending || busy) return;
		busy = 'approve';
		dispatch('decide', { actionIndex, decision: { type: 'approve' } });
	};

	const handleReject = () => {
		if (!pending || busy) return;
		busy = 'reject';
		dispatch('decide', { actionIndex, decision: { type: 'reject' } });
	};

	const formatArgs = (args: Record<string, unknown> | undefined): string => {
		if (!args || Object.keys(args).length === 0) return '';
		try {
			return JSON.stringify(args, null, 2);
		} catch {
			return String(args);
		}
	};

	// SQL 같은 긴 string 인자는 JSON 한 줄로 박히면 \n 이 escape 되어 가독성 망침.
	// 도구별로 "큰 string 인자" 가 알려진 키에 있으면 raw 로 별도 표시.
	const PRIMARY_STRING_KEYS: Record<string, string> = {
		run_sql: 'sql',
		run_sql_read: 'sql',
		run_sql_write: 'sql',
		execute_code: 'code',
		code_interpreter: 'code',
	};

	$: primaryKey = action?.name ? PRIMARY_STRING_KEYS[action.name] : undefined;
	$: primaryValue =
		primaryKey && typeof action?.args?.[primaryKey] === 'string'
			? (action.args[primaryKey] as string)
			: '';
	$: primaryLang = primaryKey === 'sql' ? 'sql' : primaryKey === 'code' ? 'python' : '';
	$: otherArgs = (() => {
		if (!action?.args) return null;
		if (!primaryValue) return action.args;
		const { [primaryKey!]: _omit, ...rest } = action.args;
		return Object.keys(rest).length ? rest : null;
	})();
	$: otherArgsJson = otherArgs ? formatArgs(otherArgs as Record<string, unknown>) : '';
	$: argsJson = primaryValue ? '' : formatArgs(action?.args);
</script>

<div
	class="cloo-tool-approval"
	class:is-pending={pending}
	class:is-approved={decision === 'approve'}
	class:is-rejected={decision === 'reject'}
>
	<div class="cloo-tool-approval__header">
		<div class="cloo-tool-approval__title">
			<Badge status="warning" size="sm">{$i18n.t('Approval required')}</Badge>
			<span class="cloo-tool-approval__tool-name">{action?.name ?? '—'}</span>
		</div>
		{#if decision === 'approve'}
			<Badge status="success" size="sm">{$i18n.t('Approved')}</Badge>
		{:else if decision === 'reject'}
			<Badge status="danger" size="sm">{$i18n.t('Rejected')}</Badge>
		{/if}
	</div>

	{#if action?.description}
		<div class="cloo-tool-approval__description">{action.description}</div>
	{/if}

	{#if primaryValue}
		<div class="cloo-tool-approval__args-label">
			{primaryLang ? primaryLang.toUpperCase() : $i18n.t('Arguments')}
		</div>
		<pre class="cloo-tool-approval__args is-code">{primaryValue}</pre>
		{#if otherArgsJson}
			<div class="cloo-tool-approval__args-label">{$i18n.t('Other Arguments')}</div>
			<pre class="cloo-tool-approval__args">{otherArgsJson}</pre>
		{/if}
	{:else if argsJson}
		<div class="cloo-tool-approval__args-label">{$i18n.t('Arguments')}</div>
		<pre class="cloo-tool-approval__args">{argsJson}</pre>
	{/if}

	{#if pending}
		<div class="cloo-tool-approval__actions">
			<Button
				kind="outlined"
				size="sm"
				status="error"
				disabled={busy !== null}
				loading={busy === 'reject'}
				on:click={handleReject}
			>
				{$i18n.t('Reject')}
			</Button>
			<Button
				kind="filled"
				size="sm"
				disabled={busy !== null}
				loading={busy === 'approve'}
				on:click={handleApprove}
			>
				{$i18n.t('Approve')}
			</Button>
		</div>
	{/if}
</div>

<style>
	.cloo-tool-approval {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		padding: var(--cloo-space-3);
		margin: var(--cloo-space-2) 0;
		border: 1px solid var(--cloo-border-default);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-surface);
	}

	.cloo-tool-approval.is-pending {
		border-color: var(--cloo-color-warning, #d97706);
	}

	.cloo-tool-approval.is-approved {
		opacity: 0.7;
	}

	.cloo-tool-approval.is-rejected {
		opacity: 0.7;
	}

	.cloo-tool-approval__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--cloo-space-2);
	}

	.cloo-tool-approval__title {
		display: flex;
		align-items: center;
		gap: var(--cloo-space-2);
		min-width: 0;
	}

	.cloo-tool-approval__tool-name {
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.875rem;
		color: var(--cloo-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.cloo-tool-approval__description {
		font-size: 0.8125rem;
		color: var(--cloo-text-muted);
		line-height: 1.4;
	}

	.cloo-tool-approval__args-label {
		font-size: 0.75rem;
		color: var(--cloo-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.cloo-tool-approval__args {
		margin: 0;
		padding: var(--cloo-space-2);
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 0.8125rem;
		color: var(--cloo-text-default);
		background: var(--cloo-bg-default);
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		max-height: 16rem;
		overflow: auto;
		white-space: pre-wrap;
		word-break: break-word;
		line-height: 1.45;
	}

	.cloo-tool-approval__args.is-code {
		max-height: 22rem;
		tab-size: 2;
	}

	.cloo-tool-approval__actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--cloo-space-2);
	}
</style>
