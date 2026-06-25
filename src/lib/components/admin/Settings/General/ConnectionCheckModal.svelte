<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Info from '$lib/components/icons/Info.svelte';

	import { getOllamaConfig } from '$lib/apis/ollama';
	import { getOpenAIConfig } from '$lib/apis/openai';
	import { getRAGConfig, getEmbeddingConfig, getSearchEngineConfig } from '$lib/apis/retrieval';
	import { getWebhookUrl, getModels } from '$lib/apis';
	import { getAudioConfig } from '$lib/apis/audio';
	import { getImageConnectionsList, getConfig as getImageConfig } from '$lib/apis/images';
	import { getLicenseStatus } from '$lib/apis/license';
	import { getDocumentProfiles } from '$lib/apis/document-profiles';
	import { getExtractionEngines } from '$lib/apis/extraction-engines';
	import { getKMSConfig, getCodeExecutionConfig } from '$lib/apis/configs';
	import { getCodeGatewayConfig } from '$lib/apis/code-gateway';

	import { buildChecks, type CheckRow, type ConfigBundle } from './buildChecks';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let show = false;

	let loading = false;
	let loadError = false;
	let rows: CheckRow[] = [];

	const loadAll = async () => {
		loading = true;
		loadError = false;
		const token = localStorage.token;
		const safe = <T,>(p: Promise<T>): Promise<T | null> =>
			p.then((x) => x as T).catch(() => null);

		const [
			ollama,
			openai,
			embedding,
			rag,
			searchEngine,
			webhookUrl,
			audio,
			imageConfig,
			imageModels,
			license,
			documentProfiles,
			codeExecution,
			codeGateway,
			kms,
			models,
			extractionEngines
		] = await Promise.all([
			safe(getOllamaConfig(token)),
			safe(getOpenAIConfig(token)),
			safe(getEmbeddingConfig(token)),
			safe(getRAGConfig(token)),
			safe(getSearchEngineConfig(token)),
			safe(getWebhookUrl(token)),
			safe(getAudioConfig(token)),
			safe(getImageConfig(token)), // /config → enabled, engine
			safe(getImageConnectionsList(token)), // /images/connections/list → 이미지 모델(연결) 리스트
			safe(getLicenseStatus(token)),
			safe(getDocumentProfiles(token)),
			safe(getCodeExecutionConfig(token)),
			safe(getCodeGatewayConfig(token)),
			safe(getKMSConfig(token)),
			safe(getModels(token, null, true)), // base=true → 모델 페이지의 베이스 연결 모델
			safe(getExtractionEngines(token))
		]);

		const bundle: ConfigBundle = {
			ollama,
			openai,
			models: Array.isArray(models) ? models : null,
			embedding,
			rag,
			searchEngine,
			webhookUrl: typeof webhookUrl === 'string' ? webhookUrl : '',
			audio,
			image: {
				enabled: imageConfig?.enabled,
				engine: imageConfig?.engine,
				models: Array.isArray(imageModels) ? imageModels : []
			},
			extractionEngines: Array.isArray(extractionEngines) ? extractionEngines : null,
			documentProfiles: Array.isArray(documentProfiles) ? documentProfiles : null,
			codeExecution,
			codeGateway,
			kms,
			license
		};

		// 핵심 응답(LLM/임베딩/RAG/검색/음성) 중 절반 이상 null 이면 일반 오류로 간주
		const nullCount = [ollama, openai, embedding, rag, searchEngine, audio].filter(
			(x) => x === null
		).length;
		loadError = nullCount >= 4;

		rows = buildChecks(bundle);
		loading = false;
	};

	$: if (show) {
		loadAll();
	}

	const formatDetail = (detail: string) => {
		// buildChecks 의 한국어 placeholder 를 i18n 으로 치환
		if (detail === '(미설정)') return $i18n.t('Not configured');
		if (detail === '설정됨') return $i18n.t('Configured');
		if (detail === '만료됨') return $i18n.t('Expired');
		return detail;
	};
</script>

<Modal bind:show size="sm">
	<div class="px-5 pt-4 pb-2 flex items-center justify-between">
		<div class="text-base font-medium">{$i18n.t('Settings Status')}</div>
		<button
			type="button"
			class="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
			aria-label={$i18n.t('Close')}
			on:click={() => (show = false)}
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 20 20"
				fill="currentColor"
				class="w-5 h-5"
			>
				<path
					d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
				/>
			</svg>
		</button>
	</div>

	<hr class="border-gray-100 dark:border-gray-850" />

	<div class="px-5 py-3 min-h-[200px] max-h-[60vh] overflow-y-auto">
		{#if loading}
			<div class="flex items-center justify-center py-8">
				<Spinner />
			</div>
		{:else}
			{#if loadError}
				<div class="mb-3 text-xs text-red-500 dark:text-red-400">
					{$i18n.t('Failed to load settings')}
				</div>
			{/if}
			<ul class="divide-y divide-gray-100 dark:divide-gray-850">
				{#each rows as row (row.id)}
					{#if row.isHeader}
						<li
							class="flex items-center pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500"
						>
							<span>{row.label ?? $i18n.t(row.labelKey ?? '')}</span>
							{#if row.infoKey && row.status !== 'ok'}
								<Tooltip
									content={$i18n.t(row.infoKey)}
									placement="top"
									className="ml-auto flex shrink-0"
								>
									<Info
										className="size-4 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
									/>
								</Tooltip>
							{/if}
						</li>
					{:else}
						<li class="flex items-center gap-2 py-2 min-w-0 {row.nested ? 'pl-6' : ''}">
							{#if row.status === 'ok'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 shrink-0 text-emerald-500 dark:text-emerald-400"
								>
									<path
										fill-rule="evenodd"
										d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z"
										clip-rule="evenodd"
									/>
								</svg>
							{:else if row.status === 'ng'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 shrink-0 text-red-500 dark:text-red-400"
								>
									<path
										fill-rule="evenodd"
										d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
										clip-rule="evenodd"
									/>
								</svg>
							{:else}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="w-4 h-4 shrink-0 text-gray-300 dark:text-gray-600"
								>
									<circle cx="10" cy="10" r="3.5" />
								</svg>
							{/if}
							<span class="text-sm font-medium text-gray-800 dark:text-gray-100 shrink-0">
								{row.label ?? $i18n.t(row.labelKey ?? '')}
							</span>
							<span class="text-xs text-gray-500 dark:text-gray-400 truncate">
								{formatDetail(row.detail)}{#if row.isDefault} ({$i18n.t('Default')}){/if}
							</span>
							{#if row.infoKey && row.status !== 'ok'}
								<Tooltip
									content={$i18n.t(row.infoKey)}
									placement="top"
									className="ml-auto flex shrink-0"
								>
									<Info
										className="size-4 text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
									/>
								</Tooltip>
							{/if}
						</li>
					{/if}
				{/each}
			</ul>
		{/if}
	</div>

	<div class="px-5 pb-4 pt-2 flex justify-end">
		<Button kind="filled" size="md" on:click={() => (show = false)}>{$i18n.t('Close')}</Button>
	</div>
</Modal>
