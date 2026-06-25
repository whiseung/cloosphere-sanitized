<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		exportKMSAuditCSV,
		listKMSAudit,
		verifyKMSAudit,
		type KMSAuditRow,
		type KMSAuditVerifyResult
	} from '$lib/apis/configs';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<any>('i18n');

	let rows: KMSAuditRow[] = [];
	let total = 0;
	let page = 1;
	const limit = 25;
	let loading = false;

	let filterOp = '';
	let filterSuccess: '' | 'true' | 'false' = '';

	let verifyResult: KMSAuditVerifyResult | null = null;
	let verifying = false;

	let exportReason = '';
	let exporting = false;

	const operationOptions = [
		{ value: '', label: $i18n.t('All operations') },
		{ value: 'wrap', label: 'wrap' },
		{ value: 'unwrap', label: 'unwrap' },
		{ value: 'rotate', label: 'rotate' },
		{ value: 'health_check', label: 'health_check' },
		{ value: 'provider_change', label: 'provider_change' },
		{ value: 'migrate', label: 'migrate' },
		{ value: 'audit_export', label: 'audit_export' }
	];

	const successOptions = [
		{ value: '', label: $i18n.t('Any result') },
		{ value: 'true', label: $i18n.t('Success only') },
		{ value: 'false', label: $i18n.t('Failure only') }
	];

	const buildQuery = () => ({
		page,
		limit,
		operation: filterOp || undefined,
		success:
			filterSuccess === 'true'
				? true
				: filterSuccess === 'false'
					? false
					: undefined
	});

	const loadRows = async () => {
		loading = true;
		try {
			const res = await listKMSAudit(localStorage.token, buildQuery());
			rows = res.rows;
			total = res.total;
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Failed to load audit log')));
		} finally {
			loading = false;
		}
	};

	const handleOperationFilterChange = (value: string) => {
		filterOp = value;
		page = 1;
		loadRows();
	};

	const handleSuccessFilterChange = (value: string) => {
		filterSuccess = value === 'true' ? 'true' : value === 'false' ? 'false' : '';
		page = 1;
		loadRows();
	};

	const handleVerify = async () => {
		verifying = true;
		verifyResult = null;
		try {
			verifyResult = await verifyKMSAudit(localStorage.token);
			if (verifyResult?.ok) {
				toast.success(
					$i18n.t('Audit chain verified: {{count}} rows OK', {
						count: verifyResult.checked
					})
				);
			} else {
				toast.error(
					$i18n.t('Chain broken at id={{id}}: {{reason}}', {
						id: verifyResult?.first_break_id ?? '?',
						reason: verifyResult?.first_break_reason ?? '?'
					})
				);
			}
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Verification failed')));
		} finally {
			verifying = false;
		}
	};

	const handleExport = async () => {
		if (!exportReason.trim()) {
			toast.error($i18n.t('Please provide a reason for exporting audit data'));
			return;
		}
		exporting = true;
		try {
			const blob = await exportKMSAuditCSV(localStorage.token, exportReason, buildQuery());
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `kms-audit-log-${Date.now()}.csv`;
			a.click();
			URL.revokeObjectURL(url);
			toast.success($i18n.t('Audit log exported'));
			await loadRows();
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Export failed')));
		} finally {
			exporting = false;
		}
	};

	const goPrev = () => {
		page -= 1;
		loadRows();
	};

	const goNext = () => {
		page += 1;
		loadRows();
	};

	const formatTs = (ms: number) => {
		try {
			return new Date(ms).toISOString().replace('T', ' ').slice(0, 19);
		} catch {
			return String(ms);
		}
	};

	onMount(loadRows);
</script>

<div class="flex flex-col gap-3 text-sm">
	<div>
		<div class="text-base font-medium mb-1">{$i18n.t('KMS Audit Log')}</div>
		<div class="text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t(
				'Tamper-evident hash-chained record of every KMS wrap/unwrap/rotate/health-check operation. Tampering with any historic row breaks the chain on Verify.'
			)}
		</div>
	</div>

	<div class="flex flex-wrap items-end gap-2">
		<div class="flex flex-col gap-1 min-w-[180px]">
			<div class="text-xs font-medium text-[var(--cloo-text-default)]">
				{$i18n.t('Operation')}
			</div>
			<Selector
				value={filterOp}
				items={operationOptions}
				size="sm"
				on:change={(e) => handleOperationFilterChange(e.detail.value)}
			/>
		</div>
		<div class="flex flex-col gap-1 min-w-[160px]">
			<div class="text-xs font-medium text-[var(--cloo-text-default)]">
				{$i18n.t('Result')}
			</div>
			<Selector
				value={filterSuccess}
				items={successOptions}
				size="sm"
				on:change={(e) => handleSuccessFilterChange(e.detail.value)}
			/>
		</div>
		<Button kind="outlined" size="sm" type="button" loading={verifying} on:click={handleVerify}>
			{$i18n.t('Verify Integrity')}
		</Button>
	</div>

	{#if verifyResult}
		<div>
			{#if verifyResult.ok}
				<Badge status="success" size="sm">
					{$i18n.t('Chain OK ({{count}} rows checked)', { count: verifyResult.checked })}
				</Badge>
			{:else}
				<Badge status="danger" size="sm">
					{$i18n.t('Chain broken at id={{id}}: {{reason}}', {
						id: verifyResult.first_break_id ?? '?',
						reason: verifyResult.first_break_reason ?? '?'
					})}
				</Badge>
			{/if}
		</div>
	{/if}

	<div
		class="rounded-[var(--cloo-radius-default)] border border-[var(--cloo-surface-border)] bg-[var(--cloo-bg-surface)] overflow-x-auto"
	>
		<table class="w-full text-xs">
			<thead class="text-[var(--cloo-text-muted)]">
				<tr>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">id</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Time (UTC)')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Operation')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Result')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Actor')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Config Path')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('IP')}</th>
					<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Error')}</th>
				</tr>
			</thead>
			<tbody>
				{#if loading}
					<tr><td colspan="8" class="text-center py-4"><Spinner className="size-4" /></td></tr>
				{:else if rows.length === 0}
					<tr
						><td colspan="8" class="text-center py-4 text-[var(--cloo-text-muted)]">
							{$i18n.t('No audit rows match the current filter')}
						</td></tr
					>
				{:else}
					{#each rows as r (r.id)}
						<tr class="border-t border-[var(--cloo-border-subtle)]">
							<td class="px-2 py-1 whitespace-nowrap font-mono">{r.id}</td>
							<td class="px-2 py-1 whitespace-nowrap font-mono">{formatTs(r.timestamp_ms)}</td>
							<td class="px-2 py-1 whitespace-nowrap">{r.operation}</td>
							<td class="px-2 py-1 whitespace-nowrap">
								{#if r.success}
									<Badge status="success" size="sm">OK</Badge>
								{:else}
									<Badge status="danger" size="sm">FAIL</Badge>
								{/if}
							</td>
							<td class="px-2 py-1 whitespace-nowrap text-[var(--cloo-text-muted)]">
								{r.actor_type}{r.actor_id ? `:${r.actor_id.slice(0, 8)}` : ''}
							</td>
							<td class="px-2 py-1 max-w-[280px] truncate" title={r.config_path ?? ''}>
								{r.config_path ?? '-'}
							</td>
							<td class="px-2 py-1 whitespace-nowrap font-mono">{r.client_ip ?? '-'}</td>
							<td class="px-2 py-1 max-w-[160px] truncate" title={r.error_code ?? ''}>
								{r.error_code ?? '-'}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>

	<div class="flex items-center justify-between">
		<div class="text-xs text-[var(--cloo-text-muted)]">
			{$i18n.t('Total: {{count}}', { count: total })} ·
			{$i18n.t('Page {{page}}', { page })}
		</div>
		<div class="flex items-center gap-1.5">
			<Button
				kind="outlined"
				size="sm"
				type="button"
				disabled={page <= 1 || loading}
				on:click={goPrev}
			>
				{$i18n.t('Prev')}
			</Button>
			<Button
				kind="outlined"
				size="sm"
				type="button"
				disabled={page * limit >= total || loading}
				on:click={goNext}
			>
				{$i18n.t('Next')}
			</Button>
		</div>
	</div>

	<div class="flex flex-wrap items-end gap-2 pt-2 border-t border-[var(--cloo-border-subtle)]">
		<div class="flex flex-col gap-1 flex-1 min-w-[260px]">
			<div class="text-xs font-medium text-[var(--cloo-text-default)]">
				{$i18n.t('Export reason (recorded in audit chain)')}
			</div>
			<Input
				bind:value={exportReason}
				placeholder={$i18n.t('e.g. quarterly compliance review')}
				size="sm"
			/>
		</div>
		<Button
			kind="outlined"
			size="sm"
			type="button"
			loading={exporting}
			disabled={!exportReason.trim()}
			on:click={handleExport}
		>
			{$i18n.t('Export CSV')}
		</Button>
	</div>
</div>
