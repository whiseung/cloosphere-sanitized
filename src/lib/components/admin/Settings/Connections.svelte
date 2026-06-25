<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';

	const dispatch = createEventDispatcher();

	import { getOllamaConfig, updateOllamaConfig } from '$lib/apis/ollama';
	import { getOpenAIConfig, updateOpenAIConfig, getOpenAIModels } from '$lib/apis/openai';
	import { getModels as _getModels } from '$lib/apis';
	import {
		getDirectConnectionsConfig,
		setDirectConnectionsConfig,
		getGoogleCloudConfig,
		setGoogleCloudConfig,
		getGoogleIntegrationConfig,
		setGoogleIntegrationConfig,
		getStorageConfig,
		setStorageConfig,
		testStorageConnection,
		getFileStorageConfig,
		setFileStorageConfig,
		testFileStorageConnection
	} from '$lib/apis/configs';
	import type {
		StorageConfig,
		S3Config,
		AzureConfig,
		GCSConfig,
		FileStorageConfig
	} from '$lib/apis/configs';

	import { config, models, settings, user } from '$lib/stores';

	import { slide } from 'svelte/transition';

	import Button from '$lib/components/common/Button.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';

	import OpenAIConnection from './Connections/OpenAIConnection.svelte';
	import AddConnectionModal from '$lib/components/AddConnectionModal.svelte';
	import OllamaConnection from './Connections/OllamaConnection.svelte';
	const i18n = getContext('i18n');

	// Cloud Accounts
	const CLOUD_PROVIDERS = [{ id: 'gcp', label: 'Google Cloud' }];

	let enabledCloudProviders: string[] = [];
	let cloudAccountExpanded: Record<string, boolean> = {};
	let showAddCloudAccountMenu = false;

	$: availableCloudProviders = CLOUD_PROVIDERS.filter(
		(p) => !enabledCloudProviders.includes(p.id)
	);

	const addCloudAccount = async (providerId: string) => {
		if (!enabledCloudProviders.includes(providerId)) {
			enabledCloudProviders = [...enabledCloudProviders, providerId];
			cloudAccountExpanded[providerId] = true;
			if (providerId === 'gcp') {
				googleCloudConfig.GOOGLE_CLOUD_ENABLED = true;
				await updateGoogleCloudHandler(true);
			}
		}
		showAddCloudAccountMenu = false;
	};

	const removeCloudAccount = async (providerId: string) => {
		if (providerId === 'gcp') {
			googleCloudConfig.GOOGLE_CLOUD_ENABLED = false;
			googleCloudConfig.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY = '';
			await updateGoogleCloudHandler();
		}
		enabledCloudProviders = enabledCloudProviders.filter((id) => id !== providerId);
		delete cloudAccountExpanded[providerId];
	};

	const getModels = async () => {
		const models = await _getModels(
			localStorage.token,
			$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
		);
		return models;
	};

	// External
	let OLLAMA_BASE_URLS = [''];
	let OLLAMA_API_CONFIGS = {};

	let OPENAI_API_KEYS = [''];
	let OPENAI_API_BASE_URLS = [''];
	let OPENAI_API_CONFIGS = {};

	let ENABLE_OPENAI_API: null | boolean = null;
	let ENABLE_OLLAMA_API: null | boolean = null;

	let directConnectionsConfig = null;
	let googleCloudConfig = { GOOGLE_CLOUD_ENABLED: false, GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY: '' };

	// Gmail / Calendar / Drive 채팅 통합 admin 토글 (T-B09 endpoint).
	// GOOGLE_OAUTH_CONFIGURED 는 read-only — Google OAuth 자격증명
	// (GOOGLE_CLIENT_ID/SECRET) 미설정이면 섹션 자체를 렌더링하지 않는다.
	let googleIntegrationConfig: {
		ENABLE_GMAIL_INTEGRATION: boolean | null;
		ENABLE_CALENDAR_INTEGRATION: boolean | null;
		ENABLE_DRIVE_INTEGRATION: boolean | null;
		GOOGLE_OAUTH_CONFIGURED: boolean;
	} = {
		ENABLE_GMAIL_INTEGRATION: false,
		ENABLE_CALENDAR_INTEGRATION: false,
		ENABLE_DRIVE_INTEGRATION: false,
		GOOGLE_OAUTH_CONFIGURED: false
	};
	let storageConfig: StorageConfig | null = null;
	let fileStorageConfig: FileStorageConfig = { provider: 'local', s3: null, azure: null, gcs: null };
	let fileStorageLoaded = false;
	let testingConnection = false;
	let testingFileConnection = false;
	let imageGcsCredentialSource: 'global' | 'custom' = 'global';
	let fileGcsCredentialSource: 'global' | 'custom' = 'global';

	// Default storage configurations
	const defaultS3Config: S3Config = {
		bucket_name: '',
		region_name: 'us-east-1',
		endpoint_url: '',
		access_key_id: '',
		secret_access_key: '',
		key_prefix: ''
	};

	const defaultAzureConfig: AzureConfig = {
		endpoint: '',
		container_name: '',
		storage_key: ''
	};

	const defaultGCSConfig: GCSConfig = {
		bucket_name: '',
		credentials_json: ''
	};

	$: imageUploadModeOptions = [
		{ value: 'base64', label: $i18n.t('Base64 Inline') },
		{ value: 'storage', label: $i18n.t('Cloud Storage') }
	];

	$: storageProviderOptions = [
		{ value: 'local', label: $i18n.t('Local Storage') },
		{ value: 's3', label: $i18n.t('AWS S3') },
		{ value: 'azure', label: $i18n.t('Azure Blob') },
		{ value: 'gcs', label: $i18n.t('Google Cloud Storage') }
	];

	$: gcsCredentialSourceOptions = [
		{ value: 'global', label: $i18n.t('Use Global Google Cloud Key') },
		{ value: 'custom', label: $i18n.t('Use Custom Key') }
	];

	let pipelineUrls = {};
	let showAddOpenAIConnectionModal = false;
	let showAddOllamaConnectionModal = false;

	const updateOpenAIHandler = async (silent = false) => {
		if (ENABLE_OPENAI_API === null) return true;

		// Remove trailing slashes
		OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS.map((url) => url.replace(/\/$/, ''));

		// Check if API KEYS length is same than API URLS length
		if (OPENAI_API_KEYS.length !== OPENAI_API_BASE_URLS.length) {
			// if there are more keys than urls, remove the extra keys
			if (OPENAI_API_KEYS.length > OPENAI_API_BASE_URLS.length) {
				OPENAI_API_KEYS = OPENAI_API_KEYS.slice(0, OPENAI_API_BASE_URLS.length);
			}

			// if there are more urls than keys, add empty keys
			if (OPENAI_API_KEYS.length < OPENAI_API_BASE_URLS.length) {
				const diff = OPENAI_API_BASE_URLS.length - OPENAI_API_KEYS.length;
				for (let i = 0; i < diff; i++) {
					OPENAI_API_KEYS.push('');
				}
			}
		}

		const res = await updateOpenAIConfig(localStorage.token, {
			ENABLE_OPENAI_API: ENABLE_OPENAI_API,
			OPENAI_API_BASE_URLS: OPENAI_API_BASE_URLS,
			OPENAI_API_KEYS: OPENAI_API_KEYS,
			OPENAI_API_CONFIGS: OPENAI_API_CONFIGS
		}).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		if (res) {
			if (!silent) toast.success($i18n.t('OpenAI API settings updated'));
			await models.set(await getModels());
			return true;
		}
		return false;
	};

	const updateOllamaHandler = async (silent = false) => {
		if (ENABLE_OLLAMA_API === null) return true;

		// Remove trailing slashes
		OLLAMA_BASE_URLS = OLLAMA_BASE_URLS.map((url) => url.replace(/\/$/, ''));

		const res = await updateOllamaConfig(localStorage.token, {
			ENABLE_OLLAMA_API: ENABLE_OLLAMA_API,
			OLLAMA_BASE_URLS: OLLAMA_BASE_URLS,
			OLLAMA_API_CONFIGS: OLLAMA_API_CONFIGS
		}).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		if (res) {
			if (!silent) toast.success($i18n.t('Ollama API settings updated'));
			await models.set(await getModels());
			return true;
		}
		return false;
	};

	const updateStorageHandler = async () => {
		if (!storageConfig) return true;
		const res = await setStorageConfig(localStorage.token, storageConfig).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});
		return !!res;
	};

	const updateFileStorageHandler = async () => {
		const res = await setFileStorageConfig(localStorage.token, fileStorageConfig).catch(
			(error) => {
				toast.error($i18n.t(`${error}`));
			}
		);
		return !!res;
	};

	const testFileConnection = async () => {
		testingFileConnection = true;
		try {
			const testConfig: { provider: string; s3?: S3Config; azure?: AzureConfig; gcs?: GCSConfig } =
				{ provider: fileStorageConfig.provider };
			if (fileStorageConfig.provider === 's3' && fileStorageConfig.s3)
				testConfig.s3 = fileStorageConfig.s3;
			else if (fileStorageConfig.provider === 'azure' && fileStorageConfig.azure)
				testConfig.azure = fileStorageConfig.azure;
			else if (fileStorageConfig.provider === 'gcs' && fileStorageConfig.gcs)
				testConfig.gcs = fileStorageConfig.gcs;

			const result = await testFileStorageConnection(localStorage.token, testConfig);
			if (result) toast.success($i18n.t(result.message || 'Connection successful'));
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			testingFileConnection = false;
		}
	};

	const testConnection = async () => {
		if (!storageConfig) return;
		testingConnection = true;

		try {
			const testConfig: { provider: string; s3?: S3Config; azure?: AzureConfig; gcs?: GCSConfig } = {
				provider: storageConfig.provider
			};

			if (storageConfig.provider === 's3' && storageConfig.s3) {
				testConfig.s3 = storageConfig.s3;
			} else if (storageConfig.provider === 'azure' && storageConfig.azure) {
				testConfig.azure = storageConfig.azure;
			} else if (storageConfig.provider === 'gcs' && storageConfig.gcs) {
				testConfig.gcs = storageConfig.gcs;
			}

			const result = await testStorageConnection(localStorage.token, testConfig);
			if (result) {
				toast.success($i18n.t(result.message || 'Connection successful'));
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			testingConnection = false;
		}
	};

	const updateDirectConnectionsHandler = async (silent = false) => {
		const res = await setDirectConnectionsConfig(localStorage.token, directConnectionsConfig).catch(
			(error) => {
				toast.error($i18n.t(`${error}`));
			}
		);

		if (res) {
			if (!silent) toast.success($i18n.t('Direct Connections settings updated'));
			await models.set(await getModels());
			return true;
		}
		return false;
	};

	const updateGoogleCloudHandler = async (silent = false) => {
		const res = await setGoogleCloudConfig(localStorage.token, googleCloudConfig).catch(
			(error) => {
				toast.error($i18n.t(`${error}`));
			}
		);

		if (res) {
			googleCloudConfig = res;
			if (!silent) toast.success($i18n.t('Google Cloud settings updated'));
			return true;
		}
		return false;
	};

	const updateGoogleIntegrationHandler = async (
		next: {
			ENABLE_GMAIL_INTEGRATION?: boolean;
			ENABLE_CALENDAR_INTEGRATION?: boolean;
			ENABLE_DRIVE_INTEGRATION?: boolean;
		},
		silent = false
	) => {
		const res = await setGoogleIntegrationConfig(localStorage.token, next).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});
		if (res) {
			googleIntegrationConfig = {
				ENABLE_GMAIL_INTEGRATION: res.ENABLE_GMAIL_INTEGRATION ?? false,
				ENABLE_CALENDAR_INTEGRATION: res.ENABLE_CALENDAR_INTEGRATION ?? false,
				ENABLE_DRIVE_INTEGRATION: res.ENABLE_DRIVE_INTEGRATION ?? false,
				GOOGLE_OAUTH_CONFIGURED:
					res.GOOGLE_OAUTH_CONFIGURED ?? googleIntegrationConfig.GOOGLE_OAUTH_CONFIGURED
			};
			if (!silent) toast.success($i18n.t('Google Workspace settings updated'));
			return true;
		}
		return false;
	};

	const addOpenAIConnectionHandler = async (connection) => {
		OPENAI_API_BASE_URLS = [...OPENAI_API_BASE_URLS, connection.url];
		OPENAI_API_KEYS = [...OPENAI_API_KEYS, connection.key];
		OPENAI_API_CONFIGS[OPENAI_API_BASE_URLS.length - 1] = connection.config;

		await updateOpenAIHandler();
	};

	const addOllamaConnectionHandler = async (connection) => {
		OLLAMA_BASE_URLS = [...OLLAMA_BASE_URLS, connection.url];
		OLLAMA_API_CONFIGS[OLLAMA_BASE_URLS.length - 1] = {
			...connection.config,
			key: connection.key
		};

		await updateOllamaHandler();
	};

	onMount(async () => {
		if ($user?.role === 'admin') {
			let ollamaConfig = {};
			let openaiConfig = {};

			await Promise.all([
				(async () => {
					ollamaConfig = await getOllamaConfig(localStorage.token);
				})(),
				(async () => {
					openaiConfig = await getOpenAIConfig(localStorage.token);
				})(),
				(async () => {
					directConnectionsConfig = await getDirectConnectionsConfig(localStorage.token);
				})(),
				(async () => {
					try {
						googleCloudConfig = await getGoogleCloudConfig(localStorage.token);
					} catch (error) {
						console.error('Failed to load Google Cloud config:', error);
					}
				})(),
				(async () => {
					try {
						const cfg = await getGoogleIntegrationConfig(localStorage.token);
						googleIntegrationConfig = {
							ENABLE_GMAIL_INTEGRATION: cfg.ENABLE_GMAIL_INTEGRATION ?? false,
							ENABLE_CALENDAR_INTEGRATION: cfg.ENABLE_CALENDAR_INTEGRATION ?? false,
							ENABLE_DRIVE_INTEGRATION: cfg.ENABLE_DRIVE_INTEGRATION ?? false,
							GOOGLE_OAUTH_CONFIGURED: cfg.GOOGLE_OAUTH_CONFIGURED ?? false
						};
					} catch (error) {
						console.error('Failed to load Google Integration config:', error);
					}
				})(),
				(async () => {
					try {
						const storageRes = await getStorageConfig(localStorage.token);
						if (storageRes) {
							storageConfig = storageRes;
							if (!storageConfig.s3) {
								storageConfig.s3 = { ...defaultS3Config };
							}
							if (!storageConfig.azure) {
								storageConfig.azure = { ...defaultAzureConfig };
							}
							if (!storageConfig.gcs) {
								storageConfig.gcs = { ...defaultGCSConfig };
							}
							imageGcsCredentialSource = storageConfig.gcs?.credentials_json ? 'custom' : 'global';
						}
					} catch (error) {
						toast.error($i18n.t(`${error}`));
					}
				})(),
			(async () => {
					try {
						const res = await getFileStorageConfig(localStorage.token);
						if (res) {
							fileStorageConfig = res;
							if (!fileStorageConfig.s3) fileStorageConfig.s3 = { ...defaultS3Config };
							if (!fileStorageConfig.azure)
								fileStorageConfig.azure = { ...defaultAzureConfig };
							if (!fileStorageConfig.gcs) fileStorageConfig.gcs = { ...defaultGCSConfig };
							fileGcsCredentialSource = fileStorageConfig.gcs?.credentials_json ? 'custom' : 'global';
						}
					} catch (error) {
						console.error('Failed to load file storage config:', error);
					} finally {
						fileStorageLoaded = true;
					}
				})(),
			]);

			// Initialize cloud providers based on loaded config
			if (googleCloudConfig.GOOGLE_CLOUD_ENABLED) {
				enabledCloudProviders = ['gcp'];
			}

			ENABLE_OPENAI_API = openaiConfig.ENABLE_OPENAI_API;
			ENABLE_OLLAMA_API = ollamaConfig.ENABLE_OLLAMA_API;

			OPENAI_API_BASE_URLS = openaiConfig.OPENAI_API_BASE_URLS;
			OPENAI_API_KEYS = openaiConfig.OPENAI_API_KEYS;
			OPENAI_API_CONFIGS = openaiConfig.OPENAI_API_CONFIGS;

			OLLAMA_BASE_URLS = ollamaConfig.OLLAMA_BASE_URLS;
			OLLAMA_API_CONFIGS = ollamaConfig.OLLAMA_API_CONFIGS;

			if (ENABLE_OPENAI_API) {
				// get url and idx
				for (const [idx, url] of OPENAI_API_BASE_URLS.entries()) {
					if (!OPENAI_API_CONFIGS[idx]) {
						// Legacy support, url as key
						OPENAI_API_CONFIGS[idx] = OPENAI_API_CONFIGS[url] || {};
					}
				}

				OPENAI_API_BASE_URLS.forEach(async (url, idx) => {
					OPENAI_API_CONFIGS[idx] = OPENAI_API_CONFIGS[idx] || {};
					if (!(OPENAI_API_CONFIGS[idx]?.enable ?? true)) {
						return;
					}
					const res = await getOpenAIModels(localStorage.token, idx);
					if (res.pipelines) {
						pipelineUrls[url] = true;
					}
				});
			}

			if (ENABLE_OLLAMA_API) {
				for (const [idx, url] of OLLAMA_BASE_URLS.entries()) {
					if (!OLLAMA_API_CONFIGS[idx]) {
						OLLAMA_API_CONFIGS[idx] = OLLAMA_API_CONFIGS[url] || {};
					}
				}
			}
		}
	});

	const submitHandler = async () => {
		const results = await Promise.all([
			updateOpenAIHandler(true),
			updateOllamaHandler(true),
			updateDirectConnectionsHandler(true),
			updateGoogleCloudHandler(true),
			updateStorageHandler(),
			updateFileStorageHandler()
		]);

		if (results.every(Boolean)) {
			dispatch('save');
		}
	};
</script>

<AddConnectionModal
	bind:show={showAddOpenAIConnectionModal}
	onSubmit={addOpenAIConnectionHandler}
/>

<AddConnectionModal
	ollama
	bind:show={showAddOllamaConnectionModal}
	onSubmit={addOllamaConnectionHandler}
/>

<form class="flex flex-col h-full justify-between text-sm" on:submit|preventDefault={submitHandler}>
	<div class=" overflow-y-scroll scrollbar-hidden h-full">
		{#if ENABLE_OPENAI_API !== null && ENABLE_OLLAMA_API !== null && directConnectionsConfig !== null}
			<div class="my-2">
				<div class="mt-2 space-y-2 pr-1.5">
					<div class="flex justify-between items-center text-sm">
						<div class="  font-medium">{$i18n.t('AI Provider')}</div>

						<div class="flex items-center">
							<div class="">
								<Switch
									bind:state={ENABLE_OPENAI_API}
									on:change={async () => {
										updateOpenAIHandler();
									}}
								/>
							</div>
						</div>
					</div>

					{#if ENABLE_OPENAI_API}
						<hr class=" border-gray-100 dark:border-gray-850" />

						<div class="">
							<div class="flex justify-between items-center">
								<div class="font-medium">{$i18n.t('Manage AI Provider Connections')}</div>

								<Tooltip content={$i18n.t(`Add Connection`)}>
									<button
										class="px-1"
										on:click={() => {
											showAddOpenAIConnectionModal = true;
										}}
										type="button"
									>
										<Plus />
									</button>
								</Tooltip>
							</div>

							<div class="flex flex-col gap-1.5 mt-1.5">
								{#each OPENAI_API_BASE_URLS as url, idx}
									<OpenAIConnection
										pipeline={pipelineUrls[url] ? true : false}
										bind:url
										bind:key={OPENAI_API_KEYS[idx]}
										bind:config={OPENAI_API_CONFIGS[idx]}
										onSubmit={() => {
											updateOpenAIHandler();
										}}
										onDelete={() => {
											OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS.filter(
												(url, urlIdx) => idx !== urlIdx
											);
											OPENAI_API_KEYS = OPENAI_API_KEYS.filter((key, keyIdx) => idx !== keyIdx);

											let newConfig = {};
											OPENAI_API_BASE_URLS.forEach((url, newIdx) => {
												newConfig[newIdx] = OPENAI_API_CONFIGS[newIdx < idx ? newIdx : newIdx + 1];
											});
											OPENAI_API_CONFIGS = newConfig;
											updateOpenAIHandler();
										}}
									/>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			</div>

			<hr class=" border-gray-100 dark:border-gray-850" />

			<div class="pr-1.5 my-2">
				<div class="flex justify-between items-center text-sm mb-2">
					<div class="  font-medium">{$i18n.t('Ollama API')}</div>

					<div class="mt-1">
						<Switch
							bind:state={ENABLE_OLLAMA_API}
							on:change={async () => {
								updateOllamaHandler();
							}}
						/>
					</div>
				</div>

				{#if ENABLE_OLLAMA_API}
					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="">
						<div class="flex justify-between items-center">
							<div class="font-medium">{$i18n.t('Manage Ollama API Connections')}</div>

							<Tooltip content={$i18n.t(`Add Connection`)}>
								<button
									class="px-1"
									on:click={() => {
										showAddOllamaConnectionModal = true;
									}}
									type="button"
								>
									<Plus />
								</button>
							</Tooltip>
						</div>

						<div class="flex w-full gap-1.5">
							<div class="flex-1 flex flex-col gap-1.5 mt-1.5">
								{#each OLLAMA_BASE_URLS as url, idx}
									<OllamaConnection
										bind:url
										bind:config={OLLAMA_API_CONFIGS[idx]}
										{idx}
										onSubmit={() => {
											updateOllamaHandler();
										}}
										onDelete={() => {
											OLLAMA_BASE_URLS = OLLAMA_BASE_URLS.filter((url, urlIdx) => idx !== urlIdx);

											let newConfig = {};
											OLLAMA_BASE_URLS.forEach((url, newIdx) => {
												newConfig[newIdx] = OLLAMA_API_CONFIGS[newIdx < idx ? newIdx : newIdx + 1];
											});
											OLLAMA_API_CONFIGS = newConfig;
										}}
									/>
								{/each}
							</div>
						</div>

						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Trouble accessing Ollama?')}
							<a
								class=" text-gray-300 font-medium underline"
								href="/guide"
								target="_blank"
							>
								{$i18n.t('Click here for help.')}
							</a>
						</div>
					</div>
				{/if}
			</div>

			<hr class=" border-gray-100 dark:border-gray-850" />

			<div class="pr-1.5 my-2">
				<div class="flex justify-between items-center text-sm">
					<div class="  font-medium">{$i18n.t('Direct Connections')}</div>

					<div class="flex items-center">
						<div class="">
							<Switch
								bind:state={directConnectionsConfig.ENABLE_DIRECT_CONNECTIONS}
								on:change={async () => {
									updateDirectConnectionsHandler();
								}}
							/>
						</div>
					</div>
				</div>

				<div class="mt-1.5">
					<div class="text-xs text-gray-500">
						{$i18n.t(
							'Direct Connections allow users to connect to their own OpenAI compatible API endpoints.'
						)}
					</div>
				</div>
			</div>

			<hr class=" border-gray-100 dark:border-gray-850" />

			<!-- Cloud Accounts -->
			<div class="pr-1.5 my-2">
				<div class="flex justify-between items-center text-sm mb-2">
					<div class="font-medium">{$i18n.t('Cloud Accounts')}</div>

					<div class="relative">
						{#if availableCloudProviders.length > 0}
							<Tooltip content={$i18n.t('Add Cloud Account')}>
								<button
									class="px-1"
									type="button"
									on:click={() => {
										showAddCloudAccountMenu = !showAddCloudAccountMenu;
									}}
								>
									<Plus />
								</button>
							</Tooltip>
						{/if}

						{#if showAddCloudAccountMenu}
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="fixed inset-0 z-10"
								on:click={() => {
									showAddCloudAccountMenu = false;
								}}
							/>
							<div
								class="absolute right-0 mt-1 z-20 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg py-1 min-w-[160px]"
							>
								{#each availableCloudProviders as provider}
									<button
										class="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
										type="button"
										on:click={() => addCloudAccount(provider.id)}
									>
										{$i18n.t(provider.label)}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				</div>

				<div class="mb-1.5 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Global service account key used as fallback when individual features have no key configured.'
					)}
				</div>

				{#if enabledCloudProviders.length === 0}
					<div class="text-center text-xs text-gray-400 dark:text-gray-500 py-3">
						{$i18n.t('No cloud accounts configured. Click + to add one.')}
					</div>
				{:else}
					<div class="flex flex-col gap-1.5">
						{#each enabledCloudProviders as providerId}
							{@const provider = CLOUD_PROVIDERS.find((p) => p.id === providerId)}
							{#if provider}
								<div class="border border-gray-200 dark:border-gray-700 rounded-lg">
									<!-- Accordion Header -->
									<div class="flex items-center justify-between px-3 py-2">
										<button
											class="flex items-center gap-2 flex-1 text-left"
											type="button"
											on:click={() => {
												cloudAccountExpanded[providerId] = !cloudAccountExpanded[providerId];
											}}
										>
											{#if cloudAccountExpanded[providerId]}
												<ChevronUp className="size-3.5" />
											{:else}
												<ChevronDown className="size-3.5" />
											{/if}
											<span class="text-sm font-medium">{$i18n.t(provider.label)}</span>
										</button>

										<div class="flex items-center gap-1.5">
											{#if providerId === 'gcp'}
												{#if googleCloudConfig.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY}
													<span
														class="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-1.5 py-0.5 rounded"
													>
														{$i18n.t('Configured')}
													</span>
												{:else if googleCloudConfig.GOOGLE_CLOUD_ENABLED}
													<span
														class="text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 px-1.5 py-0.5 rounded"
													>
														{$i18n.t('Using ADC')}
													</span>
												{/if}
											{/if}

											<Tooltip content={$i18n.t('Delete')}>
												<button
													class="p-0.5 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition"
													type="button"
													on:click={() => removeCloudAccount(providerId)}
												>
													<XMark className="size-3.5" />
												</button>
											</Tooltip>
										</div>
									</div>

									<!-- Accordion Content -->
									{#if cloudAccountExpanded[providerId]}
										<div class="px-3 pb-3 border-t border-gray-100 dark:border-gray-800" transition:slide={{ duration: 200 }}>
											{#if providerId === 'gcp'}
												<div class="mt-2.5 flex flex-col w-full">
													<div class="mb-1 text-xs font-medium">
														{$i18n.t('Service Account Key (JSON)')}
													</div>
													<SensitiveTextarea
														placeholder={'{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}'}
														rows={4}
														bind:value={googleCloudConfig.GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY}
													/>
													<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
														{$i18n.t('Leave empty to use Application Default Credentials.')}
													</div>
												</div>
											{/if}
										</div>
									{/if}
								</div>
							{/if}
						{/each}
					</div>
				{/if}
			</div>

			<!-- Google Workspace Integration (Gmail / Calendar 채팅 통합) -->
			<!-- Google OAuth 자격증명 미설정이면 사용자가 연결할 방법이 없어 토글이 무의미 → 섹션 숨김 -->
			{#if googleIntegrationConfig.GOOGLE_OAUTH_CONFIGURED}
			<hr class=" border-gray-100 dark:border-gray-850" />

			<div class="pr-1.5 my-2">
				<div class="flex justify-between items-center text-sm mb-2">
					<div class="font-medium">{$i18n.t('Google Workspace Integration')}</div>
				</div>
				<div class="mb-2 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Allow users to send Gmail messages, create Calendar events, and create Google Docs in Drive from chat. Requires user Google OAuth connection and group permission. Disabled by default for safety.'
					)}
				</div>

				<div class="mb-2 flex w-full justify-between items-center gap-2">
					<div>
						<div class="text-xs font-medium">{$i18n.t('Gmail Integration')}</div>
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t('Sensitive scope (gmail.send) requires Google App verification.')}
						</div>
					</div>
					<Switch
						state={!!googleIntegrationConfig.ENABLE_GMAIL_INTEGRATION}
						on:change={(e) =>
							updateGoogleIntegrationHandler({ ENABLE_GMAIL_INTEGRATION: e.detail })}
					/>
				</div>

				<div class="mb-2 flex w-full justify-between items-center gap-2">
					<div>
						<div class="text-xs font-medium">{$i18n.t('Calendar Integration')}</div>
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t(
								'Restricted scope (calendar.events) requires CASA Tier 2 security audit.'
							)}
						</div>
					</div>
					<Switch
						state={!!googleIntegrationConfig.ENABLE_CALENDAR_INTEGRATION}
						on:change={(e) =>
							updateGoogleIntegrationHandler({ ENABLE_CALENDAR_INTEGRATION: e.detail })}
					/>
				</div>

				<div class="mb-2 flex w-full justify-between items-center gap-2">
					<div>
						<div class="text-xs font-medium">{$i18n.t('Drive Integration')}</div>
						<div class="text-[11px] text-gray-400 dark:text-gray-500">
							{$i18n.t('Restricted scope (drive) requires CASA Tier 2 security audit.')}
						</div>
					</div>
					<Switch
						state={!!googleIntegrationConfig.ENABLE_DRIVE_INTEGRATION}
						on:change={(e) =>
							updateGoogleIntegrationHandler({ ENABLE_DRIVE_INTEGRATION: e.detail })}
					/>
				</div>
			</div>
			{/if}

			<!-- Image Attachment Mode Settings -->
			{#if storageConfig}
				<hr class=" border-gray-100 dark:border-gray-850" />

				<div class="pr-1.5 my-2">
					<div class="flex justify-between items-center text-sm mb-2">
						<div class="font-medium">{$i18n.t('Image Attachment Mode')}</div>
					</div>
					<div class="mb-1.5 text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Controls how images attached to chat are processed and stored.')}
					</div>

					<div class="mb-2.5 flex w-full justify-between items-center gap-2">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Image Upload Mode')}
						</div>
						<div class="min-w-[14rem]">
							<Selector
								value={storageConfig.image_upload_mode}
								items={imageUploadModeOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									if (storageConfig) storageConfig.image_upload_mode = e.detail.value;
								}}
							/>
						</div>
					</div>

					{#if storageConfig.image_upload_mode === 'storage'}
						<div class="mb-2.5 flex w-full justify-between items-center gap-2">
							<div class="self-center text-xs font-medium">
								{$i18n.t('Storage Provider')}
							</div>
							<div class="min-w-[14rem]">
								<Selector
									value={storageConfig.provider}
									items={storageProviderOptions}
									size="sm"
									searchEnabled={false}
									on:change={(e) => {
										if (storageConfig) storageConfig.provider = e.detail.value;
									}}
								/>
							</div>
						</div>

						{#if storageConfig.provider === 'local'}
							<div class="mt-1 mb-1 text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Files will be stored on the server disk. No additional configuration required.')}
							</div>
						{:else if storageConfig.provider === 's3' && storageConfig.s3}
							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.s3.bucket_name}
										placeholder={$i18n.t('Bucket Name')}
										size="sm"
									/>
								</div>
								<div class="flex-1">
									<Input
										bind:value={storageConfig.s3.region_name}
										placeholder={$i18n.t('Region')}
										size="sm"
									/>
								</div>
							</div>

							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.s3.endpoint_url}
										placeholder={$i18n.t('Endpoint URL (Optional)')}
										size="sm"
									/>
								</div>
							</div>

							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.s3.access_key_id}
										placeholder={$i18n.t('Access Key ID')}
										size="sm"
									/>
								</div>
								<div class="flex-1">
									<SensitiveInput
										placeholder={$i18n.t('Secret Access Key')}
										bind:value={storageConfig.s3.secret_access_key}
										required={false}
									/>
								</div>
							</div>

							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.s3.key_prefix}
										placeholder={$i18n.t('Key Prefix (Optional)')}
										size="sm"
									/>
								</div>
							</div>

							<div class="mb-2.5 flex w-full justify-between items-center">
								<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
								<Button
									kind="text"
									size="sm"
									type="button"
									disabled={testingConnection}
									loading={testingConnection}
									on:click={testConnection}
								>
									{testingConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
								</Button>
							</div>
						{:else if storageConfig.provider === 'azure' && storageConfig.azure}
							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.azure.endpoint}
										placeholder={$i18n.t('Storage Endpoint')}
										size="sm"
									/>
								</div>
							</div>

							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.azure.container_name}
										placeholder={$i18n.t('Container Name')}
										size="sm"
									/>
								</div>
								<div class="flex-1">
									<SensitiveInput
										placeholder={$i18n.t('Storage Key')}
										bind:value={storageConfig.azure.storage_key}
										required={false}
									/>
								</div>
							</div>

							<div class="mb-2.5 flex w-full justify-between items-center">
								<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
								<Button
									kind="text"
									size="sm"
									type="button"
									disabled={testingConnection}
									loading={testingConnection}
									on:click={testConnection}
								>
									{testingConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
								</Button>
							</div>
						{:else if storageConfig.provider === 'gcs' && storageConfig.gcs}
							<div class="my-0.5 flex gap-2 pr-2">
								<div class="flex-1">
									<Input
										bind:value={storageConfig.gcs.bucket_name}
										placeholder={$i18n.t('Bucket Name')}
										size="sm"
									/>
								</div>
							</div>

							<div class="mb-2.5 flex flex-col w-full">
								<div class="mb-1.5 flex gap-2 items-center">
									<div class="text-xs font-medium shrink-0">{$i18n.t('Authentication')}</div>
									<div class="min-w-[200px]">
										<Selector
											value={imageGcsCredentialSource}
											items={gcsCredentialSourceOptions}
											size="sm"
											searchEnabled={false}
											on:change={(e) => {
												imageGcsCredentialSource = e.detail.value;
												if (imageGcsCredentialSource === 'global' && storageConfig?.gcs) {
													storageConfig.gcs.credentials_json = '';
												}
											}}
										/>
									</div>
								</div>
								{#if imageGcsCredentialSource === 'custom'}
									<div class="mb-1 text-xs font-medium">{$i18n.t('Service Account JSON')}</div>
									<SensitiveTextarea
										placeholder={'{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}'}
										rows={4}
										bind:value={storageConfig.gcs.credentials_json}
									/>
								{/if}
							</div>

							<div class="mb-2.5 flex w-full justify-between items-center">
								<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
								<Button
									kind="text"
									size="sm"
									type="button"
									disabled={testingConnection}
									loading={testingConnection}
									on:click={testConnection}
								>
									{testingConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
								</Button>
							</div>
						{/if}
					{/if}
				</div>
			{/if}

			<!-- Shared Storage (File Uploads) Settings -->
			<hr class=" border-gray-100 dark:border-gray-850" />

			<div class="pr-1.5 my-2">
				<div class="flex justify-between items-center text-sm mb-2">
					<div class="font-medium">{$i18n.t('Shared Storage')}</div>
				</div>
				<div class="mb-2.5 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Controls where uploaded files (documents, PDFs, etc.) are stored. Uses the same cloud credentials configured in Image Attachment Mode.'
					)}
				</div>

				<div class="mb-2.5 flex w-full justify-between items-center gap-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('File Storage Provider')}
					</div>
					<div class="min-w-[14rem]">
						<Selector
							value={fileStorageConfig.provider}
							items={storageProviderOptions}
							size="sm"
							searchEnabled={false}
							on:change={(e) => {
								fileStorageConfig.provider = e.detail.value;
							}}
						/>
					</div>
				</div>

				{#if fileStorageConfig.provider === 'local'}
					<div class="mt-1 mb-1 text-xs text-gray-400 dark:text-gray-500">
						{$i18n.t('Files will be stored on the server disk. No additional configuration required.')}
					</div>
				{:else if fileStorageConfig.provider === 's3' && fileStorageConfig.s3}
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.s3.bucket_name}
								placeholder={$i18n.t('Bucket Name')}
								size="sm"
							/>
						</div>
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.s3.region_name}
								placeholder={$i18n.t('Region')}
								size="sm"
							/>
						</div>
					</div>
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.s3.endpoint_url}
								placeholder={$i18n.t('Endpoint URL (Optional)')}
								size="sm"
							/>
						</div>
					</div>
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.s3.access_key_id}
								placeholder={$i18n.t('Access Key ID')}
								size="sm"
							/>
						</div>
						<div class="flex-1">
							<SensitiveInput
								placeholder={$i18n.t('Secret Access Key')}
								bind:value={fileStorageConfig.s3.secret_access_key}
								required={false}
							/>
						</div>
					</div>
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.s3.key_prefix}
								placeholder={$i18n.t('Key Prefix (Optional)')}
								size="sm"
							/>
						</div>
					</div>
					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
						<Button
							kind="text"
							size="sm"
							type="button"
							disabled={testingFileConnection}
							loading={testingFileConnection}
							on:click={testFileConnection}
						>
							{testingFileConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
						</Button>
					</div>
				{:else if fileStorageConfig.provider === 'azure' && fileStorageConfig.azure}
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.azure.endpoint}
								placeholder={$i18n.t('Storage Endpoint')}
								size="sm"
							/>
						</div>
					</div>
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.azure.container_name}
								placeholder={$i18n.t('Container Name')}
								size="sm"
							/>
						</div>
						<div class="flex-1">
							<SensitiveInput
								placeholder={$i18n.t('Storage Key')}
								bind:value={fileStorageConfig.azure.storage_key}
								required={false}
							/>
						</div>
					</div>
					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
						<Button
							kind="text"
							size="sm"
							type="button"
							disabled={testingFileConnection}
							loading={testingFileConnection}
							on:click={testFileConnection}
						>
							{testingFileConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
						</Button>
					</div>
				{:else if fileStorageConfig.provider === 'gcs' && fileStorageConfig.gcs}
					<div class="my-0.5 flex gap-2 pr-2">
						<div class="flex-1">
							<Input
								bind:value={fileStorageConfig.gcs.bucket_name}
								placeholder={$i18n.t('Bucket Name')}
								size="sm"
							/>
						</div>
					</div>
					<div class="mb-2.5 flex flex-col w-full">
						<div class="mb-1.5 flex gap-2 items-center">
							<div class="text-xs font-medium shrink-0">{$i18n.t('Authentication')}</div>
							<div class="min-w-[200px]">
								<Selector
									value={fileGcsCredentialSource}
									items={gcsCredentialSourceOptions}
									size="sm"
									searchEnabled={false}
									on:change={(e) => {
										fileGcsCredentialSource = e.detail.value;
										if (fileGcsCredentialSource === 'global' && fileStorageConfig?.gcs) {
											fileStorageConfig.gcs.credentials_json = '';
										}
									}}
								/>
							</div>
						</div>
						{#if fileGcsCredentialSource === 'custom'}
							<div class="mb-1 text-xs font-medium">{$i18n.t('Service Account JSON')}</div>
							<SensitiveTextarea
								placeholder={'{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}'}
								rows={4}
								bind:value={fileStorageConfig.gcs.credentials_json}
							/>
						{/if}
					</div>
					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Test Connection')}</div>
						<Button
							kind="text"
							size="sm"
							type="button"
							disabled={testingFileConnection}
							loading={testingFileConnection}
							on:click={testFileConnection}
						>
							{testingFileConnection ? $i18n.t('Testing...') : $i18n.t('Test')}
						</Button>
					</div>
				{/if}
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
		<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
