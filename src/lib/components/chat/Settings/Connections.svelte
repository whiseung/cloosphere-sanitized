<script lang="ts">
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { getModels as _getModels } from '$lib/apis';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import { config as globalConfig, models, settings, user } from '$lib/stores';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Connection from './Connections/Connection.svelte';
	import {
		getMyEmailConnections,
		type ProviderConnectionStatus
	} from '$lib/apis/email';

	import AddConnectionModal from '$lib/components/AddConnectionModal.svelte';

	export let saveSettings: Function;

	let config = null;

	let showConnectionModal = false;

	// 본인의 Microsoft / Google OAuth 연결 상태. null = 아직 로드 안됨.
	let emailConnections: ProviderConnectionStatus[] | null = null;

	const PROVIDER_LABEL: Record<string, string> = {
		microsoft: 'Microsoft (SSO)',
		google: 'Google (SSO)'
	};

	// OAuth scope → 사용자 친화 라벨 i18n 키.  엔트리에 없으면 raw scope 그대로 노출.
	// 기본 신원 scope (openid / email / profile / userinfo.*) 는 의미 없어 숨김.
	const SCOPE_HIDDEN = new Set<string>([
		'openid',
		'email',
		'profile',
		'offline_access',
		'https://www.googleapis.com/auth/userinfo.email',
		'https://www.googleapis.com/auth/userinfo.profile'
	]);

	const SCOPE_LABEL_KEYS: Record<string, string> = {
		// Google
		'https://www.googleapis.com/auth/gmail.readonly': 'Read Gmail messages',
		'https://www.googleapis.com/auth/gmail.send': 'Send email on your behalf',
		'https://www.googleapis.com/auth/calendar.events': 'View and edit calendar events',
		// Microsoft Graph (delegated)
		'Mail.Read': 'Read Outlook mail',
		'Mail.ReadWrite': 'Read and write Outlook mail',
		'Mail.Send': 'Send email on your behalf',
		'Calendars.ReadWrite': 'View and edit calendar events',
		'User.Read': 'Read your basic profile',
		'User.ReadBasic.All': 'Look up colleagues in directory'
	};

	const formatScope = (scope: string) => {
		const key = SCOPE_LABEL_KEYS[scope];
		return key ? $i18n.t(key) : scope;
	};

	const visibleScopes = (scopes: string[] | null) => {
		if (!scopes) return [];
		return scopes.filter((s) => !SCOPE_HIDDEN.has(s));
	};

	const reloadEmailConnections = async () => {
		try {
			emailConnections = await getMyEmailConnections(localStorage.token);
		} catch (e) {
			console.error('Failed to load email connections:', e);
			emailConnections = [];
		}
	};

	const addConnectionHandler = async (connection) => {
		config.OPENAI_API_BASE_URLS.push(connection.url);
		config.OPENAI_API_KEYS.push(connection.key);
		config.OPENAI_API_CONFIGS[config.OPENAI_API_BASE_URLS.length - 1] = connection.config;

		await updateHandler();
	};

	const updateHandler = async () => {
		// Remove trailing slashes
		config.OPENAI_API_BASE_URLS = config.OPENAI_API_BASE_URLS.map((url) => url.replace(/\/$/, ''));

		// Check if API KEYS length is same than API URLS length
		if (config.OPENAI_API_KEYS.length !== config.OPENAI_API_BASE_URLS.length) {
			// if there are more keys than urls, remove the extra keys
			if (config.OPENAI_API_KEYS.length > config.OPENAI_API_BASE_URLS.length) {
				config.OPENAI_API_KEYS = config.OPENAI_API_KEYS.slice(
					0,
					config.OPENAI_API_BASE_URLS.length
				);
			}

			// if there are more urls than keys, add empty keys
			if (config.OPENAI_API_KEYS.length < config.OPENAI_API_BASE_URLS.length) {
				const diff = config.OPENAI_API_BASE_URLS.length - config.OPENAI_API_KEYS.length;
				for (let i = 0; i < diff; i++) {
					config.OPENAI_API_KEYS.push('');
				}
			}
		}

		await saveSettings({
			directConnections: config
		});
	};

	onMount(async () => {
		config = $settings?.directConnections ?? {
			OPENAI_API_BASE_URLS: [],
			OPENAI_API_KEYS: [],
			OPENAI_API_CONFIGS: {}
		};
		await reloadEmailConnections();
	});
</script>

<AddConnectionModal direct bind:show={showConnectionModal} onSubmit={addConnectionHandler} />

<form
	class="flex flex-col h-full justify-between text-sm"
	on:submit|preventDefault={() => {
		updateHandler();
	}}
>
	<div class=" overflow-y-scroll scrollbar-hidden h-full">
		{#if config !== null}
			<div class="pr-1.5 space-y-2">
				{#if $globalConfig?.features?.enable_direct_connections}
					<div class="space-y-2">
						<div class="flex justify-between items-center">
							<div class=" text-base font-semibold">
								{$i18n.t('Manage Direct Connections')}
							</div>

							<Tooltip content={$i18n.t(`Add Connection`)}>
								<Button
									kind="text"
									size="sm"
									on:click={() => {
										showConnectionModal = true;
									}}
								>
									<svelte:fragment slot="prefix">
										<Plus className="size-3.5" />
									</svelte:fragment>
									{$i18n.t('Add')}
								</Button>
							</Tooltip>
						</div>

						<div class="flex flex-col gap-1.5">
							{#each config?.OPENAI_API_BASE_URLS ?? [] as url, idx}
								<Connection
									bind:url
									bind:key={config.OPENAI_API_KEYS[idx]}
									bind:config={config.OPENAI_API_CONFIGS[idx]}
									onSubmit={() => {
										updateHandler();
									}}
									onDelete={() => {
										config.OPENAI_API_BASE_URLS = config.OPENAI_API_BASE_URLS.filter(
											(url, urlIdx) => idx !== urlIdx
										);
										config.OPENAI_API_KEYS = config.OPENAI_API_KEYS.filter(
											(key, keyIdx) => idx !== keyIdx
										);

										let newConfig = {};
										config.OPENAI_API_BASE_URLS.forEach((url, newIdx) => {
											newConfig[newIdx] =
												config.OPENAI_API_CONFIGS[newIdx < idx ? newIdx : newIdx + 1];
										});
										config.OPENAI_API_CONFIGS = newConfig;
									}}
								/>
							{/each}
						</div>

						<div class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Connect to your own OpenAI compatible API endpoints.')}
							<br />
							{$i18n.t(
								'CORS must be properly configured by the provider to allow requests from Open WebUI.'
							)}
						</div>
					</div>

					<hr class="border-gray-50 dark:border-gray-850 my-3" />
				{/if}

				<div class="space-y-2">
					<div class=" text-base font-semibold">{$i18n.t('Connected Accounts')}</div>
					<div class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('External tools use these SSO connections to act on your behalf.')}
					</div>

					{#if emailConnections === null}
						<div class="py-2">
							<Spinner className="size-4" />
						</div>
					{:else}
						<div class="flex flex-col gap-1.5">
							{#each emailConnections as conn (conn.provider)}
								<div
									class="flex flex-col gap-2 px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)]"
								>
									<div class="flex justify-between items-center">
										<div class="flex flex-col">
											<div class="text-sm font-medium">
												{PROVIDER_LABEL[conn.provider] ?? conn.provider}
											</div>
											<div class="text-xs text-gray-500 dark:text-gray-400">
												{#if conn.connected}
													{conn.account_email ?? $i18n.t('Connected')}
												{:else}
													{$i18n.t('Not connected — sign in again to enable.')}
												{/if}
											</div>
										</div>
									</div>
									{#if conn.connected && visibleScopes(conn.scopes).length > 0}
										<div class="flex flex-wrap gap-1">
											{#each visibleScopes(conn.scopes) as scope (scope)}
												<span
													class="text-[11px] px-2 py-0.5 rounded-full border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-default)] text-gray-700 dark:text-gray-300"
													title={scope}
												>
													{formatScope(scope)}
												</span>
											{/each}
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<div class="flex h-full justify-center">
				<div class="my-auto">
					<Spinner className="size-6" />
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
