<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { config } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';
	import {
		getLicenseStatus,
		registerLicenseKey,
		deleteLicenseKey,
		type LicenseStatus,
		type KeyInfo
	} from '$lib/apis/license';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let licenseStatus: LicenseStatus = {
		has_license: false,
		tier: null,
		company: null,
		max_users: 0,
		expires_at: null,
		license_keys: [],
		feature_keys: [],
		permissions: {},
		enforcement_enabled: false
	};
	let newKey = '';
	let loading = false;
	let registering = false;

	const MODULE_LABELS: Record<string, string> = {
		// Standard tier
		audit_log: 'Audit Log',
		glossary: 'Glossary',
		guardrail: 'Guardrail',
		image_generation: 'Image Generation',
		kbsphere: 'Knowledge Base (KbSphere)',
		tools: 'Tools',
		// Professional tier
		agent_flow: 'Agent Flow',
		ai_dashboard: 'AI Dashboard',
		branding: 'Branding',
		dbsphere: 'DbSphere',
		embed_widget: 'Embed Widget',
		evaluation: 'Evaluation',
		trace: 'Trace',
		// Enterprise only
		code_gateway: 'Code Gateway',
		file_guardrail: 'File Guardrail',
		global_guardrail: 'Global Guardrail',
		knowledge_graph: 'Knowledge Graph'
	};

	const TIER_LABELS: Record<string, string> = {
		basic: 'Basic',
		standard: 'Standard',
		professional: 'Professional',
		enterprise: 'Enterprise',
		developer: 'Developer'
	};

	const loadStatus = async () => {
		loading = true;
		try {
			const result = await getLicenseStatus(localStorage.token);
			if (result) {
				licenseStatus = result;
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			loading = false;
		}
	};

	const handleRegister = async () => {
		if (!newKey.trim()) {
			toast.error($i18n.t('Please enter a license key'));
			return;
		}

		registering = true;
		try {
			const result = await registerLicenseKey(localStorage.token, newKey.trim());
			if (result?.success) {
				toast.success(
					$i18n.t('Key registered successfully') + (result.type ? ` (${result.type})` : '')
				);
				newKey = '';
				await loadStatus();
				await config.set(await getBackendConfig());
			} else {
				toast.error(result?.error || $i18n.t('Failed to register key'));
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			registering = false;
		}
	};

	const handleDelete = async (key: string) => {
		try {
			await deleteLicenseKey(localStorage.token, key);
			toast.success($i18n.t('Key deleted successfully'));
			await loadStatus();
			await config.set(await getBackendConfig());
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const formatDate = (timestamp: number | null | undefined): string => {
		if (!timestamp) return '-';
		return new Date(timestamp * 1000).toLocaleDateString();
	};

	onMount(async () => {
		await loadStatus();
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveHandler();
	}}
>
	<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<!-- License Status -->
		<div class="mb-3.5">
			<div class="mb-2.5 text-base font-medium">{$i18n.t('License Status')}</div>

			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			{#if loading}
				<div class="text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Loading...')}
				</div>
			{:else}
				<div class="flex flex-col gap-2.5 pr-2">
					<LabelBase label={$i18n.t('Status')} size="md">
						<svelte:fragment slot="right">
							<Badge
								status={licenseStatus.has_license ? 'success' : 'default'}
								size="md"
								invert
								content={licenseStatus.has_license
									? $i18n.t('Active')
									: $i18n.t('Not Registered')}
							/>
						</svelte:fragment>
					</LabelBase>

					{#if licenseStatus.has_license}
						<LabelBase label={$i18n.t('Tier')} size="md">
							<svelte:fragment slot="right">
								<div class="text-xs">
									{TIER_LABELS[licenseStatus.tier ?? ''] ?? licenseStatus.tier ?? '-'}
								</div>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Company')} size="md">
							<svelte:fragment slot="right">
								<div class="text-xs">
									{licenseStatus.company ?? '-'}
								</div>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Expires')} size="md">
							<svelte:fragment slot="right">
								<div class="text-xs">
									{formatDate(licenseStatus.expires_at)}
								</div>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Max Users')} size="md">
							<svelte:fragment slot="right">
								<div class="text-xs">
									{licenseStatus.max_users || $i18n.t('Unlimited')}
								</div>
							</svelte:fragment>
						</LabelBase>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Register Key -->
		<div class="mb-3">
			<div class="mb-2.5 text-base font-medium">{$i18n.t('Register Key')}</div>

			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			<div class="mb-2.5 w-full">
				<Textarea
					bind:value={newKey}
					label={$i18n.t('License Key')}
					placeholder={$i18n.t('Paste license or feature key here...')}
					rows={3}
					size="md"
					inputClassName="font-mono"
				/>

				<div class="mt-2 flex">
					<Button
						kind="filled"
						size="md"
						type="button"
						disabled={registering || !newKey.trim()}
						loading={registering}
						on:click={handleRegister}
					>
						{$i18n.t('Register Key')}
					</Button>
				</div>
			</div>
		</div>

		<!-- Registered Keys -->
		{#if licenseStatus.license_keys.length > 0 || licenseStatus.feature_keys.length > 0}
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">
					{$i18n.t('Registered Keys')}
				</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="flex flex-col gap-1.5">
					{#each licenseStatus.license_keys as keyInfo}
						<div class="flex items-center justify-between py-2">
							<div class="flex items-center gap-2 min-w-0">
								<Badge status="info" size="sm" content="LICENSE" />
								<div class="min-w-0">
									<div class="text-xs font-medium truncate">
										{TIER_LABELS[String(keyInfo.payload?.tier ?? '')] ??
											keyInfo.payload?.tier ?? '-'}
										- {keyInfo.payload?.company ?? '-'}
									</div>
									<div class="text-xs text-gray-400 dark:text-gray-500">
										{$i18n.t('Expires')}: {formatDate(Number(keyInfo.payload?.exp) || null)}
										{#if !keyInfo.valid}
											<span class="text-red-500 ml-1">({keyInfo.error})</span>
										{/if}
									</div>
								</div>
							</div>
							<Tooltip content={$i18n.t('Delete')}>
								<button
									type="button"
									class="shrink-0 ml-2 p-1 rounded-lg text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition"
									on:click={() => handleDelete(keyInfo.token)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											fill-rule="evenodd"
											d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
											clip-rule="evenodd"
										/>
									</svg>
								</button>
							</Tooltip>
						</div>
					{/each}

					{#each licenseStatus.feature_keys as keyInfo}
						<div class="flex items-center justify-between py-2">
							<div class="flex items-center gap-2 min-w-0">
								<Badge status="accent" size="sm" content="FEATURE" />
								<div class="min-w-0">
									<div class="text-xs font-medium truncate">
										{MODULE_LABELS[String(keyInfo.payload?.module ?? '')] ??
											keyInfo.payload?.module ?? '-'}
										- {keyInfo.payload?.company ?? '-'}
									</div>
									<div class="text-xs text-gray-400 dark:text-gray-500">
										{$i18n.t('Expires')}: {formatDate(Number(keyInfo.payload?.exp) || null)}
										{#if !keyInfo.valid}
											<span class="text-red-500 ml-1">({keyInfo.error})</span>
										{/if}
									</div>
								</div>
							</div>
							<Tooltip content={$i18n.t('Delete')}>
								<button
									type="button"
									class="shrink-0 ml-2 p-1 rounded-lg text-gray-500 hover:text-red-500 dark:hover:text-red-400 transition"
									on:click={() => handleDelete(keyInfo.token)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-4 h-4"
									>
										<path
											fill-rule="evenodd"
											d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.519.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5zM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4zM8.58 7.72a.75.75 0 00-1.5.06l.3 7.5a.75.75 0 101.5-.06l-.3-7.5zm4.34.06a.75.75 0 10-1.5-.06l-.3 7.5a.75.75 0 101.5.06l.3-7.5z"
											clip-rule="evenodd"
										/>
									</svg>
								</button>
							</Tooltip>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Feature Status -->
		<div class="mb-3">
			<div class="mb-2.5 text-base font-medium">
				{$i18n.t('Feature Status')}
			</div>

			<hr class="border-gray-100 dark:border-gray-850 my-2" />

			{#if !licenseStatus.enforcement_enabled}
				<div class="text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t(
						'License enforcement is disabled. Register a license key to activate feature-based access control.'
					)}
				</div>
			{:else}
				<div class="flex flex-col gap-2.5 pr-2">
					{#each Object.entries(MODULE_LABELS) as [module, label]}
						<LabelBase {label} size="md">
							<svelte:fragment slot="right">
								<Badge
									status={licenseStatus.permissions[module] ? 'success' : 'default'}
									size="sm"
									content={licenseStatus.permissions[module]
										? $i18n.t('Available')
										: $i18n.t('Not Licensed')}
								/>
							</svelte:fragment>
						</LabelBase>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
