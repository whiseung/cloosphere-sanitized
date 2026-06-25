<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { config as backendConfig, user } from '$lib/stores';

	import { getBackendConfig } from '$lib/apis';
	import {
		getConfig,
		updateConfig,
		getImageConnectionsConfig,
		updateImageConnectionsConfig
	} from '$lib/apis/images';
	import Button from '$lib/components/common/Button.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ImageConnection from './Connections/ImageConnection.svelte';
	import AddImageConnectionModal from './Connections/AddImageConnectionModal.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let loading = false;

	let config = null;

	// Image connections
	let IMAGE_API_URLS: string[] = [];
	let IMAGE_API_KEYS: string[] = [];
	let IMAGE_API_CONFIGS: Record<string, any> = {};
	let showAddImageConnectionModal = false;

	const updateConfigHandler = async () => {
		const res = await updateConfig(localStorage.token, config)
			.catch((error) => {
				toast.error($i18n.t(`${error}`));
				return null;
			});

		if (res) {
			config = res;
		}

		if (config.enabled) {
			backendConfig.set(await getBackendConfig());
		}
	};

	const updateImageConnectionsHandler = async () => {
		if (IMAGE_API_KEYS.length !== IMAGE_API_URLS.length) {
			if (IMAGE_API_KEYS.length > IMAGE_API_URLS.length) {
				IMAGE_API_KEYS = IMAGE_API_KEYS.slice(0, IMAGE_API_URLS.length);
			}
			if (IMAGE_API_KEYS.length < IMAGE_API_URLS.length) {
				const diff = IMAGE_API_URLS.length - IMAGE_API_KEYS.length;
				for (let i = 0; i < diff; i++) {
					IMAGE_API_KEYS.push('');
				}
			}
		}

		const res = await updateImageConnectionsConfig(localStorage.token, {
			IMAGE_API_URLS: IMAGE_API_URLS,
			IMAGE_API_KEYS: IMAGE_API_KEYS,
			IMAGE_API_CONFIGS: IMAGE_API_CONFIGS
		}).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});

		if (res) {
			toast.success($i18n.t('Image connection settings updated'));
		}
	};

	const addImageConnectionHandler = async (connection: {
		url: string;
		key: string;
		config: Record<string, any>;
	}) => {
		IMAGE_API_URLS = [...IMAGE_API_URLS, connection.url];
		IMAGE_API_KEYS = [...IMAGE_API_KEYS, connection.key];
		IMAGE_API_CONFIGS[IMAGE_API_URLS.length - 1] = connection.config;

		await updateImageConnectionsHandler();
	};

	const saveHandler = async () => {
		loading = true;

		await updateConfig(localStorage.token, config).catch((error) => {
			toast.error($i18n.t(`${error}`));
			loading = false;
			return null;
		});

		dispatch('save');
		loading = false;
	};

	onMount(async () => {
		if ($user?.role === 'admin') {
			const res = await getConfig(localStorage.token).catch((error) => {
				toast.error($i18n.t(`${error}`));
				return null;
			});

			if (res) {
				config = res;
			}

			try {
				const imageConnConfig = await getImageConnectionsConfig(localStorage.token);
				if (imageConnConfig) {
					IMAGE_API_URLS = imageConnConfig.IMAGE_API_URLS || [];
					IMAGE_API_KEYS = imageConnConfig.IMAGE_API_KEYS || [];
					IMAGE_API_CONFIGS = imageConnConfig.IMAGE_API_CONFIGS || {};
				}
			} catch (error) {
				// Image connections may not be configured yet
			}
		}
	});
</script>

<AddImageConnectionModal
	bind:show={showAddImageConnectionModal}
	onSubmit={addImageConnectionHandler}
/>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveHandler();
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden pr-2">
		{#if config}
			<div>
				<div class=" mb-1 text-sm font-medium">{$i18n.t('Image Settings')}</div>

				<div>
					<div class=" py-1 flex w-full justify-between">
						<div class=" self-center text-xs font-medium">
							{$i18n.t('Image Generation')}
						</div>

						<div class="px-1">
							<Switch
								bind:state={config.enabled}
								on:change={() => {
									updateConfigHandler();
								}}
							/>
						</div>
					</div>
				</div>

			</div>
			<hr class=" border-gray-100 dark:border-gray-850" />

			<div>
				<div class="flex justify-between items-center mb-1">
					<div class="text-sm font-medium">{$i18n.t('Image Generation API')}</div>

					<Tooltip content={$i18n.t('Add Image Connection')}>
						<button
							class="px-1"
							on:click={() => {
								showAddImageConnectionModal = true;
							}}
							type="button"
						>
							<Plus />
						</button>
					</Tooltip>
				</div>

				<div class="flex flex-col gap-1.5">
					{#each IMAGE_API_URLS as url, idx}
						<ImageConnection
							bind:url
							bind:key={IMAGE_API_KEYS[idx]}
							bind:config={IMAGE_API_CONFIGS[idx]}
							onSubmit={() => {
								updateImageConnectionsHandler();
							}}
							onDelete={() => {
								IMAGE_API_URLS = IMAGE_API_URLS.filter((_, urlIdx) => idx !== urlIdx);
								IMAGE_API_KEYS = IMAGE_API_KEYS.filter((_, keyIdx) => idx !== keyIdx);

								let newConfig = {};
								IMAGE_API_URLS.forEach((_, newIdx) => {
									newConfig[newIdx] =
										IMAGE_API_CONFIGS[newIdx < idx ? newIdx : newIdx + 1];
								});
								IMAGE_API_CONFIGS = newConfig;
								updateImageConnectionsHandler();
							}}
						/>
					{/each}
				</div>
			</div>
		{/if}

	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
		<Button kind="filled" size="md" type="submit" {loading}>
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
