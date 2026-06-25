<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import {
		getSearchEngineConfig,
		updateSearchEngineConfig,
		testPgvectorConnection,
		type SearchEngineConfig
	} from '$lib/apis/retrieval';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SensitiveTextarea from '$lib/components/common/SensitiveTextarea.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let loading = false;
	let config: SearchEngineConfig | null = null;
	let rerankCredentialSource: 'global' | 'custom' = 'global';
	let vertexSearchCredentialSource: 'global' | 'custom' = 'global';

	let testingPgvector = false;
	let pgvectorTestResult: { success: boolean; message: string } | null = null;

	$: engineTypeOptions = [
		{ value: '', label: $i18n.t('Not configured') },
		{ value: 'azure_search', label: $i18n.t('Azure AI Search') },
		{ value: 'pgvector', label: $i18n.t('PostgreSQL pgvector') },
		{ value: 'milvus', label: $i18n.t('Milvus') },
		{ value: 'elasticsearch', label: $i18n.t('Elasticsearch') },
		{ value: 'vertex_search', label: $i18n.t('Google Vertex AI Search') }
	];

	$: rerankerTypeOptions = [
		{ value: '', label: $i18n.t('Not configured') },
		{ value: 'azure_search_builtin', label: $i18n.t('Azure AI Search (Built-in)') },
		{ value: 'vertex', label: $i18n.t('Vertex AI Ranking API') }
	];

	$: rerankerVertexModelOptions = [
		{ value: 'semantic-ranker-default@latest', label: 'semantic-ranker-default@latest' },
		{ value: 'semantic-ranker-fast-004', label: 'semantic-ranker-fast-004' }
	];

	$: credentialSourceOptions = [
		{ value: 'global', label: $i18n.t('Use Global Google Cloud Key') },
		{ value: 'custom', label: $i18n.t('Use Custom Key') }
	];

	const loadConfig = async () => {
		try {
			config = await getSearchEngineConfig(localStorage.token);
			rerankCredentialSource = config?.reranker_vertex_service_account_key ? 'custom' : 'global';
			vertexSearchCredentialSource = config?.vertex_service_account_key ? 'custom' : 'global';
		} catch (err) {
			toast.error($i18n.t(`${err}`));
		}
	};

	const submitHandler = async () => {
		if (!config) return;

		loading = true;
		try {
			await updateSearchEngineConfig(localStorage.token, config);
			dispatch('save');
		} catch (err) {
			toast.error($i18n.t(`${err}`));
		} finally {
			loading = false;
		}
	};

	const testPgvectorHandler = async () => {
		if (!config) return;
		testingPgvector = true;
		pgvectorTestResult = null;
		try {
			const res = await testPgvectorConnection(localStorage.token, {
				pgvector_host: config.pgvector_host,
				pgvector_port: config.pgvector_port,
				pgvector_database: config.pgvector_database,
				pgvector_user: config.pgvector_user,
				pgvector_password: config.pgvector_password
			});
			pgvectorTestResult = { success: res.success, message: res.message };
			if (res.success) {
				toast.success(res.message || $i18n.t('Connection successful!'));
			} else {
				toast.error(res.message || $i18n.t('Connection failed.'));
			}
		} catch (err) {
			const message =
				typeof err === 'string' ? err : ((err as { message?: string })?.message ?? `${err}`);
			pgvectorTestResult = { success: false, message };
			toast.error(message);
		} finally {
			testingPgvector = false;
		}
	};

	// When engine_type changes, auto-set reranker for Azure AI Search
	$: if (config) {
		if (config.engine_type === 'azure_search' && !config.reranker_type) {
			config.reranker_type = 'azure_search_builtin';
		} else if (config.engine_type !== 'azure_search' && config.reranker_type === 'azure_search_builtin') {
			config.reranker_type = '';
		}
	}

	onMount(async () => {
		await loadConfig();
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={submitHandler}
>
	{#if config}
		<div class="space-y-2.5 overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<!-- Search Engine Type -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Search Engine')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="mb-2.5 flex w-full justify-between items-center gap-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Engine Type')}
					</div>
					<div class="min-w-[200px]">
						<Selector
							value={config.engine_type ?? ''}
							items={engineTypeOptions}
							size="sm"
							searchEnabled={false}
							on:change={(e) => {
								if (config) config.engine_type = e.detail.value;
								pgvectorTestResult = null;
							}}
						/>
					</div>
				</div>

				<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Select a search engine for Knowledge Base, Glossary, and DbSphere.')}
					{$i18n.t('Embedding settings can be configured in Settings > Documents.')}
				</div>
			</div>

			<!-- Search Settings -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Search Settings')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="mb-2.5 flex w-full justify-between items-center gap-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Top K')}
					</div>
					<input
						type="number"
						class="w-20 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
						min="1"
						max="100"
						bind:value={config.top_k}
					/>
				</div>

				<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Top K controls the number of search results retrieved from the vector database.')}
				</div>
			</div>

			<!-- Azure AI Search -->
			{#if config.engine_type === 'azure_search'}
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('Azure AI Search')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5">
						<Input
							bind:value={config.azure_endpoint}
							label={$i18n.t('Endpoint')}
							placeholder="https://your-search-service.search.windows.net"
							size="sm"
						/>
					</div>

					<div class="mb-2.5 flex flex-col w-full">
						<div class="mb-1 text-xs font-medium">{$i18n.t('API Key')}</div>
						<SensitiveInput
							placeholder={$i18n.t('Enter API Key')}
							bind:value={config.azure_api_key}
						/>
					</div>

					<div class="mb-2.5">
						<Input
							bind:value={config.azure_api_version}
							label={$i18n.t('API Version')}
							placeholder="2024-07-01"
							size="sm"
						/>
					</div>

					<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
						{$i18n.t('Embedding is performed using the settings in Documents. Auto-vectorizer is not used.')}
					</div>
				</div>
			{/if}

			<!-- PostgreSQL pgvector -->
			{#if config.engine_type === 'pgvector'}
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('PostgreSQL pgvector')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={config.pgvector_host}
								label={$i18n.t('Host')}
								placeholder="localhost"
								size="sm"
							/>
						</div>
						<div class="w-24 flex flex-col">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Port')}</div>
							<input
								type="number"
								class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								placeholder="5432"
								bind:value={config.pgvector_port}
							/>
						</div>
					</div>

					<div class="mb-2.5">
						<Input
							bind:value={config.pgvector_database}
							label={$i18n.t('Database')}
							placeholder="postgres"
							size="sm"
						/>
					</div>

					<div class="mb-2.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={config.pgvector_user}
								label={$i18n.t('User')}
								placeholder="postgres"
								size="sm"
							/>
						</div>
						<div class="flex-1 flex flex-col">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Password')}</div>
							<SensitiveInput
								placeholder={$i18n.t('Enter Password')}
								bind:value={config.pgvector_password}
							/>
						</div>
					</div>

					<div class="mt-3 flex items-center gap-2 flex-wrap">
						<Button
							kind="outlined"
							size="sm"
							loading={testingPgvector}
							on:click={testPgvectorHandler}
						>
							{$i18n.t('Test Connection')}
						</Button>
						{#if pgvectorTestResult}
							<span
								class="text-xs {pgvectorTestResult.success
									? 'text-green-600 dark:text-green-400'
									: 'text-red-600 dark:text-red-400'}"
							>
								{pgvectorTestResult.message}
							</span>
						{/if}
					</div>
				</div>
			{/if}

			<!-- Milvus -->
			{#if config.engine_type === 'milvus'}
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('Milvus')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={config.milvus_host}
								label={$i18n.t('Host')}
								placeholder="localhost"
								size="sm"
							/>
						</div>
						<div class="w-24 flex flex-col">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Port')}</div>
							<input
								type="number"
								class="w-full rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								placeholder="19530"
								bind:value={config.milvus_port}
							/>
						</div>
					</div>

					<div class="mb-2.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={config.milvus_user}
								label={`${$i18n.t('User')} (${$i18n.t('optional')})`}
								size="sm"
							/>
						</div>
						<div class="flex-1 flex flex-col">
							<div class="mb-1 text-xs font-medium">
								{$i18n.t('Password')} ({$i18n.t('optional')})
							</div>
							<SensitiveInput
								placeholder={$i18n.t('Enter Password')}
								bind:value={config.milvus_password}
							/>
						</div>
					</div>
				</div>
			{/if}

			<!-- Elasticsearch -->
			{#if config.engine_type === 'elasticsearch'}
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('Elasticsearch')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5">
						<Input
							bind:value={config.elasticsearch_url}
							label={$i18n.t('URL')}
							placeholder="http://localhost:9200"
							size="sm"
						/>
					</div>

					<div class="mb-2.5 flex flex-col w-full">
						<div class="mb-1 text-xs font-medium">{$i18n.t('API Key')} ({$i18n.t('optional')})</div>
						<SensitiveInput
							placeholder={$i18n.t('Enter API Key')}
							bind:value={config.elasticsearch_api_key}
						/>
					</div>

					<div class="mb-2.5 flex gap-2">
						<div class="flex-1">
							<Input
								bind:value={config.elasticsearch_user}
								label={`${$i18n.t('User')} (${$i18n.t('optional')})`}
								size="sm"
							/>
						</div>
						<div class="flex-1 flex flex-col">
							<div class="mb-1 text-xs font-medium">
								{$i18n.t('Password')} ({$i18n.t('optional')})
							</div>
							<SensitiveInput
								placeholder={$i18n.t('Enter Password')}
								bind:value={config.elasticsearch_password}
							/>
						</div>
					</div>

					<div class="mb-2.5">
						<Input
							bind:value={config.elasticsearch_ca_certs}
							label={`${$i18n.t('CA Certificates Path')} (${$i18n.t('optional')})`}
							placeholder="/path/to/ca.crt"
							size="sm"
						/>
					</div>
				</div>
			{/if}

			<!-- Vertex AI Search -->
			{#if config.engine_type === 'vertex_search'}
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('Google Vertex AI Search')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5">
						<Input
							bind:value={config.vertex_project_id}
							label={$i18n.t('Project ID')}
							placeholder="your-gcp-project-id"
							size="sm"
						/>
					</div>

					<div class="mb-2.5">
						<Input
							bind:value={config.vertex_location}
							label={$i18n.t('Location')}
							placeholder="us-central1"
							size="sm"
						/>
					</div>

					<div class="mb-2.5 flex flex-col w-full">
						<div class="mb-1.5 flex gap-2 items-center">
							<div class="text-xs font-medium shrink-0">{$i18n.t('Authentication')}</div>
							<div class="min-w-[200px]">
								<Selector
									value={vertexSearchCredentialSource}
									items={credentialSourceOptions}
									size="sm"
									searchEnabled={false}
									on:change={(e) => {
										vertexSearchCredentialSource =
											e.detail.value === 'custom' ? 'custom' : 'global';
										if (vertexSearchCredentialSource === 'global' && config) {
											config.vertex_service_account_key = '';
										}
									}}
								/>
							</div>
						</div>
						{#if vertexSearchCredentialSource === 'custom'}
							<SensitiveTextarea
								rows={4}
								placeholder={`{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}`}
								bind:value={config.vertex_service_account_key}
							/>
						{/if}
					</div>

					<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
						{$i18n.t('If not set, uses Global Google Cloud Key or Application Default Credentials (ADC).')}
					</div>
				</div>
			{/if}

			<!-- Reranker (선택사항) -->
			<div class="mb-3">
				<div class="mb-2.5 text-base font-medium">{$i18n.t('Reranker')}</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				<div class="mb-2.5 flex w-full justify-between items-center gap-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Reranker Type')}
					</div>
					<div class="min-w-[220px]">
						<Selector
							value={config.reranker_type ?? ''}
							items={rerankerTypeOptions}
							size="sm"
							searchEnabled={false}
							disabled={config.engine_type === 'azure_search'}
							on:change={(e) => {
								if (config) config.reranker_type = e.detail.value;
							}}
						/>
					</div>
				</div>

				{#if config.reranker_type}
				<div class="mb-2.5 flex w-full justify-between items-center gap-2">
					<div class="self-center text-xs font-medium">
						{$i18n.t('Reranker Top K')}
					</div>
					<input
						type="number"
						class="w-20 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
						min="1"
						max="100"
						bind:value={config.reranker_top_k}
					/>
				</div>

				<div class="mb-2.5">
					<div class="flex justify-between items-center mb-2">
						<div class="text-xs font-medium">{$i18n.t('Reranker Threshold')}</div>
						<span class="text-xs text-gray-500">{(config.reranker_threshold ?? 0).toFixed(2)}</span>
					</div>
					<input
						type="range"
						min="0"
						max="1"
						step="0.01"
						bind:value={config.reranker_threshold}
						class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700"
					/>
					<div class="flex justify-between text-xs text-gray-500 mt-1">
						<span>0</span>
						<span>0.5</span>
						<span>1.0</span>
					</div>
				</div>
			{/if}

			{#if config.reranker_type === 'vertex'}
					<div class="mb-2.5">
						<Input
							bind:value={config.reranker_vertex_project_id}
							label={`${$i18n.t('Project ID')} (${$i18n.t('optional')})`}
							placeholder={$i18n.t('Auto-detected from credentials if empty')}
							size="sm"
						/>
					</div>

					<div class="mb-2.5">
						<Input
							bind:value={config.reranker_vertex_location}
							label={$i18n.t('Location')}
							placeholder="global"
							size="sm"
						/>
					</div>

					<div class="mb-2.5 flex w-full justify-between items-center gap-2">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Reranker Model')}
						</div>
						<div class="min-w-[280px]">
							<Selector
								value={config.reranker_vertex_model ?? ''}
								items={rerankerVertexModelOptions}
								size="sm"
								searchEnabled={false}
								on:change={(e) => {
									if (config) config.reranker_vertex_model = e.detail.value;
								}}
							/>
						</div>
					</div>

					<div class="mb-2.5 flex flex-col w-full">
						<div class="mb-1.5 flex gap-2 items-center">
							<div class="text-xs font-medium shrink-0">{$i18n.t('Authentication')}</div>
							<div class="min-w-[200px]">
								<Selector
									value={rerankCredentialSource}
									items={credentialSourceOptions}
									size="sm"
									searchEnabled={false}
									on:change={(e) => {
										rerankCredentialSource =
											e.detail.value === 'custom' ? 'custom' : 'global';
										if (rerankCredentialSource === 'global' && config) {
											config.reranker_vertex_service_account_key = '';
										}
									}}
								/>
							</div>
						</div>
						{#if rerankCredentialSource === 'custom'}
							<SensitiveTextarea
								rows={4}
								placeholder={`{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}`}
								bind:value={config.reranker_vertex_service_account_key}
							/>
						{/if}
					</div>

					<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
						{$i18n.t('If not set, uses Global Google Cloud Key or Application Default Credentials (ADC).')}
					</div>
				{/if}

				<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Reranker re-scores search results using a semantic model for improved accuracy. Optional.')}
				</div>
			</div>
		</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
		<Button kind="filled" size="md" type="submit" {loading}>
			{$i18n.t('Save')}
		</Button>
	</div>
	{:else}
		<div class="flex items-center justify-center h-full">
			<Spinner />
		</div>
	{/if}
</form>
