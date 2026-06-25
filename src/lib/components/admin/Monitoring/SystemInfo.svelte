<script lang="ts">
	import { getContext, onMount } from 'svelte';

	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let loading = true;

	// Placeholder data - 실제 시스템 API 연동 시 교체
	let systemInfo = {
		version: '0.6.5',
		python_version: '3.12',
		database: 'PostgreSQL',
		vector_db: 'Azure Search',
		ollama_status: 'Connected',
		openai_status: 'Connected'
	};

	const loadSystemInfo = async () => {
		loading = true;
		// TODO: 실제 시스템 정보 API 연동
		await new Promise((resolve) => setTimeout(resolve, 500));
		loading = false;
	};

	onMount(() => {
		loadSystemInfo();
	});
</script>

<!-- Header -->
<div class="mt-0.5 mb-2 gap-1 flex flex-col md:flex-row justify-between">
	<div class="flex md:self-center text-lg font-medium px-0.5">
		{$i18n.t('System')}
	</div>

	<div class="flex gap-1">
		<button
			class="p-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-900 transition"
			on:click={loadSystemInfo}
		>
			<ArrowPath className="size-5" />
		</button>
	</div>
</div>

<hr class="mb-3 border-gray-50 dark:border-gray-850" />

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else}
	<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
		<!-- Version -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Version')}</div>
			<div class="text-lg font-semibold">v{systemInfo.version}</div>
		</div>

		<!-- Python Version -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Python')}</div>
			<div class="text-lg font-semibold">{systemInfo.python_version}</div>
		</div>

		<!-- Database -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Database')}</div>
			<div class="text-lg font-semibold">{systemInfo.database}</div>
		</div>

		<!-- Vector DB -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Vector Database')}</div>
			<div class="text-lg font-semibold">{systemInfo.vector_db}</div>
		</div>

		<!-- Ollama Status -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('Ollama')}</div>
			<div class="flex items-center gap-2">
				<span
					class="w-2 h-2 rounded-full {systemInfo.ollama_status === 'Connected'
						? 'bg-green-500'
						: 'bg-red-500'}"
				></span>
				<span class="text-lg font-semibold">{systemInfo.ollama_status}</span>
			</div>
		</div>

		<!-- OpenAI Status -->
		<div class="p-4 bg-gray-50 dark:bg-gray-950 rounded-xl">
			<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">{$i18n.t('OpenAI')}</div>
			<div class="flex items-center gap-2">
				<span
					class="w-2 h-2 rounded-full {systemInfo.openai_status === 'Connected'
						? 'bg-green-500'
						: 'bg-red-500'}"
				></span>
				<span class="text-lg font-semibold">{systemInfo.openai_status}</span>
			</div>
		</div>
	</div>

	<!-- Coming Soon Notice -->
	<div class="mt-8 p-6 bg-gray-50 dark:bg-gray-950 rounded-xl text-center">
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="size-12 text-gray-400 dark:text-gray-600 mx-auto mb-4"
		>
			<path
				fill-rule="evenodd"
				d="M11.078 2.25c-.917 0-1.699.663-1.85 1.567L9.05 5H6a2.25 2.25 0 0 0-2.25 2.25v.894c0 .448.133.882.378 1.252l.174.251c.16.232.36.431.586.59l.13.091a.75.75 0 0 1 .242.72l-.457 2.734a2.25 2.25 0 0 0 2.221 2.618h1.351a2.25 2.25 0 0 0 2.187-1.719l.417-1.669a.75.75 0 0 1 .728-.581h.356a.75.75 0 0 1 .728.581l.417 1.669a2.25 2.25 0 0 0 2.187 1.719h1.35a2.25 2.25 0 0 0 2.222-2.618l-.458-2.734a.75.75 0 0 1 .242-.72l.13-.09c.227-.16.427-.359.587-.591l.173-.251c.245-.37.378-.804.378-1.252v-.894A2.25 2.25 0 0 0 18 5h-3.05l-.178-1.183a1.875 1.875 0 0 0-1.85-1.567h-1.844ZM4.5 12.75a.75.75 0 0 1 .75-.75h13.5a.75.75 0 0 1 0 1.5H5.25a.75.75 0 0 1-.75-.75Zm.75 2.25a.75.75 0 0 0 0 1.5h13.5a.75.75 0 0 0 0-1.5H5.25Z"
				clip-rule="evenodd"
			/>
		</svg>
		<p class="text-gray-500 dark:text-gray-400">
			{$i18n.t('More system monitoring features coming soon.')}
		</p>
	</div>
{/if}
