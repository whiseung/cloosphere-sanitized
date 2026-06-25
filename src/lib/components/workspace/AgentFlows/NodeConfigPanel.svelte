<script lang="ts">
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { getModels as getAgentModels, getModelById } from '$lib/apis/models';
	import { getModels as getAvailableModels } from '$lib/apis';
	import { getGuardrails } from '$lib/apis/guardrails';
	import { getGlossaries } from '$lib/apis/glossary';
	import { getAgentFlowList } from '$lib/apis/agent-flows';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let node: any = null;
	export let upstreamNodes: any[] = [];
	export let stateKeys: Array<{ key: string; source: string; nodeId: string; type: string }> = [];
	export let token: string = '';
	export let currentFlowId: string | null = null;  // Exclude from subflow selection

	// Resources for dropdowns
	let agents: any[] = [];      // Models with base_model_id (user-defined agents)
	let baseModels: any[] = [];  // Models without base_model_id (LLM providers)
	let guardrails: any[] = [];
	let glossaries: any[] = [];
	let flows: any[] = [];       // Available flows for subflow selection
	let loading = false;

	// Upstream agent outputs (for variable reference)
	let upstreamAgentOutputs: Array<{
		nodeId: string;
		nodeLabel: string;
		agentId: string;
		agentName: string;
		outputType: 'text' | 'json_schema';
		fields: Array<{ name: string; type: string; path: string }>;
	}> = [];

	// Local state for editing
	let label = '';
	let resourceId = '';
	let config: Record<string, any> = {};
	let currentNodeId: string | null = null;

	// Variables for Start node
	let variables: Array<{ name: string; type: string; defaultValue: string }> = [];

	// Routes for Router node
	let routes: Array<{
		id: string;
		label: string;
		branch_key: string;
		condition?: { type: string; field?: string; value?: string };
	}> = [];

	// Load resources on mount
	onMount(async () => {
		await loadResources();
	});

	async function loadResources() {
		loading = true;
		try {
			const [agentModelsRes, baseModelsRes, guardrailsRes, glossariesRes, flowsRes] = await Promise.all([
				getAgentModels(token),
				getAvailableModels(token, null, true),  // base: true for LLM models only
				getGuardrails(token),
				getGlossaries(token),
				getAgentFlowList(token)
			]);
			// User-defined agents (have base_model_id)
			agents = (agentModelsRes || []).filter((m: any) => m.base_model_id);
			// Base LLM models from providers (Ollama, OpenAI, etc.) - excludes agents
			baseModels = baseModelsRes || [];
			guardrails = guardrailsRes || [];
			glossaries = glossariesRes || [];
			flows = flowsRes || [];
		} catch (e) {
			console.error('Failed to load resources:', e);
		} finally {
			loading = false;
		}
	}

	// Load upstream agent outputs when upstreamNodes change
	$: if (upstreamNodes && token) {
		loadUpstreamAgentOutputs();
	}

	async function loadUpstreamAgentOutputs() {
		const outputs: typeof upstreamAgentOutputs = [];

		for (const upNode of upstreamNodes) {
			// Handle Agent nodes
			if (upNode.type === 'agent' && upNode.data?.resourceId) {
				try {
					const agent = await getModelById(token, upNode.data.resourceId);
					if (agent) {
						const outputInfo: (typeof upstreamAgentOutputs)[0] = {
							nodeId: upNode.id,
							nodeLabel: upNode.data?.label || 'Agent',
							agentId: agent.id,
							agentName: agent.name,
							outputType:
								agent.meta?.responseFormat?.type === 'json_schema' ? 'json_schema' : 'text',
							fields: []
						};

						if (
							agent.meta?.responseFormat?.type === 'json_schema' &&
							agent.meta?.responseFormat?.json_schema?.schema
						) {
							const schema = agent.meta.responseFormat.json_schema.schema;
							outputInfo.fields = extractSchemaFields(schema, '');
						}

						outputInfo.fields.unshift({
							name: 'response',
							type: outputInfo.outputType === 'json_schema' ? 'object' : 'string',
							path: 'response'
						});

						outputs.push(outputInfo);
					}
				} catch (e) {
					console.error('Failed to load agent:', e);
				}
			}
			// Handle Model nodes
			else if (upNode.type === 'model') {
				const modelConfig = upNode.data?.config || {};
				const modelId = modelConfig.modelId;
				const modelName = baseModels.find((m: any) => m.id === modelId)?.name || modelId || 'Model';

				const outputInfo: (typeof upstreamAgentOutputs)[0] = {
					nodeId: upNode.id,
					nodeLabel: upNode.data?.label || 'Model',
					agentId: modelId || '',
					agentName: modelName,
					outputType: modelConfig.responseFormat === 'json' ? 'json_schema' : 'text',
					fields: []
				};

				// Add fields from jsonFields config if JSON format
				if (modelConfig.responseFormat === 'json' && modelConfig.jsonFields?.length > 0) {
					for (const field of modelConfig.jsonFields) {
						outputInfo.fields.push({
							name: field.name,
							type: field.type,
							path: field.name
						});
					}
				}

				outputInfo.fields.unshift({
					name: 'response',
					type: modelConfig.responseFormat === 'json' ? 'object' : 'string',
					path: 'response'
				});

				outputs.push(outputInfo);
			}
			// Handle Guardrail nodes (Block output provides block info)
			else if (upNode.type === 'guardrail') {
				const guardrailId = upNode.data?.resourceId;
				const guardrailName = guardrails.find((g: any) => g.id === guardrailId)?.name || 'Guardrail';

				const outputInfo: (typeof upstreamAgentOutputs)[0] = {
					nodeId: upNode.id,
					nodeLabel: upNode.data?.label || 'Guardrail',
					agentId: guardrailId || '',
					agentName: guardrailName,
					outputType: 'json_schema',
					fields: [
						{ name: 'guardrail_type', type: 'string', path: 'guardrail_type' },
						{ name: 'guardrail_reason', type: 'string', path: 'guardrail_reason' }
					]
				};

				outputs.push(outputInfo);
			}
			// Handle Transform nodes
			else if (upNode.type === 'transform') {
				const transformConfig = upNode.data?.config || {};
				const outputKey = transformConfig.outputKey || 'transformed';
				const transformType = transformConfig.transformType || 'extract';

				const outputInfo: (typeof upstreamAgentOutputs)[0] = {
					nodeId: upNode.id,
					nodeLabel: upNode.data?.label || 'Transform',
					agentId: '',
					agentName: $i18n.t(transformType === 'extract' ? 'Extract Field' : 'Format Text'),
					outputType: 'text',
					fields: [
						{ name: outputKey, type: 'string', path: outputKey }
					]
				};

				outputs.push(outputInfo);
			}
		}

		upstreamAgentOutputs = outputs;
	}

	function extractSchemaFields(
		schema: any,
		prefix: string
	): Array<{ name: string; type: string; path: string }> {
		const fields: Array<{ name: string; type: string; path: string }> = [];

		if (schema?.properties) {
			for (const [key, value] of Object.entries(schema.properties) as [string, any][]) {
				const path = prefix ? `${prefix}.${key}` : key;
				const fieldType = value.type || 'string';

				fields.push({ name: key, type: fieldType, path });

				if (fieldType === 'object' && value.properties) {
					fields.push(...extractSchemaFields(value, path));
				}
			}
		}

		return fields;
	}

	// Update local state only when node ID changes
	$: if (node?.id !== currentNodeId) {
		currentNodeId = node?.id || null;
		if (node) {
			label = node.data?.label || '';
			resourceId = node.data?.resourceId || '';
			config = { ...(node.data?.config || {}) };
			variables = config.variables || [];
			const defaultRoutes = [
				{
					id: 'route1',
					label: 'Route 1',
					branch_key: 'route1',
					condition: { type: 'contains', value: '' }
				},
				{
					id: 'route2',
					label: 'Route 2',
					branch_key: 'route2',
					condition: { type: 'contains', value: '' }
				}
			];
			routes = (config.routes || defaultRoutes).map((r: any) => ({
				...r,
				condition: r.condition || { type: 'contains', value: '' }
			}));
		}
	}

	function handleUpdate() {
		if (!node) return;
		dispatch('update', {
			nodeId: node.id,
			data: { label, resourceId, config }
		});
	}

	function handleDelete() {
		if (!node) return;
		dispatch('delete', { nodeId: node.id });
	}

	// Node type checkers
	const isNodeType = (type: string | undefined, ...types: string[]) => types.includes(type || '');

	// Variables management
	function addVariable() {
		variables = [...variables, { name: '', type: 'string', defaultValue: '' }];
		config.variables = variables;
		handleUpdate();
	}

	function removeVariable(index: number) {
		variables = variables.filter((_, i) => i !== index);
		config.variables = variables;
		handleUpdate();
	}

	function updateVariable() {
		config.variables = variables;
		handleUpdate();
	}

	// Routes management
	function addRoute() {
		const newIndex = routes.length + 1;
		routes = [
			...routes,
			{
				id: `route${newIndex}`,
				label: `Route ${newIndex}`,
				branch_key: `route${newIndex}`,
				condition: { type: 'contains', value: '' }
			}
		];
		config.routes = routes;
		handleUpdate();
	}

	function removeRoute(index: number) {
		if (routes.length <= 2) return;
		routes = routes.filter((_, i) => i !== index);
		config.routes = routes;
		handleUpdate();
	}

	function updateRoute() {
		config.routes = routes;
		handleUpdate();
	}

	function generateBranchKey(label: string): string {
		return label
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '_')
			.replace(/^_|_$/g, '');
	}

	// Common input classes - compact size for better fit
	const inputClass =
		'w-full px-2 py-1.5 text-xs rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600';
	const selectClass = inputClass;
	const labelClass = 'block text-xs font-medium mb-1 text-gray-700 dark:text-gray-300';
</script>

<div class="h-full flex flex-col overflow-hidden">
	{#if !node}
		<!-- Empty State -->
		<div
			class="flex flex-col items-center justify-center h-full text-center px-4 text-gray-500 dark:text-gray-400"
		>
			<svg
				class="size-12 mb-3 opacity-50"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122"
				/>
			</svg>
			<p class="text-sm">{$i18n.t('Select a node to configure')}</p>
		</div>
	{:else}
		<!-- Header -->
		<div
			class="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-850"
		>
			<div>
				<h3 class="text-sm font-semibold text-gray-900 dark:text-white">
					{$i18n.t('Node Configuration')}
				</h3>
				<p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5 capitalize">
					{node.type?.replace('flow', '') || node.type}
				</p>
			</div>
			<Tooltip content={$i18n.t('Delete Node')}>
				<button
					class="p-1.5 rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
					on:click={handleDelete}
				>
					<svg class="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
						/>
					</svg>
				</button>
			</Tooltip>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto p-4 space-y-4">
			<!-- Label -->
			<div>
				<label for="node-label" class={labelClass}>{$i18n.t('Label')}</label>
				<input
					id="node-label"
					type="text"
					bind:value={label}
					on:change={handleUpdate}
					class={inputClass}
					placeholder={$i18n.t('Enter label')}
				/>
			</div>

			<!-- Start Node - Variables -->
			{#if isNodeType(node.type, 'flowInput')}
				<div>
					<div class="flex items-center justify-between mb-2">
						<span class={labelClass}>{$i18n.t('Variables')}</span>
						<button
							type="button"
							on:click={addVariable}
							class="px-2 py-1 text-xs rounded-lg font-medium transition bg-gray-100 hover:bg-gray-200 text-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700 dark:text-gray-300"
						>
							+ {$i18n.t('Add')}
						</button>
					</div>

					{#if variables.length === 0}
						<p class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Define variables that can be used throughout the flow')}
						</p>
					{:else}
						<div class="space-y-2 max-h-48 overflow-y-auto">
							{#each variables as variable, index}
								<div class="p-2 bg-gray-50 dark:bg-gray-850 rounded-lg border border-gray-100 dark:border-gray-800">
									<div class="flex items-start gap-2">
										<div class="flex-1 space-y-1 min-w-0">
											<div class="flex items-center gap-1">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 w-8">{$i18n.t('Name')}</span>
												<input
													type="text"
													bind:value={variable.name}
													on:change={updateVariable}
													class="flex-1 px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
													placeholder={$i18n.t('Variable name')}
												/>
											</div>
											<div class="flex items-center gap-1">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 w-8">{$i18n.t('Type')}</span>
												<select
													bind:value={variable.type}
													on:change={updateVariable}
													class="flex-1 px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
												>
													<option value="string">String</option>
													<option value="number">Number</option>
													<option value="boolean">Boolean</option>
													<option value="array">Array</option>
													<option value="object">Object</option>
												</select>
											</div>
											<div class="flex items-center gap-1">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 w-8">{$i18n.t('Default')}</span>
												<input
													type="text"
													bind:value={variable.defaultValue}
													on:change={updateVariable}
													class="flex-1 px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
													placeholder={$i18n.t('Default value')}
												/>
											</div>
										</div>
										<button
											type="button"
											on:click={() => removeVariable(index)}
											class="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg flex-shrink-0"
										>
											<svg class="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M6 18L18 6M6 6l12 12"
												/>
											</svg>
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- Available State Keys (auto-collected from other nodes) -->
				{#if stateKeys.length > 0}
					<div class="mt-4">
						<div class="flex items-center gap-2 mb-2">
							<span class={labelClass}>{$i18n.t('Available State Keys')}</span>
							<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400">
								{$i18n.t('Auto')}
							</span>
						</div>
						<p class="text-[10px] text-gray-500 dark:text-gray-400 mb-2">
							{$i18n.t('State keys generated by nodes in this flow')}
						</p>
						<div class="space-y-1 max-h-40 overflow-y-auto">
							{#each stateKeys as sk}
								<div class="flex items-center justify-between p-1.5 bg-gray-50 dark:bg-gray-850 rounded border border-gray-100 dark:border-gray-800">
									<div class="flex items-center gap-2 min-w-0">
										<code class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-mono">
											{'{' + sk.key + '}'}
										</code>
										<span class="text-[10px] text-gray-400 dark:text-gray-500 truncate">
											{sk.source}
										</span>
									</div>
									<span class="text-[9px] px-1 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400 flex-shrink-0">
										{sk.type}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			{/if}

			<!-- Agent Selection -->
			{#if isNodeType(node.type, 'agent')}
				<div>
					<label for="agent-select" class={labelClass}>{$i18n.t('Agent')}</label>
					{#if loading}
						<p class="text-xs text-gray-500">{$i18n.t('Loading')}...</p>
					{:else}
						<select
							id="agent-select"
							bind:value={resourceId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select Agent')}</option>
							{#each agents as agent}
								<option value={agent.id}>{agent.name}</option>
							{/each}
						</select>
						<p class="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
							{$i18n.t('Agent settings (tools, knowledge, etc.) are inherited from agent configuration')}
						</p>
					{/if}
				</div>

				<!-- User Prompt for Agent -->
				<div>
					<label class={labelClass}>{$i18n.t('User Prompt')}</label>
					<textarea
						bind:value={config.userPrompt}
						on:change={handleUpdate}
						rows="3"
						class="{inputClass} resize-none"
						placeholder="{$i18n.t('Use {input} for flow input or {state_key} for State values')}"
					></textarea>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
						{$i18n.t('Example')}: <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{input}'}</code>, <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{transformed}'}</code>
					</p>
					<!-- State Keys for Agent User Prompt -->
					{#if stateKeys.length > 0}
						<div class="mt-1.5 flex flex-wrap gap-1">
							{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
								<button
									type="button"
									class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-mono hover:bg-blue-100 dark:hover:bg-blue-900/40 transition"
									on:click={() => {
										config.userPrompt = (config.userPrompt || '') + '{' + sk.key + '}';
										handleUpdate();
									}}
									title="{sk.source} ({sk.type})"
								>
									{'{' + sk.key + '}'}
								</button>
							{/each}
						</div>
					{/if}
				</div>
			{/if}

			<!-- Model Node Configuration -->
			{#if isNodeType(node.type, 'model')}
				<div>
					<label class={labelClass}>{$i18n.t('Model')}</label>
					{#if loading}
						<p class="text-xs text-gray-500">{$i18n.t('Loading')}...</p>
					{:else}
						<select
							bind:value={config.modelId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select model')}</option>
							{#each baseModels as model}
								<option value={model.id}>{model.name}</option>
							{/each}
						</select>
					{/if}
				</div>

				<div>
					<label class={labelClass}>{$i18n.t('System Prompt')}</label>
					<textarea
						bind:value={config.systemPrompt}
						on:change={handleUpdate}
						rows="3"
						class="{inputClass} resize-none"
						placeholder={$i18n.t('Enter system prompt for this model...')}
					></textarea>
				</div>

				<!-- User Prompt -->
				<div>
					<label class={labelClass}>{$i18n.t('User Prompt')}</label>
					<textarea
						bind:value={config.userPrompt}
						on:change={handleUpdate}
						rows="3"
						class="{inputClass} resize-none"
						placeholder="{$i18n.t('Use {input} for flow input or {state_key} for State values')}"
					></textarea>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
						{$i18n.t('Example')}: <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{input}'}</code>, <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{transformed}'}</code>
					</p>
					<!-- State Keys for Model User Prompt -->
					{#if stateKeys.length > 0}
						<div class="mt-1.5 flex flex-wrap gap-1">
							{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
								<button
									type="button"
									class="text-[10px] px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 font-mono hover:bg-purple-100 dark:hover:bg-purple-900/40 transition"
									on:click={() => {
										config.userPrompt = (config.userPrompt || '') + '{' + sk.key + '}';
										handleUpdate();
									}}
									title="{sk.source} ({sk.type})"
								>
									{'{' + sk.key + '}'}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				<!-- JSON Output Fields (always shown for structured output) -->
				<div>
					<div class="flex items-center justify-between mb-1.5">
						<label class={labelClass}>{$i18n.t('Output Fields')}</label>
						<button
							type="button"
							class="px-2 py-1 text-xs rounded-lg font-medium transition bg-purple-100 hover:bg-purple-200 text-purple-700 dark:bg-purple-900/30 dark:hover:bg-purple-900/50 dark:text-purple-300"
							on:click={() => {
								if (!config.jsonFields) config.jsonFields = [];
								config.jsonFields = [...config.jsonFields, { name: '', type: 'string', description: '' }];
								config.responseFormat = 'json';
								handleUpdate();
							}}
						>
							+ {$i18n.t('Add Field')}
						</button>
					</div>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mb-2">
						{$i18n.t('Define structured output fields for downstream nodes to use')}
					</p>

					{#if config.jsonFields?.length > 0}
						<div class="space-y-1.5">
							{#each config.jsonFields as field, i}
								<div class="p-1.5 bg-gray-50 dark:bg-gray-800/50 rounded border border-gray-100 dark:border-gray-800">
									<div class="flex items-center gap-1">
										<input
											type="text"
											bind:value={field.name}
											on:change={handleUpdate}
											class="flex-1 min-w-0 px-1.5 py-0.5 text-[10px] rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
											placeholder={$i18n.t('Field name')}
										/>
										<select
											bind:value={field.type}
											on:change={handleUpdate}
											class="w-16 px-1 py-0.5 text-[10px] rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white"
										>
											<option value="string">str</option>
											<option value="number">num</option>
											<option value="boolean">bool</option>
											<option value="array">arr</option>
											<option value="object">obj</option>
										</select>
										<button
											type="button"
											class="p-0.5 text-gray-400 hover:text-red-500"
											on:click={() => {
												config.jsonFields = config.jsonFields.filter((_, idx) => idx !== i);
												if (config.jsonFields.length === 0) {
													config.responseFormat = 'text';
												}
												handleUpdate();
											}}
										>
											<svg class="size-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
											</svg>
										</button>
									</div>
									<input
										type="text"
										bind:value={field.description}
										on:change={handleUpdate}
										class="w-full mt-1 px-1.5 py-0.5 text-[10px] rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 {!field.description ? 'border-amber-300 dark:border-amber-700' : ''}"
										placeholder={$i18n.t('Description for LLM (e.g., category of the input)')}
									/>
								</div>
							{/each}
						</div>
					{:else}
						<div class="text-[10px] text-gray-400 dark:text-gray-500 p-2 bg-gray-50 dark:bg-gray-800/50 rounded border border-dashed border-gray-200 dark:border-gray-700">
							<p class="mb-1">{$i18n.t('No fields defined - will output plain text response.')}</p>
							<p>{$i18n.t('Add fields to extract structured data (e.g., category, sentiment, summary).')}</p>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Glossary Configuration -->
			{#if isNodeType(node.type, 'glossary')}
				<div>
					<label class={labelClass}>{$i18n.t('Glossary')}</label>
					{#if loading}
						<p class="text-xs text-gray-500">{$i18n.t('Loading')}...</p>
					{:else}
						<select
							bind:value={resourceId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select Glossary')}</option>
							{#each glossaries as g}
								<option value={g.id}>{g.name}</option>
							{/each}
						</select>
						<p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1">
							{$i18n.t('Select a glossary to look up terms in the input text')}
						</p>
					{/if}
				</div>
			{/if}

			<!-- Merge Configuration -->
			{#if isNodeType(node.type, 'merge')}
				<div>
					<label class={labelClass}>{$i18n.t('Merge Type')}</label>
					<select
						bind:value={config.mergeType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="concat">{$i18n.t('Concat')} - {$i18n.t('Join texts with separator')}</option>
						<option value="json">{$i18n.t('JSON')} - {$i18n.t('Merge as JSON object')}</option>
						<option value="template">{$i18n.t('Template')} - {$i18n.t('Custom Jinja2 template')}</option>
					</select>
				</div>

				{#if config.mergeType === 'concat'}
					<div>
						<label class={labelClass}>{$i18n.t('Separator')}</label>
						<input
							type="text"
							bind:value={config.separator}
							on:change={handleUpdate}
							class={inputClass}
							placeholder="\n\n"
						/>
					</div>
				{/if}

				{#if config.mergeType === 'template'}
					<div>
						<label class={labelClass}>{$i18n.t('Template')}</label>
						<textarea
							bind:value={config.template}
							on:change={handleUpdate}
							rows="4"
							class="{inputClass} resize-none font-mono"
							placeholder={'{{ NodeA_response }}\n{{ NodeB_response }}'}
						></textarea>
						{#if stateKeys.length > 0}
							<div class="flex flex-wrap gap-1 mt-1.5">
								{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
									<button
										type="button"
										class="text-[10px] px-1.5 py-0.5 rounded bg-teal-50 dark:bg-teal-900/20 text-teal-600 dark:text-teal-400 hover:bg-teal-100 dark:hover:bg-teal-900/40"
										on:click={() => { config.template = (config.template || '') + `{{ ${sk.key.replace('.','_').replace(' ','_')} }}`; handleUpdate(); }}
									>
										{sk.key}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{/if}
			{/if}

			<!-- Condition Configuration -->
			{#if isNodeType(node.type, 'condition')}
				<div>
					<label class={labelClass}>{$i18n.t('State Key')}</label>
					<select
						bind:value={config.sourceField}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="">{$i18n.t('Select state key')}</option>
						<option value="input">{$i18n.t('input (User message)')}</option>
						{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
							<option value={sk.key}>{sk.key} ({sk.source})</option>
						{/each}
					</select>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
						{$i18n.t('State key to evaluate for condition')}
					</p>
				</div>

				<div>
					<label for="condition-type" class={labelClass}>{$i18n.t('Condition Type')}</label>
					<select
						id="condition-type"
						bind:value={config.conditionType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="contains">{$i18n.t('Contains')}</option>
						<option value="not_contains">{$i18n.t('Does not contain')}</option>
						<option value="equals">{$i18n.t('Equals')}</option>
						<option value="not_equals">{$i18n.t('Not equals')}</option>
						<option value="starts_with">{$i18n.t('Starts with')}</option>
						<option value="ends_with">{$i18n.t('Ends with')}</option>
						<option value="greater_than">{$i18n.t('Greater than')}</option>
						<option value="less_than">{$i18n.t('Less than')}</option>
						<option value="is_empty">{$i18n.t('Is empty')}</option>
						<option value="is_not_empty">{$i18n.t('Is not empty')}</option>
						<option value="regex">{$i18n.t('Regex match')}</option>
					</select>
				</div>

				{#if !['is_empty', 'is_not_empty'].includes(config.conditionType)}
					<div>
						<label for="condition-value" class={labelClass}>{$i18n.t('Value')}</label>
						<input
							id="condition-value"
							type="text"
							bind:value={config.value}
							on:change={handleUpdate}
							class={inputClass}
							placeholder={$i18n.t('Enter value to compare')}
						/>
					</div>
				{/if}
			{/if}

			<!-- Router Configuration -->
			{#if isNodeType(node.type, 'router')}
				<!-- Routing Type -->
				<div>
					<label class={labelClass}>{$i18n.t('Routing Type')}</label>
					<select
						bind:value={config.routingType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="rule">{$i18n.t('Rule-based')} - {$i18n.t('Match conditions in order')}</option>
						<option value="llm">{$i18n.t('LLM-based')} - {$i18n.t('Let AI choose the route')}</option>
					</select>
				</div>

				{#if config.routingType === 'llm'}
					<!-- LLM Model Selection -->
					<div>
						<label class={labelClass}>{$i18n.t('Model')}</label>
						<select
							bind:value={config.modelId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Default')}</option>
							{#each baseModels as model}
								<option value={model.id}>{model.name}</option>
							{/each}
						</select>
					</div>
				{/if}

				<!-- State Key Selection -->
				<div>
					<label class={labelClass}>{$i18n.t('State Key')}</label>
					<select
						bind:value={config.sourceField}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="">{$i18n.t('Select state key')}</option>
						<option value="input">{$i18n.t('input (User message)')}</option>
						{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
							<option value={sk.key}>{sk.key} ({sk.source})</option>
						{/each}
					</select>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
						{$i18n.t('Select the state key to evaluate for routing')}
					</p>
				</div>

				<!-- Routes -->
				<div>
					<div class="flex items-center justify-between mb-2">
						<span class="text-sm font-medium text-gray-700 dark:text-gray-300">{$i18n.t('Routes')}</span>
						<button
							type="button"
							on:click={addRoute}
							class="px-2 py-1 text-xs rounded-lg font-medium transition bg-violet-100 hover:bg-violet-200 text-violet-700 dark:bg-violet-900/30 dark:hover:bg-violet-900/50 dark:text-violet-300"
						>
							+ {$i18n.t('Add Route')}
						</button>
					</div>

					<div class="space-y-2 max-h-60 overflow-y-auto">
						{#each routes as route, index}
							<div class="p-2.5 bg-gray-50 dark:bg-gray-850 rounded-lg border border-gray-100 dark:border-gray-800">
								<div class="flex items-start gap-2">
									<div class="flex-1 space-y-2 min-w-0">
										<!-- Route Label & Key -->
										<div class="space-y-1">
											<div class="flex items-center gap-1">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 w-10">{$i18n.t('Label')}</span>
												<input
													type="text"
													bind:value={route.label}
													on:change={() => {
														if (route.label && !route.branch_key) {
															route.branch_key = generateBranchKey(route.label);
														}
														updateRoute();
													}}
													class="flex-1 px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
													placeholder={$i18n.t('Route name')}
												/>
											</div>
											<div class="flex items-center gap-1">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 w-10">Key</span>
												<input
													type="text"
													bind:value={route.branch_key}
													on:change={updateRoute}
													class="flex-1 px-2 py-1 text-xs font-mono rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
													placeholder="branch_key"
												/>
											</div>
										</div>

										<!-- Route Condition -->
										{#if route.condition}
											<div class="pt-1 border-t border-gray-200 dark:border-gray-700">
												<span class="text-[10px] text-gray-500 dark:text-gray-400 block mb-1">{$i18n.t('Condition')}</span>
												<div class="space-y-1">
													<select
														bind:value={route.condition.type}
														on:change={updateRoute}
														class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
													>
														<option value="contains">{$i18n.t('Contains')}</option>
														<option value="not_contains">{$i18n.t('Does not contain')}</option>
														<option value="equals">{$i18n.t('Equals')}</option>
														<option value="not_equals">{$i18n.t('Not equals')}</option>
														<option value="starts_with">{$i18n.t('Starts with')}</option>
														<option value="ends_with">{$i18n.t('Ends with')}</option>
														<option value="greater_than">{$i18n.t('Greater than')}</option>
														<option value="less_than">{$i18n.t('Less than')}</option>
														<option value="is_empty">{$i18n.t('Is empty')}</option>
														<option value="is_not_empty">{$i18n.t('Is not empty')}</option>
														<option value="regex">{$i18n.t('Regex match')}</option>
													</select>
													{#if !['is_empty', 'is_not_empty'].includes(route.condition.type)}
														<input
															type="text"
															bind:value={route.condition.value}
															on:change={updateRoute}
															class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
															placeholder={$i18n.t('Value')}
														/>
													{/if}
												</div>
											</div>
										{/if}
									</div>

									<!-- Delete Button -->
									{#if routes.length > 2}
										<button
											type="button"
											on:click={() => removeRoute(index)}
											class="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg flex-shrink-0"
										>
											<svg class="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													stroke-width="2"
													d="M6 18L18 6M6 6l12 12"
												/>
											</svg>
										</button>
									{/if}
								</div>
							</div>
						{/each}
					</div>
				</div>

				<!-- Default Route -->
				<div>
					<label for="default-route" class={labelClass}>{$i18n.t('Default Route')}</label>
					<select
						id="default-route"
						bind:value={config.defaultRoute}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="">{$i18n.t('None (error if no match)')}</option>
						{#each routes as route}
							<option value={route.id}>{route.label}</option>
						{/each}
					</select>
					<p class="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
						{$i18n.t('Route to use when no condition matches')}
					</p>
				</div>
			{/if}

			<!-- Aggregator Configuration -->
			{#if isNodeType(node.type, 'aggregator')}
				<!-- How to combine -->
				<div>
					<label class={labelClass}>{$i18n.t('How to Combine')}</label>
					<select
						bind:value={config.aggregationType}
						on:change={handleUpdate}
						class="w-full px-2 py-1.5 text-xs rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
					>
						<option value="collect">{$i18n.t('Collect all as list')}</option>
						<option value="merge">{$i18n.t('Merge into one object')}</option>
						<option value="concat">{$i18n.t('Join as text')}</option>
						<option value="sum">{$i18n.t('Add numbers')}</option>
						<option value="first">{$i18n.t('Use first only')}</option>
						<option value="last">{$i18n.t('Use last only')}</option>
						<option value="custom">{$i18n.t('Custom')}</option>
					</select>
				</div>

				<!-- Timeout setting -->
				<div>
					<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Timeout (seconds)')}</label>
					<input
						type="number"
						min="0"
						max="3600"
						bind:value={config.timeout}
						on:change={handleUpdate}
						class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
						placeholder="0"
					/>
					<p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1">
						{$i18n.t('Inputs are determined by connected edges')}
					</p>
				</div>

				<!-- When to proceed -->
				<div>
					<label class={labelClass}>{$i18n.t('When to Proceed')}</label>
					<select
						bind:value={config.waitStrategy}
						on:change={handleUpdate}
						class="w-full px-2 py-1.5 text-xs rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
					>
						<option value="all">{$i18n.t('After all complete')}</option>
						<option value="any">{$i18n.t('After any one completes')}</option>
						<option value="count">{$i18n.t('After N complete')}</option>
					</select>
					{#if config.waitStrategy === 'count'}
						<input
							type="number"
							min="1"
							max="10"
							bind:value={config.minInputs}
							on:change={handleUpdate}
							class="w-full mt-1 px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
							placeholder={$i18n.t('Minimum count')}
						/>
					{/if}
				</div>

				<!-- Advanced Settings (collapsible) -->
				<details class="group">
					<summary class="flex items-center gap-1 cursor-pointer text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300">
						<svg class="size-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						</svg>
						{$i18n.t('Advanced Settings')}
					</summary>
					<div class="mt-2 space-y-2 pl-4 border-l-2 border-gray-100 dark:border-gray-800">
						<div>
							<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Output Name')}</label>
							<input
								type="text"
								bind:value={config.stateKey}
								on:change={handleUpdate}
								class="w-full px-2 py-1 text-xs font-mono rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
								placeholder="results"
							/>
						</div>
						<div>
							<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Merge Mode')}</label>
							<select
								bind:value={config.reducer}
								on:change={handleUpdate}
								class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
							>
								<option value="add">{$i18n.t('Append to list')}</option>
								<option value="merge">{$i18n.t('Merge objects')}</option>
								<option value="replace">{$i18n.t('Keep latest')}</option>
							</select>
						</div>
					</div>
				</details>

				{#if config.aggregationType === 'custom'}
					<div>
						<label class={labelClass}>{$i18n.t('Custom Template')}</label>
						<textarea
							bind:value={config.template}
							on:change={handleUpdate}
							rows="3"
							class="w-full px-2 py-1.5 text-xs font-mono rounded-lg bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600 resize-none"
							placeholder={`{{ inputs | map(attribute='value') | list | tojson }}`}
						></textarea>
						<p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1">
							{$i18n.t('Use')} <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">inputs</code> {$i18n.t('to access all values')}
						</p>
					</div>
				{/if}
			{/if}

			<!-- HumanInput Configuration -->
			{#if isNodeType(node.type, 'humanInput')}
				<div>
					<label class={labelClass}>{$i18n.t('Input Type')}</label>
					<select
						bind:value={config.inputType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="approval">{$i18n.t('Approval (Yes/No)')}</option>
						<option value="text">{$i18n.t('Text Input')}</option>
						<option value="choice">{$i18n.t('Multiple Choice')}</option>
					</select>
				</div>

				<div>
					<label class={labelClass}>{$i18n.t('Prompt Message')}</label>
					<textarea
						bind:value={config.prompt}
						on:change={handleUpdate}
						rows="2"
						class="{inputClass} resize-none"
						placeholder={$i18n.t('Message to show the user...')}
					></textarea>
				</div>

				{#if config.inputType === 'choice'}
					<div>
						<div class="flex items-center justify-between mb-2">
							<span class={labelClass}>{$i18n.t('Choices')}</span>
							<button
								type="button"
								on:click={() => {
									config.choices = [...(config.choices || []), { label: '', value: '' }];
									handleUpdate();
								}}
								class="px-2 py-1 text-xs rounded-lg font-medium transition bg-teal-100 hover:bg-teal-200 text-teal-700 dark:bg-teal-900/30 dark:hover:bg-teal-900/50 dark:text-teal-300"
							>
								+ {$i18n.t('Add')}
							</button>
						</div>
						<div class="space-y-2 max-h-40 overflow-y-auto">
							{#each config.choices || [] as choice, index}
								<div class="flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-850 rounded-lg">
									<div class="flex-1 space-y-1 min-w-0">
										<input
											type="text"
											bind:value={choice.label}
											on:change={handleUpdate}
											class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
											placeholder={$i18n.t('Display label')}
										/>
										<input
											type="text"
											bind:value={choice.value}
											on:change={handleUpdate}
											class="w-full px-2 py-1 text-xs font-mono rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
											placeholder={$i18n.t('value')}
										/>
									</div>
									<button
										type="button"
										on:click={() => {
											config.choices = config.choices.filter((_, i) => i !== index);
											handleUpdate();
										}}
										class="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg flex-shrink-0"
									>
										<svg class="size-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
										</svg>
									</button>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Advanced settings -->
				<details class="group">
					<summary class="flex items-center gap-1 cursor-pointer text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300">
						<svg class="size-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						</svg>
						{$i18n.t('Advanced Settings')}
					</summary>
					<div class="mt-2 space-y-2 pl-4 border-l-2 border-gray-100 dark:border-gray-800">
						<div class="grid grid-cols-2 gap-2">
							<div>
								<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Timeout')}</label>
								<input
									type="number"
									min="0"
									max="86400"
									bind:value={config.timeout}
									on:change={handleUpdate}
									class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
									placeholder="0"
								/>
							</div>
							<div>
								<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Required')}</label>
								<select
									bind:value={config.required}
									on:change={handleUpdate}
									class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
								>
									<option value={true}>{$i18n.t('Yes')}</option>
									<option value={false}>{$i18n.t('No')}</option>
								</select>
							</div>
						</div>
						<div>
							<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Output Name')}</label>
							<input
								type="text"
								bind:value={config.stateKey}
								on:change={handleUpdate}
								class="w-full px-2 py-1 text-xs font-mono rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
								placeholder="user_response"
							/>
						</div>
						<div>
							<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Default Value')}</label>
							<input
								type="text"
								bind:value={config.defaultValue}
								on:change={handleUpdate}
								class="w-full px-2 py-1 text-xs rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
								placeholder={$i18n.t('Value if timeout')}
							/>
						</div>
					</div>
				</details>
			{/if}

			<!-- Transform Configuration -->
			{#if isNodeType(node.type, 'transform')}
				<!-- Transform Type Selection -->
				<div>
					<label class={labelClass}>{$i18n.t('Transform Type')}</label>
					<select
						bind:value={config.transformType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="extract">{$i18n.t('Extract Field')} - {$i18n.t('Get specific data from input')}</option>
						<option value="format">{$i18n.t('Format Text')} - {$i18n.t('Create text from template')}</option>
					</select>
				</div>

				<!-- Extract: State key to extract -->
				{#if config.transformType === 'extract'}
					<div>
						<label class={labelClass}>{$i18n.t('State Key')}</label>
						<select
							bind:value={config.sourceField}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select state key')}</option>
							<option value="input">{$i18n.t('input (User message)')}</option>
							{#each stateKeys.filter(sk => sk.nodeId !== node.id) as sk}
								<option value={sk.key}>{sk.key} ({sk.source})</option>
							{/each}
						</select>
						<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('State key to extract and pass through')}
						</p>
					</div>
				{/if}

				<!-- Format: Template with State key placeholders -->
				{#if config.transformType === 'format'}
					<div>
						<label class={labelClass}>{$i18n.t('Output Template')}</label>
						<textarea
							bind:value={config.formatTemplate}
							on:change={handleUpdate}
							rows="3"
							class="{inputClass} resize-none"
							placeholder={$i18n.t('Error: {guardrail_type} - {guardrail_reason}')}
						></textarea>
						<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('Use {state_key} to insert State values')}
						</p>
					</div>
				{/if}

				<!-- Output Key -->
				<div>
					<label class={labelClass}>{$i18n.t('Output Key')}</label>
					<input
						type="text"
						bind:value={config.outputKey}
						on:change={handleUpdate}
						class={inputClass}
						placeholder="transformed"
					/>
					<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
						{$i18n.t('State key for output')}
					</p>
				</div>

				<!-- Advanced Settings (Jinja2 for power users) -->
				<details class="group">
					<summary class="flex items-center gap-1 cursor-pointer text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300">
						<svg class="size-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						</svg>
						{$i18n.t('Advanced Settings')}
					</summary>
					<div class="mt-2 space-y-2 pl-4 border-l-2 border-gray-100 dark:border-gray-800">
					<div class="flex items-center gap-2 text-xs">
						<Checkbox
							state={config.useAdvanced ? 'checked' : 'unchecked'}
							on:change={(e) => {
								config.useAdvanced = e.detail === 'checked';
								handleUpdate();
							}}
						/>
						<span class="text-gray-700 dark:text-gray-300">{$i18n.t('Use Jinja2 Template')}</span>
					</div>

						{#if config.useAdvanced}
							<div>
								<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Jinja2 Template')}</label>
								<textarea
									bind:value={config.template}
									on:change={handleUpdate}
									rows="4"
									class="{inputClass} font-mono text-[10px] resize-none"
									placeholder="{'{{ state.guardrail_type }} - {{ state.guardrail_reason }}'}"
								></textarea>
								<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
									{$i18n.t('Access State with')} <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{{ state.key }}'}</code>
								</p>
							</div>
						{/if}
					</div>
				</details>
			{/if}

			<!-- Notification Configuration -->
			{#if isNodeType(node.type, 'notification')}
				<div>
					<label for="notification-type" class={labelClass}>{$i18n.t('Notification Type')}</label>
					<select
						id="notification-type"
						bind:value={config.type}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="email">{$i18n.t('Email')}</option>
						<option value="slack">{$i18n.t('Slack')}</option>
						<option value="teams">{$i18n.t('Microsoft Teams')}</option>
						<option value="discord">{$i18n.t('Discord')}</option>
					</select>
				</div>

				{#if config.type === 'email'}
					<div>
						<label for="notification-to" class={labelClass}>{$i18n.t('To')}</label>
						<input
							id="notification-to"
							type="text"
							bind:value={config.to}
							on:change={handleUpdate}
							class={inputClass}
							placeholder="email@example.com"
						/>
					</div>
					<div>
						<label for="notification-subject" class={labelClass}>{$i18n.t('Subject')}</label>
						<input
							id="notification-subject"
							type="text"
							bind:value={config.subject}
							on:change={handleUpdate}
							class={inputClass}
							placeholder={$i18n.t('Email subject')}
						/>
					</div>
				{/if}

				<div>
					<label for="notification-message" class={labelClass}>{$i18n.t('Message Template')}</label>
					<textarea
						id="notification-message"
						bind:value={config.messageTemplate}
						on:change={handleUpdate}
						rows="3"
						class="{inputClass} resize-none"
						placeholder="{'{{ input }}'}"
					></textarea>
					<p class="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
						{$i18n.t('Use Jinja2 syntax for dynamic content')}
					</p>
				</div>
			{/if}

			<!-- Guardrail Configuration -->
			{#if isNodeType(node.type, 'guardrail')}
				<div>
					<label for="guardrail-select" class={labelClass}>{$i18n.t('Guardrail')}</label>
					{#if loading}
						<p class="text-xs text-gray-500">{$i18n.t('Loading')}...</p>
					{:else if guardrails.length === 0}
						<div
							class="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg p-3"
						>
							{$i18n.t('No guardrails available. Create one in Workspace > Guardrails.')}
						</div>
					{:else}
						<select
							id="guardrail-select"
							bind:value={resourceId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select Guardrail')}</option>
							{#each guardrails as guardrail}
								<option value={guardrail.id}>{guardrail.name}</option>
							{/each}
						</select>
						{#if resourceId}
							{@const selected = guardrails.find((g) => g.id === resourceId)}
							{#if selected?.description}
								<p class="text-xs text-gray-500 dark:text-gray-400 mt-1.5">
									{selected.description}
								</p>
							{/if}
						{/if}
					{/if}
				</div>

				<!-- Block Action -->
				<div>
					<label class={labelClass}>{$i18n.t('Block Action')}</label>
					<select
						bind:value={config.onBlocked}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="stop">{$i18n.t('Stop')} - {$i18n.t('End flow immediately')}</option>
						<option value="message">{$i18n.t('Message')} - {$i18n.t('Show message and stop')}</option>
						<option value="continue">{$i18n.t('Continue')} - {$i18n.t('Continue to Block output')}</option>
					</select>
				</div>

				<!-- Custom message (when onBlocked is 'message') -->
				{#if config.onBlocked === 'message'}
					<div>
						<label class={labelClass}>{$i18n.t('Blocked Message')}</label>
						<textarea
							bind:value={config.blockedMessage}
							on:change={handleUpdate}
							rows="2"
							class="{inputClass} resize-none"
							placeholder={$i18n.t('Message to show when blocked...')}
						></textarea>
					</div>
				{/if}

				<!-- Output info based on mode -->
				<div class="text-xs bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2.5">
					<div class="flex items-center gap-2 mb-2">
						<div class="flex items-center gap-1 text-green-600 dark:text-green-400">
							<div class="w-2 h-2 rounded-full bg-green-500"></div>
							<span class="font-medium">{$i18n.t('Pass')}</span>
						</div>
						<span class="text-gray-400 text-[10px]">→ {$i18n.t('Continue flow')}</span>
					</div>

					{#if config.onBlocked === 'continue'}
						<div class="flex items-center gap-2 mb-2">
							<div class="flex items-center gap-1 text-red-600 dark:text-red-400">
								<div class="w-2 h-2 rounded-full bg-red-500"></div>
								<span class="font-medium">{$i18n.t('Block')}</span>
							</div>
							<span class="text-gray-400 text-[10px]">→ {$i18n.t('Continue with block info')}</span>
						</div>
						<p class="text-[10px] text-gray-500 dark:text-gray-400 mb-1.5">{$i18n.t('Block output fields')}:</p>
						<div class="space-y-0.5 text-[10px] text-gray-600 dark:text-gray-400">
							<div><code class="bg-gray-200 dark:bg-gray-700 px-1 rounded">guardrail_type</code> - {$i18n.t('Block type')}</div>
							<div><code class="bg-gray-200 dark:bg-gray-700 px-1 rounded">guardrail_reason</code> - {$i18n.t('Block reason')}</div>
						</div>
					{:else if config.onBlocked === 'message'}
						<div class="flex items-center gap-2">
							<div class="flex items-center gap-1 text-red-600 dark:text-red-400">
								<div class="w-2 h-2 rounded-full bg-red-500"></div>
								<span class="font-medium">{$i18n.t('Block')}</span>
							</div>
							<span class="text-gray-400 text-[10px]">→ {$i18n.t('Show message and stop')}</span>
						</div>
					{:else}
						<div class="flex items-center gap-2">
							<div class="flex items-center gap-1 text-red-600 dark:text-red-400">
								<div class="w-2 h-2 rounded-full bg-red-500"></div>
								<span class="font-medium">{$i18n.t('Block')}</span>
							</div>
							<span class="text-gray-400 text-[10px]">→ {$i18n.t('End flow')}</span>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Subflow Configuration -->
			{#if isNodeType(node.type, 'subflow')}
				{@const availableFlows = flows.filter(f => f.id !== currentFlowId)}
				<div>
					<label class={labelClass}>{$i18n.t('Select Flow')}</label>
					{#if loading}
						<p class="text-xs text-gray-500">{$i18n.t('Loading')}...</p>
					{:else if availableFlows.length === 0}
						<div class="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg p-2.5">
							{$i18n.t('No flows available. Create a flow first.')}
						</div>
					{:else}
						<select
							bind:value={resourceId}
							on:change={handleUpdate}
							class={selectClass}
						>
							<option value="">{$i18n.t('Select a flow')}</option>
							{#each availableFlows as flow}
								<option value={flow.id}>{flow.name}</option>
							{/each}
						</select>
						{#if resourceId}
							{@const selectedFlow = flows.find((f) => f.id === resourceId)}
							{#if selectedFlow?.description}
								<p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
									{selectedFlow.description}
								</p>
							{/if}
						{/if}
					{/if}
				</div>

				<!-- Subflow input mapping (advanced) -->
				<details class="group">
					<summary class="flex items-center gap-1 cursor-pointer text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300">
						<svg class="size-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
						</svg>
						{$i18n.t('Advanced Settings')}
					</summary>
					<div class="mt-2 space-y-2 pl-4 border-l-2 border-gray-100 dark:border-gray-800">
						<div>
							<label class="text-[10px] text-gray-500 dark:text-gray-400 mb-1 block">{$i18n.t('Output Name')}</label>
							<input
								type="text"
								bind:value={config.stateKey}
								on:change={handleUpdate}
								class="w-full px-2 py-1 text-xs font-mono rounded bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600"
								placeholder="subflow_result"
							/>
						</div>
					</div>
				</details>
			{/if}

			<!-- Output Node Configuration -->
			{#if isNodeType(node.type, 'flowOutput', 'output')}
				<div>
					<label class={labelClass}>{$i18n.t('Action Type')}</label>
					<select
						bind:value={config.actionType}
						on:change={handleUpdate}
						class={selectClass}
					>
						<option value="passthrough">{$i18n.t('Passthrough')} - {$i18n.t('Return current output as-is')}</option>
						<option value="response">{$i18n.t('Response')} - {$i18n.t('Generate final response with prompt')}</option>
						<option value="error">{$i18n.t('Error')} - {$i18n.t('Return as error message')}</option>
					</select>
				</div>

				<!-- Response mode settings -->
				{#if config.actionType === 'response'}
					<div>
					<div class="flex items-center gap-2 text-xs">
						<Checkbox
							state={config.usePrompt ? 'checked' : 'unchecked'}
							on:change={(e) => {
								config.usePrompt = e.detail === 'checked';
								handleUpdate();
							}}
						/>
						<span class="text-gray-700 dark:text-gray-300">{$i18n.t('Use custom prompt for final response')}</span>
					</div>
					</div>

					{#if config.usePrompt}
						<div>
							<label class={labelClass}>{$i18n.t('Final Response Prompt')}</label>
							<textarea
								bind:value={config.prompt}
								on:change={handleUpdate}
								rows="4"
								class="{inputClass} resize-none"
								placeholder={$i18n.t('Enter prompt for generating the final response...')}
							></textarea>
							<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
								{$i18n.t('Use')} <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{input}'}</code>,
								<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{output}'}</code>,
								<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{sources}'}</code>
							</p>

							<!-- Available State Keys -->
							{#if stateKeys.length > 0}
								<details class="mt-2 group">
									<summary class="flex items-center gap-1 cursor-pointer text-[10px] text-blue-500 dark:text-blue-400 hover:text-blue-600 dark:hover:text-blue-300">
										<svg class="size-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
										</svg>
										{$i18n.t('Available State Keys')} ({stateKeys.length})
									</summary>
									<div class="mt-1.5 flex flex-wrap gap-1">
										{#each stateKeys as sk}
											<button
												type="button"
												class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 font-mono hover:bg-blue-100 dark:hover:bg-blue-900/40 transition"
												on:click={() => {
													config.prompt = (config.prompt || '') + '{' + sk.key + '}';
													handleUpdate();
												}}
												title="{sk.source} ({sk.type})"
											>
												{'{' + sk.key + '}'}
											</button>
										{/each}
									</div>
								</details>
							{/if}
						</div>

						<!-- Model selection for response generation -->
						<div>
							<label class={labelClass}>{$i18n.t('Model for Response')}</label>
							<select
								bind:value={config.modelId}
								on:change={handleUpdate}
								class={selectClass}
							>
								<option value="" disabled>{$i18n.t('Select model')}</option>
								{#each baseModels as model}
									<option value={model.id}>{model.name}</option>
								{/each}
							</select>
						</div>
					{/if}
				{/if}

				<!-- Error mode settings -->
				{#if config.actionType === 'error'}
					<div>
						<label class={labelClass}>{$i18n.t('Error Message Template')}</label>
						<textarea
							bind:value={config.errorTemplate}
							on:change={handleUpdate}
							rows="2"
							class="{inputClass} resize-none"
							placeholder={$i18n.t('Error: {output}')}
						></textarea>
						<p class="text-[10px] text-gray-500 dark:text-gray-400 mt-1">
							{$i18n.t('Use')} <code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{'{output}'}</code> {$i18n.t('for the current value')}
						</p>

						<!-- Available State Keys for error template -->
						{#if stateKeys.length > 0}
							<div class="mt-1.5 flex flex-wrap gap-1">
								{#each stateKeys as sk}
									<button
										type="button"
										class="text-[10px] px-1.5 py-0.5 rounded bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 font-mono hover:bg-orange-100 dark:hover:bg-orange-900/40 transition"
										on:click={() => {
											config.errorTemplate = (config.errorTemplate || '') + '{' + sk.key + '}';
											handleUpdate();
										}}
										title="{sk.source} ({sk.type})"
									>
										{'{' + sk.key + '}'}
									</button>
								{/each}
							</div>
						{/if}
					</div>
				{/if}

				<!-- Output info -->
				<div class="text-xs bg-gray-50 dark:bg-gray-800/50 rounded-lg p-2.5">
					<p class="font-medium text-gray-700 dark:text-gray-300 mb-1.5">{$i18n.t('Output Behavior')}</p>
					{#if config.actionType === 'passthrough' || !config.actionType}
						<p class="text-gray-500 dark:text-gray-400">
							➡️ {$i18n.t('Returns the current output directly to the user')}
						</p>
					{:else if config.actionType === 'response'}
						<p class="text-gray-500 dark:text-gray-400">
							💬 {$i18n.t('Generates a polished response using the prompt and sources')}
						</p>
					{:else if config.actionType === 'error'}
						<p class="text-gray-500 dark:text-gray-400">
							⚠️ {$i18n.t('Returns an error message to indicate flow failure')}
						</p>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>
