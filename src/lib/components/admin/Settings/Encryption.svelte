<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getKMSConfig,
		getKMSRotationConfig,
		listKMSAudit,
		migrateKMS,
		setKMSConfig,
		setKMSRotationConfig,
		testKMSConnection,
		triggerKMSRotationCheck,
		verifyKMSAudit,
		type KMSAuditRow,
		type KMSAuditVerifyResult,
		type KMSConfig,
		type KMSMigrateResult,
		type KMSRotationCheckResult,
		type KMSRotationStatus
	} from '$lib/apis/configs';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<any>('i18n');

	export let saveHandler: () => Promise<void> | void;

	let loading = true;
	let saving = false;
	let testing = false;

	let config: KMSConfig = {
		KMS_PROVIDER: 'fernet',
		KMS_AZURE_KEY_VAULT_KEY_URI: '',
		KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED: '',
		KMS_AZURE_TENANT_ID: '',
		KMS_AZURE_CLIENT_ID: '',
		KMS_AZURE_CLIENT_SECRET: ''
	};

	type TestResult = { ok: boolean; detail: string } | null;
	let lastTest: TestResult = null;

	let migrating = false;
	let lastMigrate: KMSMigrateResult | null = null;
	let showMigrateConfirm = false;

	$: providerOptions = [
		{
			value: 'fernet',
			label: $i18n.t('Local (Fernet)')
		},
		{
			value: 'azkv-env',
			label: $i18n.t('Azure Key Vault (envelope)')
		}
	];

	$: isAzure = config.KMS_PROVIDER === 'azkv-env';

	const loadConfig = async () => {
		try {
			const res = await getKMSConfig(localStorage.token);
			config = {
				KMS_PROVIDER: res?.KMS_PROVIDER ?? 'fernet',
				KMS_AZURE_KEY_VAULT_KEY_URI: res?.KMS_AZURE_KEY_VAULT_KEY_URI ?? '',
				KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED:
					res?.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED ?? '',
				KMS_AZURE_TENANT_ID: res?.KMS_AZURE_TENANT_ID ?? '',
				KMS_AZURE_CLIENT_ID: res?.KMS_AZURE_CLIENT_ID ?? '',
				KMS_AZURE_CLIENT_SECRET: res?.KMS_AZURE_CLIENT_SECRET ?? ''
			};
			// Capture the saved KEK URIs so handleSave() can detect inline
			// rotation (URI changed) and prompt to migrate envelopes.
			originalKekUri = config.KMS_AZURE_KEY_VAULT_KEY_URI ?? '';
			originalRestrictedKekUri = config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED ?? '';
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? $i18n.t('Failed to load encryption config'));
		} finally {
			loading = false;
		}
	};

	const handleTest = async () => {
		testing = true;
		lastTest = null;
		try {
			lastTest = await testKMSConnection(localStorage.token, config);
			if (lastTest?.ok) {
				toast.success($i18n.t('Connection successful'));
			} else {
				toast.error(formatBackendError(lastTest, $i18n) || $i18n.t('Connection failed'));
			}
		} catch (e: any) {
			lastTest = {
				ok: false,
				detail: typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? $i18n.t('Connection failed')
			};
			toast.error(lastTest.detail);
		} finally {
			testing = false;
		}
	};

	const handleMigrate = async () => {
		migrating = true;
		try {
			lastMigrate = await migrateKMS(localStorage.token);
			const total = sumTouched(lastMigrate);
			toast.success($i18n.t('Migrated {{count}} record(s)', { count: total }));
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? $i18n.t('Migration failed'));
		} finally {
			migrating = false;
			showMigrateConfirm = false;
		}
	};

	const sumTouched = (res: KMSMigrateResult): number => {
		const groups = res?.counts ? Object.values(res.counts) : [];
		return groups.reduce((acc, g) => acc + (g?.touched ?? 0), 0);
	};

	const sumFailed = (res: KMSMigrateResult): number => {
		const groups = res?.counts ? Object.values(res.counts) : [];
		return groups.reduce((acc, g) => acc + (g?.failed ?? 0), 0);
	};

	// --- Save-time KEK change detection ----------------------------------
	//
	// When the operator edits the KEK URI inline (Azure Key Vault section)
	// and saves, we want two safeties:
	//   1. Auto health-check the new KEK before persisting — bad URI /
	//      missing RBAC must NOT replace a working config.
	//   2. Prompt to run Migrate Existing Data — without it, historic
	//      envelopes stay on the old KEK and the new KEK only takes
	//      effect for fresh writes.
	//
	// The previous "Rotate KEK" section was removed in favor of this
	// inline flow — the rotate API endpoint is still available as a
	// programmatic shortcut.

	let originalKekUri = '';
	let originalRestrictedKekUri = '';

	let showMigrateAfterSaveConfirm = false;

	// --- Auto rotation (Phase 4.5) --------------------------------------

	let autoRotationStatus: KMSRotationStatus | null = null;
	let autoRotationSaving = false;
	let autoRotationChecking = false;
	let lastAutoCheck: KMSRotationCheckResult | null = null;

	const loadAutoRotation = async () => {
		try {
			autoRotationStatus = await getKMSRotationConfig(localStorage.token);
			lastAutoCheck = autoRotationStatus.last_result;
		} catch (e: any) {
			toast.error(
				typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Failed to load rotation config'))
			);
		}
	};

	const handleAutoRotationSave = async () => {
		if (!autoRotationStatus) return;
		autoRotationSaving = true;
		try {
			autoRotationStatus = await setKMSRotationConfig(localStorage.token, {
				KMS_ROTATION_AUTO_ENABLED: autoRotationStatus.KMS_ROTATION_AUTO_ENABLED,
				KMS_ROTATION_CHECK_INTERVAL_HOURS: autoRotationStatus.KMS_ROTATION_CHECK_INTERVAL_HOURS,
				KMS_ROTATION_DRY_RUN: autoRotationStatus.KMS_ROTATION_DRY_RUN
			});
			toast.success($i18n.t('Auto rotation settings saved'));
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Failed to save')));
		} finally {
			autoRotationSaving = false;
		}
	};

	const handleAutoRotationCheck = async (dryRun: boolean) => {
		autoRotationChecking = true;
		try {
			lastAutoCheck = await triggerKMSRotationCheck(localStorage.token, dryRun);
			if (lastAutoCheck.ok) {
				toast.success(
					dryRun
						? $i18n.t('Dry-run check complete')
						: $i18n.t('Rotation check complete')
				);
			} else {
				toast.error($i18n.t('Rotation check reported errors'));
			}
			// Refresh saved status (last_check_at / last_result).
			await loadAutoRotation();
			// If a real rotation actually fired, refresh the main config view too.
			if (
				!dryRun &&
				lastAutoCheck.tiers.some((t) => t.status === 'rotated')
			) {
				await loadConfig();
			}
		} catch (e: any) {
			toast.error(
				typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Rotation check failed'))
			);
		} finally {
			autoRotationChecking = false;
		}
	};

	const formatTsHuman = (ts: number) => {
		if (!ts) return $i18n.t('never');
		try {
			return new Date(ts * 1000).toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
		} catch {
			return String(ts);
		}
	};

	// --- Audit log quick status (Phase 4.2) ------------------------------
	//
	// Compact view here — most recent 5 rows + "Verify Integrity" action.
	// The full filterable table + CSV export live under
	// Monitoring → KMS Audit so this settings tab stays focused on KMS
	// configuration rather than log review.

	let auditRows: KMSAuditRow[] = [];
	let auditTotal = 0;
	let auditLoading = false;

	let verifyResult: KMSAuditVerifyResult | null = null;
	let verifying = false;

	const loadAudit = async () => {
		auditLoading = true;
		try {
			const res = await listKMSAudit(localStorage.token, { page: 1, limit: 5 });
			auditRows = res.rows;
			auditTotal = res.total;
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : (formatBackendError(e, $i18n) ?? $i18n.t('Failed to load audit log')));
		} finally {
			auditLoading = false;
		}
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

	const formatTs = (ms: number) => {
		try {
			return new Date(ms).toISOString().replace('T', ' ').slice(0, 19);
		} catch {
			return String(ms);
		}
	};

	const handleSave = async () => {
		saving = true;
		try {
			// Pre-flight: when switching to / staying on the envelope provider,
			// probe the new KEK before persisting. A bad URI / missing RBAC
			// must NOT replace a working config — replacing without a probe
			// is exactly how operators lock themselves out of decrypt.
			if (config.KMS_PROVIDER === 'azkv-env') {
				lastTest = null;
				const probe = await testKMSConnection(localStorage.token, config);
				lastTest = probe;
				if (!probe?.ok) {
					toast.error(formatBackendError(probe, $i18n) || $i18n.t('Connection failed'));
					return;
				}
			}

			// Detect inline rotation: any KEK URI changed from what was loaded.
			const kekChanged =
				(config.KMS_AZURE_KEY_VAULT_KEY_URI ?? '') !== originalKekUri ||
				(config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED ?? '') !== originalRestrictedKekUri;

			const res = await setKMSConfig(localStorage.token, config);
			config = {
				KMS_PROVIDER: res?.KMS_PROVIDER ?? 'fernet',
				KMS_AZURE_KEY_VAULT_KEY_URI: res?.KMS_AZURE_KEY_VAULT_KEY_URI ?? '',
				KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED:
					res?.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED ?? '',
				KMS_AZURE_TENANT_ID: res?.KMS_AZURE_TENANT_ID ?? '',
				KMS_AZURE_CLIENT_ID: res?.KMS_AZURE_CLIENT_ID ?? '',
				KMS_AZURE_CLIENT_SECRET: res?.KMS_AZURE_CLIENT_SECRET ?? ''
			};
			originalKekUri = config.KMS_AZURE_KEY_VAULT_KEY_URI ?? '';
			originalRestrictedKekUri = config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED ?? '';

			await saveHandler();

			// New KEK is now active for fresh writes. Historic envelopes
			// stay on the prior KEK until Migrate runs — surface that as a
			// confirm so the operator doesn't end up with mixed state by
			// accident.
			if (kekChanged && config.KMS_PROVIDER === 'azkv-env') {
				showMigrateAfterSaveConfirm = true;
			}
		} catch (e: any) {
			toast.error(typeof e === 'string' ? e : formatBackendError(e, $i18n) ?? $i18n.t('Failed to save encryption config'));
		} finally {
			saving = false;
		}
	};

	onMount(async () => {
		await loadConfig();
		await loadAutoRotation();
		await loadAudit();
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={handleSave}
>
	<div class="space-y-3 overflow-y-scroll scrollbar-hidden h-full pr-1">
		{#if loading}
			<div class="flex items-center justify-center py-8">
				<Spinner className="size-5" />
			</div>
		{:else}
			<div>
				<div class="mb-2 text-sm font-medium">{$i18n.t('Provider')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t(
						'Select the backend that encrypts sensitive configuration values. Switching providers does not migrate existing data — legacy ciphertexts continue to decrypt via fallback.'
					)}
				</div>

				<div class="flex flex-col gap-1">
					<div class="text-xs font-medium text-[var(--cloo-text-default)]">
						{$i18n.t('KMS Provider')}
					</div>
					<div class="encryption-provider-selector w-full">
						<Selector
							value={config.KMS_PROVIDER}
							items={providerOptions}
							size="md"
							on:change={(e) => {
								config.KMS_PROVIDER = e.detail.value;
								lastTest = null;
							}}
						/>
					</div>
					<div class="text-xs text-gray-500 dark:text-gray-400">
						{isAzure
							? $i18n.t('Encrypt with AES-256-GCM, wrap DEK with RSA-OAEP-256 KEK in Azure Key Vault.')
							: $i18n.t('Self-managed Fernet using WEBUI_SECRET_KEY. No external dependency.')}
					</div>
				</div>
			</div>

			{#if isAzure}
				<hr class="border-gray-100 dark:border-gray-850" />

				<div>
					<div class="mb-2 text-sm font-medium">{$i18n.t('Azure Key Vault')}</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
						{$i18n.t(
							'Versioned KEK URI from your Key Vault. The Service Principal must have the "Key Vault Crypto User" role on this vault.'
						)}
					</div>

					<div class="flex flex-col gap-3">
						<Input
							bind:value={config.KMS_AZURE_KEY_VAULT_KEY_URI}
							label={$i18n.t('KEK URI (default tier)')}
							caption={$i18n.t('Wraps Confidential & Internal classifications')}
							placeholder="https://<vault>.vault.azure.net/keys/<name>/<version>"
							size="md"
							required
						/>
						<Input
							bind:value={config.KMS_AZURE_KEY_VAULT_KEY_URI_RESTRICTED}
							label={$i18n.t('Restricted KEK URI (optional)')}
							caption={$i18n.t(
								'Separate KEK for Restricted (PII, financial) classifications. Leave blank to share the default KEK above. Same Service Principal is reused.'
							)}
							placeholder="https://<vault>.vault.azure.net/keys/<pii-kek>/<version>"
							size="md"
						/>
					</div>
				</div>

				<hr class="border-gray-100 dark:border-gray-850" />

				<div>
					<div class="mb-2 text-sm font-medium">{$i18n.t('Service Principal (optional)')}</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
						{$i18n.t(
							'Use a dedicated Service Principal when the Key Vault lives in a different tenant from your Microsoft OAuth app. Leave empty to fall back to MICROSOFT_CLIENT_* or DefaultAzureCredential.'
						)}
					</div>

					<div class="flex flex-col gap-3">
						<Input
							bind:value={config.KMS_AZURE_TENANT_ID}
							label={$i18n.t('Tenant ID')}
							placeholder={$i18n.t('Directory (tenant) ID')}
							size="md"
						/>
						<Input
							bind:value={config.KMS_AZURE_CLIENT_ID}
							label={$i18n.t('Client ID')}
							placeholder={$i18n.t('Application (client) ID')}
							size="md"
						/>

						<div>
							<div class="mb-1 text-xs font-medium text-[var(--cloo-text-default)]">
								{$i18n.t('Client Secret')}
							</div>
							<div
								class="flex items-center gap-2 px-3 py-2 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-surface-border)] bg-[var(--cloo-bg-surface)]"
							>
								<SensitiveInput
									bind:value={config.KMS_AZURE_CLIENT_SECRET}
									placeholder={$i18n.t('Client secret value')}
									required={false}
								/>
							</div>
						</div>
					</div>
				</div>
			{/if}

			{#if lastTest}
				<div
					class="px-3 py-2 rounded-[var(--cloo-radius-default)] border"
					class:border-green-300={lastTest.ok}
					class:border-red-300={!lastTest.ok}
					class:bg-green-50={lastTest.ok}
					class:bg-red-50={!lastTest.ok}
					class:dark:bg-green-900={lastTest.ok}
					class:dark:bg-red-900={!lastTest.ok}
					class:dark:bg-opacity-20={true}
				>
					<div class="flex items-center gap-2">
						<Badge status={lastTest.ok ? 'success' : 'danger'} size="sm">
							{lastTest.ok ? $i18n.t('Connected') : $i18n.t('Failed')}
						</Badge>
						<span class="text-xs text-gray-700 dark:text-gray-300 break-all">
							{lastTest.detail}
						</span>
					</div>
				</div>
			{/if}

			<hr class="border-gray-100 dark:border-gray-850" />

			<div>
				<div class="mb-2 text-sm font-medium">{$i18n.t('Migrate Existing Data')}</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t(
						'Re-encrypt every legacy ciphertext (Config secrets, DbSphere connections, tool connection keys, license tokens) under the currently configured provider. Idempotent — re-running is safe.'
					)}
				</div>

				<Button
					kind="outlined"
					size="md"
					type="button"
					loading={migrating}
					on:click={() => (showMigrateConfirm = true)}
				>
					{$i18n.t('Migrate Existing Data')}
				</Button>

				{#if lastMigrate}
					<div class="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">
						{#each Object.entries(lastMigrate.counts) as [scope, c] (scope)}
							<div
								class="px-3 py-2 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-surface-border)] bg-[var(--cloo-bg-surface)]"
							>
								<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">
									{scope}
								</div>
								<div class="flex flex-wrap items-center gap-1.5 text-xs">
									<Badge status="success" size="sm">{$i18n.t('Migrated')} {c.touched}</Badge>
									{#if c.skipped > 0}
										<Badge status="default" size="sm">
											{$i18n.t('Skipped')} {c.skipped}
										</Badge>
									{/if}
									{#if c.failed > 0}
										<Badge status="danger" size="sm">{$i18n.t('Failed')} {c.failed}</Badge>
									{/if}
								</div>
							</div>
						{/each}
					</div>

					{#if sumFailed(lastMigrate) > 0}
						<div class="mt-2 text-xs text-red-600 dark:text-red-400">
							{$i18n.t(
								'Some records failed to migrate. Check backend logs for details.'
							)}
						</div>
					{/if}
				{/if}
			</div>

			<!-- Auto Rotation (Phase 4.5) — only meaningful for envelope provider -->
			{#if isAzure && autoRotationStatus}
				<div class="pt-3 border-t border-[var(--cloo-border-subtle)]">
					<div class="mb-2 text-sm font-medium">{$i18n.t('Auto Rotation')}</div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
						{$i18n.t(
							'Scheduler periodically checks Azure Key Vault for a newer KEK version (created by KV rotation_policy) and re-encrypts every envelope under it. Use Dry-run for the first activation period to preview decisions in the audit log.'
						)}
					</div>

					<div class="flex flex-col gap-3">
						<LabelBase
							label={$i18n.t('Enable auto rotation')}
							caption={$i18n.t('Off by default. Turn on after running a Dry-run check.')}
							size="md"
						>
							<svelte:fragment slot="right">
								<Switch bind:state={autoRotationStatus.KMS_ROTATION_AUTO_ENABLED} />
							</svelte:fragment>
						</LabelBase>

						<LabelBase
							label={$i18n.t('Dry-run mode')}
							caption={$i18n.t('Log would-rotate decisions without touching live config')}
							size="md"
						>
							<svelte:fragment slot="right">
								<Switch bind:state={autoRotationStatus.KMS_ROTATION_DRY_RUN} />
							</svelte:fragment>
						</LabelBase>

						<Input
							type="number"
							bind:value={autoRotationStatus.KMS_ROTATION_CHECK_INTERVAL_HOURS}
							label={$i18n.t('Check interval (hours)')}
							caption={$i18n.t('Minimum 1. The scheduler checks at most once per interval; 24 = daily.')}
							size="md"
						/>

						<div class="flex flex-wrap items-center gap-2">
							<Button
								kind="filled"
								size="sm"
								type="button"
								loading={autoRotationSaving}
								on:click={handleAutoRotationSave}
							>
								{$i18n.t('Save')}
							</Button>
							<Button
								kind="outlined"
								size="sm"
								type="button"
								loading={autoRotationChecking}
								on:click={() => handleAutoRotationCheck(true)}
							>
								{$i18n.t('Dry-run check')}
							</Button>
							<Button
								kind="outlined"
								size="sm"
								type="button"
								loading={autoRotationChecking}
								on:click={() => handleAutoRotationCheck(false)}
							>
								{$i18n.t('Check Now')}
							</Button>
						</div>
					</div>

					<!-- Status -->
					<div class="mt-3 text-xs text-[var(--cloo-text-muted)]">
						{$i18n.t('Last check')}: {formatTsHuman(autoRotationStatus.last_check_at)}
					</div>

					{#if lastAutoCheck}
						<div class="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
							{#each lastAutoCheck.tiers as tier (tier.classification)}
								<div
									class="px-3 py-2 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-surface-border)] bg-[var(--cloo-bg-surface)]"
								>
									<div class="flex items-center justify-between mb-1">
										<div class="text-xs font-medium text-[var(--cloo-text-default)]">
											{tier.classification}
										</div>
										{#if tier.status === 'up-to-date'}
											<Badge status="success" size="sm">{$i18n.t('Up to date')}</Badge>
										{:else if tier.status === 'rotated'}
											<Badge status="info" size="sm">{$i18n.t('Rotated')}</Badge>
										{:else if tier.status === 'would-rotate'}
											<Badge status="warning" size="sm">{$i18n.t('Would rotate (dry-run)')}</Badge>
										{:else if tier.status === 'error'}
											<Badge status="danger" size="sm">{$i18n.t('Error')}</Badge>
										{:else}
											<Badge status="default" size="sm">{tier.status}</Badge>
										{/if}
									</div>
									{#if tier.status === 'up-to-date'}
										<div class="text-xs text-[var(--cloo-text-muted)] truncate">
											{$i18n.t('Version')}: {tier.current_version ?? '-'}
										</div>
									{:else if tier.status === 'would-rotate' || tier.status === 'rotated'}
										<div class="text-xs text-[var(--cloo-text-muted)] truncate">
											{tier.from_version ?? '-'} → {tier.to_version ?? '-'}
										</div>
									{:else if tier.status === 'error'}
										<div class="text-xs text-red-600 dark:text-red-400 break-all">
											{tier.error ?? ''}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Audit Log quick status (Phase 4.2) — full viewer in Monitoring → KMS Audit -->
			<div class="pt-3 border-t border-[var(--cloo-border-subtle)]">
				<div class="flex items-center justify-between mb-2">
					<div class="text-sm font-medium">{$i18n.t('Audit Log')}</div>
					<a
						href="/admin/monitoring"
						class="text-xs text-[var(--cloo-color-info)] hover:underline"
					>
						{$i18n.t('Open full viewer in Monitoring →')}
					</a>
				</div>
				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t(
						'Tamper-evident hash-chained record of every KMS wrap/unwrap/rotate/health-check operation. Tampering with any historic row breaks the chain on Verify.'
					)}
				</div>

				<div class="flex flex-wrap items-center gap-2 mb-2">
					<div class="text-xs text-[var(--cloo-text-muted)]">
						{$i18n.t('Total: {{count}}', { count: auditTotal })}
					</div>
					<Button
						kind="outlined"
						size="sm"
						type="button"
						loading={verifying}
						on:click={handleVerify}
					>
						{$i18n.t('Verify Integrity')}
					</Button>
					{#if verifyResult}
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
					{/if}
				</div>

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
								<th class="text-left px-2 py-1.5 whitespace-nowrap">{$i18n.t('Config Path')}</th>
							</tr>
						</thead>
						<tbody>
							{#if auditLoading}
								<tr><td colspan="5" class="text-center py-3"><Spinner className="size-4" /></td></tr>
							{:else if auditRows.length === 0}
								<tr
									><td colspan="5" class="text-center py-3 text-[var(--cloo-text-muted)]">
										{$i18n.t('No audit rows yet')}
									</td></tr
								>
							{:else}
								{#each auditRows as r (r.id)}
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
										<td class="px-2 py-1 max-w-[300px] truncate" title={r.config_path ?? ''}>
											{r.config_path ?? '-'}
										</td>
									</tr>
								{/each}
							{/if}
						</tbody>
					</table>
				</div>
			</div>
		{/if}
	</div>

	<ConfirmDialog
		bind:show={showMigrateConfirm}
		title={$i18n.t('Migrate Existing Data?')}
		message={$i18n.t(
			'This will re-encrypt every legacy sensitive value under the current KMS provider. The operation is idempotent and safe to re-run, but writes to multiple tables.'
		)}
		confirmLabel={$i18n.t('Migrate')}
		cancelLabel={$i18n.t('Cancel')}
		onConfirm={handleMigrate}
	/>

	<ConfirmDialog
		bind:show={showMigrateAfterSaveConfirm}
		title={$i18n.t('Migrate envelopes to the new KEK?')}
		message={$i18n.t(
			'KEK URI changed. Existing envelopes still decrypt under the prior KEK, but new writes use the new KEK. Run Migrate Existing Data to re-encrypt every protected value under the new KEK now.'
		)}
		confirmLabel={$i18n.t('Migrate')}
		cancelLabel={$i18n.t('Later')}
		onConfirm={handleMigrate}
	/>

	{#if !loading}
		<div class="flex items-center justify-between pt-3">
			<Button
				kind="outlined"
				size="md"
				type="button"
				disabled={saving || (isAzure && !config.KMS_AZURE_KEY_VAULT_KEY_URI)}
				loading={testing}
				on:click={handleTest}
			>
				{$i18n.t('Test Connection')}
			</Button>

			<Button kind="filled" size="md" type="submit" loading={saving}>
				{$i18n.t('Save')}
			</Button>
		</div>
	{/if}
</form>

<style>
	/* Force the Selector to take the full row width — by default it auto-sizes
	   to its content which makes long provider names crammed. */
	.encryption-provider-selector :global(button[role='combobox']),
	.encryption-provider-selector :global(.cloo-selector__trigger) {
		width: 100%;
	}
</style>
