<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { config, WEBUI_NAME } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';
	import {
		getBrandingConfig,
		uploadBrandingAsset,
		deleteBrandingAsset,
		updateAppName
	} from '$lib/apis/branding';
	import { brandingVersion } from '$lib/stores/branding';
	import { WEBUI_BASE_URL } from '$lib/constants';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';

	const i18n = getContext('i18n');

	// i18n dynamic key declarations (for i18next-parser detection)
	// prettier-ignore
	void [
		$i18n.t('Logo (Light)'), $i18n.t('Logo (Dark)'),
		$i18n.t('Main logo displayed in sidebar and chat (PNG)'),
		$i18n.t('Dark mode logo (PNG)'),
		$i18n.t('Splash (Light)'), $i18n.t('Splash (Dark)'),
		$i18n.t('Loading screen image (PNG)'),
		$i18n.t('Dark mode loading screen image (PNG)'),
		$i18n.t('App Icon'), $i18n.t('PWA install icon (512x512, PNG)'),
		$i18n.t('Favicon'), $i18n.t('Browser tab icon (ICO, PNG)'),
		$i18n.t('Click or drag and drop to upload'),
		$i18n.t('Others')
	];

	type AssetConfig = {
		is_custom: boolean;
		url: string;
	};

	type AssetItem = {
		type: string;
		labelKey: string;
		descKey: string;
		accept: string;
	};

	let brandingConfig: Record<string, AssetConfig> = {};
	let loading = false;
	let draggingOver: Record<string, boolean> = {};
	let fileInputs: Record<string, HTMLInputElement> = {};

	let appName = '';
	let savingName = false;

	const ASSET_SECTIONS: { titleKey: string; items: AssetItem[][] }[] = [
		{
			titleKey: 'Logo',
			items: [
				[
					{
						type: 'favicon',
						labelKey: 'Logo (Light)',
						descKey: 'Main logo displayed in sidebar and chat (PNG)',
						accept: 'image/*'
					},
					{
						type: 'favicon-dark',
						labelKey: 'Logo (Dark)',
						descKey: 'Dark mode logo (PNG)',
						accept: 'image/*'
					}
				]
			]
		},
		{
			titleKey: 'Splash',
			items: [
				[
					{
						type: 'splash',
						labelKey: 'Splash (Light)',
						descKey: 'Loading screen image (PNG)',
						accept: 'image/*'
					},
					{
						type: 'splash-dark',
						labelKey: 'Splash (Dark)',
						descKey: 'Dark mode loading screen image (PNG)',
						accept: 'image/*'
					}
				]
			]
		},
		{
			titleKey: 'Others',
			items: [
				[
					{
						type: 'logo',
						labelKey: 'App Icon',
						descKey: 'PWA install icon (512x512, PNG)',
						accept: 'image/*'
					},
					{
						type: 'browser-favicon',
						labelKey: 'Favicon',
						descKey: 'Browser tab icon (ICO, PNG)',
						accept: '.ico,.png,image/x-icon,image/vnd.microsoft.icon,image/png'
					}
				]
			]
		}
	];

	const loadConfig = async () => {
		try {
			const result = await getBrandingConfig(localStorage.token);
			appName = result?.app_name ?? '';
			const { app_name: _, ...assets } = result ?? {};
			brandingConfig = assets;
		} catch (e) {
			console.error(e);
		}
	};

	const handleAppNameKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') saveAppName();
	};

	const saveAppName = async () => {
		savingName = true;
		try {
			const res = await updateAppName(localStorage.token, appName);
			WEBUI_NAME.set(res.app_name);
			await config.set(await getBackendConfig());
			toast.success($i18n.t('App name updated successfully'));
		} catch (e) {
			toast.error($i18n.t('Failed to update app name'));
			console.error(e);
		} finally {
			savingName = false;
		}
	};

	const uploadFile = async (assetType: string, file: File) => {
		const isIco = file.name?.toLowerCase().endsWith('.ico');
		if (!file.type.startsWith('image/') && !isIco) {
			toast.error($i18n.t('Failed to upload branding asset'));
			return;
		}

		loading = true;
		try {
			await uploadBrandingAsset(localStorage.token, assetType, file);
			toast.success($i18n.t('Branding updated successfully'));
			await loadConfig();
			await config.set(await getBackendConfig());
			brandingVersion.set(Date.now());
		} catch (e) {
			toast.error($i18n.t('Failed to upload branding asset'));
			console.error(e);
		} finally {
			loading = false;
		}
	};

	const handleClick = (assetType: string) => {
		fileInputs[assetType]?.click();
	};

	const handleFileInput = async (assetType: string, e: Event) => {
		const input = e.target as HTMLInputElement;
		const file = input?.files?.[0];
		if (!file) return;
		await uploadFile(assetType, file);
		input.value = '';
	};

	const handleDragOver = (e: DragEvent, assetType: string) => {
		e.preventDefault();
		if (e.dataTransfer?.types?.includes('Files')) {
			draggingOver[assetType] = true;
		}
	};

	const handleDragLeave = (e: DragEvent, assetType: string) => {
		e.preventDefault();
		const target = e.currentTarget as HTMLElement;
		if (target && !target.contains(e.relatedTarget as Node)) {
			draggingOver[assetType] = false;
		}
	};

	const handleDrop = async (e: DragEvent, assetType: string) => {
		e.preventDefault();
		draggingOver[assetType] = false;

		if (e.dataTransfer?.files?.length) {
			const file = e.dataTransfer.files[0];
			await uploadFile(assetType, file);
		}
	};

	const handleDelete = async (assetType: string) => {
		loading = true;
		try {
			await deleteBrandingAsset(localStorage.token, assetType);
			toast.success($i18n.t('Branding reset to default'));
			await loadConfig();
			await config.set(await getBackendConfig());
			brandingVersion.set(Date.now());
		} catch (e) {
			toast.error($i18n.t('Failed to reset branding'));
			console.error(e);
		} finally {
			loading = false;
		}
	};

	const getPreviewUrl = (assetType: string) => {
		return `${WEBUI_BASE_URL}/api/v1/branding/${assetType}?t=${Date.now()}`;
	};

	onMount(() => {
		loadConfig();
	});
</script>

<div class="flex flex-col h-full text-sm">
	<div class="flex flex-col gap-4 overflow-y-scroll scrollbar-hidden h-full">
		<div class="mt-0.5">
			<div class="mb-2 text-sm font-medium">{$i18n.t('Branding')}</div>
			<div class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('Customize the appearance of your application by uploading custom branding assets.')}
			</div>
		</div>

		<hr class="border-gray-100 dark:border-gray-850" />

		<div>
			<div class="mb-1 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
				{$i18n.t('App Name')}
			</div>
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
				{$i18n.t('The name displayed in the browser tab, sidebar, and throughout the interface.')}
			</div>
			<div class="flex items-center gap-2">
				<div class="flex-1">
					<Input
						bind:value={appName}
						placeholder={$i18n.t('e.g. Cloosphere')}
						size="md"
						on:keydown={handleAppNameKeydown}
					/>
				</div>
				<Button
					kind="filled"
					size="md"
					type="button"
					disabled={savingName}
					loading={savingName}
					on:click={saveAppName}
				>
					{savingName ? $i18n.t('Saving...') : $i18n.t('Save')}
				</Button>
			</div>
		</div>

		{#each ASSET_SECTIONS as section}
			<hr class="border-gray-100 dark:border-gray-850" />

			<div class="mb-1 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
				{$i18n.t(section.titleKey)}
			</div>

			{#each section.items as row}
				<div class="grid grid-cols-1 {row.length > 1 ? 'md:grid-cols-2' : ''} gap-4">
					{#each row as asset}
						<div class="flex flex-col gap-2">
							<div class="flex items-center justify-between">
								<div>
									<div class="text-sm font-medium">{$i18n.t(asset.labelKey)}</div>
									<div class="text-xs text-gray-500 dark:text-gray-400">
										{$i18n.t(asset.descKey)}
									</div>
								</div>
								{#if brandingConfig[asset.type]?.is_custom}
									<Button
										kind="outlined"
										size="sm"
										status="error"
										type="button"
										disabled={loading}
										on:click={() => handleDelete(asset.type)}
									>
										{$i18n.t('Reset')}
									</Button>
								{/if}
							</div>

							<input
								bind:this={fileInputs[asset.type]}
								type="file"
								accept={asset.accept}
								hidden
								on:change={(e) => handleFileInput(asset.type, e)}
							/>

							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<button
								type="button"
								class="relative group flex flex-col items-center justify-center rounded-lg border-2 border-dashed transition-all cursor-pointer
									{draggingOver[asset.type]
									? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
									: 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 hover:border-gray-300 dark:hover:border-gray-700'}"
								style="min-height: 120px;"
								disabled={loading}
								on:click={() => handleClick(asset.type)}
								on:dragover|preventDefault={(e) => handleDragOver(e, asset.type)}
								on:dragleave|preventDefault={(e) => handleDragLeave(e, asset.type)}
								on:drop|preventDefault={(e) => handleDrop(e, asset.type)}
							>
								{#key brandingConfig[asset.type]}
									<img
										src={getPreviewUrl(asset.type)}
										alt={$i18n.t(asset.labelKey)}
										class="max-h-16 max-w-48 object-contain pointer-events-none"
									/>
								{/key}

								<div
									class="absolute inset-0 flex flex-col items-center justify-center rounded-lg bg-white/80 dark:bg-gray-900/80 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="1.5"
										stroke="currentColor"
										class="size-6 text-gray-500 dark:text-gray-400"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
										/>
									</svg>
									<span class="mt-1 text-xs text-gray-500 dark:text-gray-400">
										{$i18n.t('Click or drag and drop to upload')}
									</span>
								</div>

								{#if draggingOver[asset.type]}
									<div
										class="absolute inset-0 flex flex-col items-center justify-center rounded-lg bg-blue-50/90 dark:bg-blue-900/40 pointer-events-none"
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="size-6 text-blue-500"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5"
											/>
										</svg>
										<span class="mt-1 text-xs text-blue-500 font-medium">
											{$i18n.t('Drop here')}
										</span>
									</div>
								{/if}
							</button>

							<div class="flex items-center">
								{#if brandingConfig[asset.type]?.is_custom}
									<Badge status="success" size="sm">{$i18n.t('Custom')}</Badge>
								{:else}
									<Badge status="secondary" size="sm">{$i18n.t('Default')}</Badge>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/each}
		{/each}
	</div>
</div>
