<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { models, user } from '$lib/stores';
	import {
		getLocales,
		getLocaleTranslations,
		updateSingleTranslation,
		syncTranslations,
		type LocaleInfo
	} from '$lib/apis/devtools';
	import { getModels } from '$lib/apis';

	import Input from '$lib/components/common/Input.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';

	type I18nStore = Readable<{ t: (key: string, options?: Record<string, unknown>) => string }>;

	const i18n = getContext<I18nStore>('i18n');

	let loading = true;
	let saving = false;
	let syncing = false;
	let locales: LocaleInfo[] = [];
	let selectedLocale = 'en-US';
	let compareLocale = '';
	let translations: Record<string, string> = {};
	let compareTranslations: Record<string, string> = {};
	let searchQuery = '';
	let filterMode: 'all' | 'missing' | 'empty' = 'all';

	// 새 키 추가
	let showAddKey = false;
	let newKey = '';
	let newValue = '';

	// 편집 중인 키
	let editingKey: string | null = null;
	let editingValue = '';

	// 동기화 관련
	let showSyncPanel = false;
	let selectedModel = '';
	let sourceLocales: string[] = ['en-US']; // 최대 3개까지 선택 가능
	let selectedTargetLocales: string[] = [];
	let syncResults: Record<string, { translated: number; failed: number; errors: string[] }> = {};
	let allModels: Array<{ id: string; name: string }> = [];

	$: filteredKeys = Object.keys(translations)
		.filter((key) => {
			if (searchQuery) {
				const query = searchQuery.toLowerCase();
				return (
					key.toLowerCase().includes(query) ||
					translations[key]?.toLowerCase().includes(query)
				);
			}
			return true;
		})
		.filter((key) => {
			if (filterMode === 'missing' && compareLocale) {
				return !compareTranslations[key];
			}
			if (filterMode === 'empty') {
				return !translations[key] || translations[key].trim() === '';
			}
			return true;
		})
		.sort();

	onMount(async () => {
		await loadLocales();
		await loadModels();
	});

	async function loadModels() {
		try {
			// 베이스 모델(일반 모델) 가져오기 - base=true로 호출
			const response = await getModels(localStorage.token, null, true);
			const baseModels = response?.data || response || [];
			allModels = baseModels.map((m: any) => ({
				id: m.id,
				name: m.name || m.id
			}));

			if (allModels.length > 0 && !selectedModel) {
				selectedModel = allModels[0].id;
			}
		} catch (error) {
			console.error('Failed to load models:', error);
		}
	}

	async function loadLocales() {
		try {
			locales = await getLocales(localStorage.token);
			await loadTranslations();
		} catch (error) {
			toast.error($i18n.t('Failed to load locales'));
		} finally {
			loading = false;
		}
	}

	async function loadTranslations() {
		if (!selectedLocale) return;

		loading = true;
		try {
			const data = await getLocaleTranslations(localStorage.token, selectedLocale);
			translations = data.translations;

			if (compareLocale) {
				const compareData = await getLocaleTranslations(localStorage.token, compareLocale);
				compareTranslations = compareData.translations;
			} else {
				compareTranslations = {};
			}
		} catch (error) {
			toast.error($i18n.t('Failed to load translations'));
		} finally {
			loading = false;
		}
	}

	// Selector items
	$: localeItems = locales.map((l) => ({ value: l.code, label: `${l.title} (${l.code})` }));
	$: compareItems = [
		{ value: '', label: `-- ${$i18n.t('None')} --` },
		...locales
			.filter((l) => l.code !== selectedLocale)
			.map((l) => ({ value: l.code, label: `${l.title} (${l.code})` }))
	];
	$: modelItems = allModels.map((m) => ({ value: m.id, label: m.name }));
	$: filterModeItems = [
		{ value: 'all', label: $i18n.t('All') },
		{ value: 'empty', label: $i18n.t('Empty values') },
		...(compareLocale ? [{ value: 'missing', label: $i18n.t('Missing in compare') }] : [])
	];

	const handleSelectedLocaleChange = async (value: string) => {
		selectedLocale = value;
		await loadTranslations();
	};

	const handleCompareLocaleChange = async (value: string) => {
		compareLocale = value;
		await handleCompareChange();
	};

	const handleFilterModeChange = (value: string) => {
		filterMode = value as 'all' | 'missing' | 'empty';
	};

	async function handleLocaleChange() {
		await loadTranslations();
	}

	async function handleCompareChange() {
		if (compareLocale) {
			try {
				const data = await getLocaleTranslations(localStorage.token, compareLocale);
				compareTranslations = data.translations;
			} catch (error) {
				toast.error($i18n.t('Failed to load compare translations'));
			}
		} else {
			compareTranslations = {};
		}
	}

	function startEdit(key: string) {
		editingKey = key;
		editingValue = translations[key] || '';
	}

	function handleEditKeydown(e: CustomEvent<KeyboardEvent>) {
		if (e.detail.key === 'Enter') saveEdit();
		if (e.detail.key === 'Escape') cancelEdit();
	}

	function cancelEdit() {
		editingKey = null;
		editingValue = '';
	}

	async function saveEdit() {
		if (!editingKey) return;

		saving = true;
		try {
			await updateSingleTranslation(
				localStorage.token,
				selectedLocale,
				editingKey,
				editingValue
			);
			translations[editingKey] = editingValue;
			translations = { ...translations };
			toast.success($i18n.t('Translation updated'));
			cancelEdit();
		} catch (error) {
			toast.error($i18n.t('Failed to update translation'));
		} finally {
			saving = false;
		}
	}

	async function addNewKey() {
		if (!newKey.trim()) {
			toast.error($i18n.t('Key cannot be empty'));
			return;
		}

		if (translations[newKey] !== undefined) {
			toast.error($i18n.t('Key already exists'));
			return;
		}

		saving = true;
		try {
			await updateSingleTranslation(localStorage.token, selectedLocale, newKey, newValue);
			translations[newKey] = newValue;
			translations = { ...translations };
			toast.success($i18n.t('Translation added'));
			newKey = '';
			newValue = '';
			showAddKey = false;
		} catch (error) {
			toast.error($i18n.t('Failed to add translation'));
		} finally {
			saving = false;
		}
	}

	async function copyFromCompare(key: string) {
		if (!compareTranslations[key]) return;

		saving = true;
		try {
			await updateSingleTranslation(
				localStorage.token,
				selectedLocale,
				key,
				compareTranslations[key]
			);
			translations[key] = compareTranslations[key];
			translations = { ...translations };
			toast.success($i18n.t('Translation copied'));
		} catch (error) {
			toast.error($i18n.t('Failed to copy translation'));
		} finally {
			saving = false;
		}
	}

	function exportTranslations() {
		const blob = new Blob([JSON.stringify(translations, null, '\t')], {
			type: 'application/json'
		});
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${selectedLocale}-translation.json`;
		a.click();
		URL.revokeObjectURL(url);
	}

	function toggleSourceLocale(code: string) {
		if (sourceLocales.includes(code)) {
			// 최소 1개는 유지
			if (sourceLocales.length > 1) {
				sourceLocales = sourceLocales.filter((c) => c !== code);
			}
		} else {
			// 최대 3개까지
			if (sourceLocales.length < 3) {
				sourceLocales = [...sourceLocales, code];
			} else {
				toast.warning($i18n.t('Maximum 3 source locales allowed'));
			}
		}
	}

	function toggleAllTargetLocales() {
		const availableTargets = locales.filter((l) => !sourceLocales.includes(l.code));
		if (selectedTargetLocales.length === availableTargets.length) {
			selectedTargetLocales = [];
		} else {
			selectedTargetLocales = availableTargets.map((l) => l.code);
		}
	}

	function toggleTargetLocale(code: string) {
		if (selectedTargetLocales.includes(code)) {
			selectedTargetLocales = selectedTargetLocales.filter((c) => c !== code);
		} else {
			selectedTargetLocales = [...selectedTargetLocales, code];
		}
	}

	async function handleSync() {
		if (!selectedModel) {
			toast.error($i18n.t('Please select a model'));
			return;
		}

		if (selectedTargetLocales.length === 0) {
			toast.error($i18n.t('Please select at least one target locale'));
			return;
		}

		syncing = true;
		syncResults = {};

		try {
			const response = await syncTranslations(
				localStorage.token,
				selectedModel,
				sourceLocales,
				selectedTargetLocales
			);

			syncResults = response.results;

			// 결과 요약
			let totalTranslated = 0;
			let totalFailed = 0;
			Object.values(syncResults).forEach((result) => {
				totalTranslated += result.translated;
				totalFailed += result.failed;
			});

			if (totalTranslated > 0) {
				toast.success(
					$i18n.t('Translated {{count}} keys successfully', { count: totalTranslated })
				);
			}
			if (totalFailed > 0) {
				toast.warning($i18n.t('Failed to translate {{count}} keys', { count: totalFailed }));
			}

			// 현재 선택된 로케일이 타겟에 포함되어 있으면 새로고침
			if (selectedTargetLocales.includes(selectedLocale)) {
				await loadTranslations();
			}
		} catch (error) {
			toast.error($i18n.t('Failed to sync translations'));
			console.error(error);
		} finally {
			syncing = false;
		}
	}
</script>

<div class="flex flex-col h-full">
	<!-- Header -->
	<div class="flex flex-col gap-4 mb-4">
		<div class="flex items-center justify-between gap-2 flex-wrap">
			<div class="flex items-center gap-4 flex-wrap">
				<div class="flex items-center gap-2">
					<span class="text-sm font-medium">{$i18n.t('Locale')}:</span>
					<div class="min-w-[12rem]">
						<Selector
							value={selectedLocale}
							items={localeItems}
							size="sm"
							on:change={(e) => handleSelectedLocaleChange(e.detail.value)}
						/>
					</div>
				</div>

				<div class="flex items-center gap-2">
					<span class="text-sm font-medium">{$i18n.t('Compare with')}:</span>
					<div class="min-w-[12rem]">
						<Selector
							value={compareLocale}
							items={compareItems}
							size="sm"
							on:change={(e) => handleCompareLocaleChange(e.detail.value)}
						/>
					</div>
				</div>
			</div>

			<div class="flex items-center gap-1.5">
				<Button kind="outlined" size="sm" type="button" on:click={() => (showSyncPanel = !showSyncPanel)}>
					{$i18n.t('Sync')}
				</Button>
				<Button kind="outlined" size="sm" type="button" on:click={exportTranslations}>
					<svelte:fragment slot="prefix">
						<ArrowDownTray className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Export JSON')}
				</Button>
				<Button kind="filled" size="sm" type="button" on:click={() => (showAddKey = true)}>
					<svelte:fragment slot="prefix">
						<Plus className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Add Key')}
				</Button>
			</div>
		</div>

		<!-- Sync Panel -->
		{#if showSyncPanel}
			<div class="p-4 rounded-lg bg-gray-50 dark:bg-gray-800/50 border dark:border-gray-700">
				<div class="flex flex-col gap-3">
					<div class="flex items-center justify-between">
						<h3 class="text-sm font-medium">{$i18n.t('Auto Translate Empty Values')}</h3>
						<Button kind="text" size="sm" type="button" on:click={() => (showSyncPanel = false)}>
							<svelte:fragment slot="prefix">
								<XMark className="size-4" />
							</svelte:fragment>
						</Button>
					</div>

					<div class="flex items-center gap-2">
						<span class="text-xs text-gray-500">{$i18n.t('Model')}:</span>
						<div class="min-w-[16rem]">
							<Selector
								value={selectedModel}
								items={modelItems}
								size="sm"
								on:change={(e) => {
									selectedModel = e.detail.value;
								}}
							/>
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-500">
								{$i18n.t('Source Locales')} ({sourceLocales.length}/3):
							</span>
							<span class="text-xs text-gray-400">
								{$i18n.t('Select up to 3 reference locales')}
							</span>
						</div>
						<div class="flex flex-wrap gap-2">
							{#each locales as locale}
								<button
									class="px-2 py-1 text-xs rounded transition {sourceLocales.includes(locale.code)
										? 'bg-gray-900 dark:bg-white text-white dark:text-black'
										: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'}"
									on:click={() => toggleSourceLocale(locale.code)}
								>
									{locale.code}
								</button>
							{/each}
						</div>
					</div>

					<div class="flex flex-col gap-2">
						<div class="flex items-center justify-between">
							<span class="text-xs text-gray-500">{$i18n.t('Target Locales')}:</span>
							<Button kind="text" size="sm" type="button" on:click={toggleAllTargetLocales}>
								{selectedTargetLocales.length ===
								locales.filter((l) => !sourceLocales.includes(l.code)).length
									? $i18n.t('Deselect All')
									: $i18n.t('Select All')}
							</Button>
						</div>
						<div class="flex flex-wrap gap-2 max-h-32 overflow-y-auto">
							{#each locales.filter((l) => !sourceLocales.includes(l.code)) as locale}
								<button
									class="px-2 py-1 text-xs rounded transition {selectedTargetLocales.includes(
										locale.code
									)
										? 'bg-gray-900 dark:bg-white text-white dark:text-black'
										: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'}"
									on:click={() => toggleTargetLocale(locale.code)}
								>
									{locale.code}
								</button>
							{/each}
						</div>
					</div>

					<div class="flex items-center justify-between pt-2">
						<span class="text-xs text-gray-500">
							{selectedTargetLocales.length} {$i18n.t('locales selected')}
						</span>
						<Button
							kind="filled"
							size="sm"
							type="button"
							loading={syncing}
							disabled={syncing || selectedTargetLocales.length === 0}
							on:click={handleSync}
						>
							{syncing ? $i18n.t('Syncing...') : $i18n.t('Start Sync')}
						</Button>
					</div>

					<!-- Sync Results -->
					{#if Object.keys(syncResults).length > 0}
						<div class="mt-2 pt-2 border-t dark:border-gray-700">
							<h4 class="text-xs font-medium mb-2">{$i18n.t('Results')}:</h4>
							<div class="flex flex-wrap gap-2 text-xs">
								{#each Object.entries(syncResults) as [locale, result]}
									<div
										class="px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 {result.failed > 0
											? 'border border-yellow-500'
											: ''}"
									>
										<span class="font-medium">{locale}:</span>
										<span class="text-green-600 dark:text-green-400">{result.translated}</span>
										{#if result.failed > 0}
											/ <span class="text-red-500">{result.failed}</span>
										{/if}
									</div>
								{/each}
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}
	</div>

	<!-- Filters -->
	<div class="flex items-center gap-4 mb-4">
		<div class="flex-1 max-w-md">
			<Input
				bind:value={searchQuery}
				placeholder={$i18n.t('Search keys or values...')}
				size="md"
				type="text"
				ariaLabel={$i18n.t('Search keys or values')}
			>
				<svelte:fragment slot="prefix">
					<MagnifyingGlass className="size-4 text-gray-400" />
				</svelte:fragment>
			</Input>
		</div>

		<div class="flex items-center gap-2">
			<span class="text-sm text-gray-500">{$i18n.t('Filter')}:</span>
			<div class="min-w-[10rem]">
				<Selector
					value={filterMode}
					items={filterModeItems}
					size="sm"
					on:change={(e) => handleFilterModeChange(e.detail.value)}
				/>
			</div>
		</div>

		<span class="text-sm text-gray-500">
			{filteredKeys.length} / {Object.keys(translations).length} {$i18n.t('keys')}
		</span>
	</div>

	<!-- Add Key Modal -->
	{#if showAddKey}
		<div class="mb-4 p-4 rounded-lg bg-gray-100 dark:bg-gray-800">
			<div class="flex flex-col gap-2">
				<Input
					bind:value={newKey}
					placeholder={$i18n.t('Translation key')}
					size="md"
					type="text"
					ariaLabel={$i18n.t('Translation key')}
				/>
				<Input
					bind:value={newValue}
					placeholder={$i18n.t('Translation value')}
					size="md"
					type="text"
					ariaLabel={$i18n.t('Translation value')}
				/>
				<div class="flex justify-end gap-2">
					<Button
						kind="outlined"
						size="sm"
						type="button"
						on:click={() => {
							showAddKey = false;
							newKey = '';
							newValue = '';
						}}
					>
						{$i18n.t('Cancel')}
					</Button>
					<Button
						kind="filled"
						size="sm"
						type="button"
						loading={saving}
						disabled={saving}
						on:click={addNewKey}
					>
						{saving ? $i18n.t('Saving...') : $i18n.t('Add')}
					</Button>
				</div>
			</div>
		</div>
	{/if}

	<!-- Translation List -->
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<Spinner className="size-6" />
		</div>
	{:else}
		<div class="flex-1 overflow-y-auto">
			<table class="w-full text-sm">
				<thead class="sticky top-0 bg-white dark:bg-gray-900">
					<tr class="border-b dark:border-gray-700">
						<th class="text-left py-2 px-3 font-medium w-1/3">{$i18n.t('Key')}</th>
						<th class="text-left py-2 px-3 font-medium">
							{selectedLocale}
						</th>
						{#if compareLocale}
							<th class="text-left py-2 px-3 font-medium text-gray-500">
								{compareLocale}
							</th>
						{/if}
						<th class="w-24"></th>
					</tr>
				</thead>
				<tbody>
					{#each filteredKeys as key (key)}
						<tr class="border-b dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/50">
							<td class="py-2 px-3 font-mono text-xs text-gray-600 dark:text-gray-400 break-all">
								{key}
							</td>
							<td class="py-2 px-3">
								{#if editingKey === key}
									<div class="flex items-center gap-2">
										<div class="flex-1">
											<Input
												bind:value={editingValue}
												size="sm"
												type="text"
												ariaLabel={$i18n.t('Edit translation')}
												on:keydown={handleEditKeydown}
											/>
										</div>
										<Button
											kind="filled"
											size="sm"
											type="button"
											loading={saving}
											disabled={saving}
											on:click={saveEdit}
										>
											{$i18n.t('Save')}
										</Button>
										<Button kind="outlined" size="sm" type="button" on:click={cancelEdit}>
											{$i18n.t('Cancel')}
										</Button>
									</div>
								{:else}
									<span
										class="cursor-pointer hover:text-gray-900 dark:hover:text-white {!translations[key]
											? 'text-gray-400 italic'
											: ''}"
										on:click={() => startEdit(key)}
									>
										{translations[key] || $i18n.t('(empty)')}
									</span>
								{/if}
							</td>
							{#if compareLocale}
								<td class="py-2 px-3 text-gray-500">
									{#if compareTranslations[key]}
										<span class="text-xs">{compareTranslations[key]}</span>
									{:else}
										<span class="text-gray-400 italic text-xs">{$i18n.t('(not found)')}</span>
									{/if}
								</td>
							{/if}
							<td class="py-2 px-3">
								<div class="flex items-center gap-1">
									{#if compareLocale && compareTranslations[key] && !translations[key]}
										<Tooltip content={$i18n.t('Copy from compare')}>
											<Button
												kind="text"
												size="sm"
												type="button"
												on:click={() => copyFromCompare(key)}
											>
												{$i18n.t('Copy')}
											</Button>
										</Tooltip>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			{#if filteredKeys.length === 0}
				<div class="text-center py-12 text-gray-500">
					{$i18n.t('No translations found')}
				</div>
			{/if}
		</div>
	{/if}
</div>
