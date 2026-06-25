<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import { getRAGConfig, updateRAGConfig } from '$lib/apis/retrieval';
	import { getGuardrails } from '$lib/apis/guardrails';

	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';

	import { models, guardrails, config } from '$lib/stores';
	import { isFeatureAllowed } from '$lib/utils/license';

	const i18n = getContext('i18n');

	let loading = true;
	let RAGConfig: any = null;

	// File Upload Guardrails local state
	let newNsfwPassExample = '';
	let newNsfwBlockExample = '';
	let newClassPassText = '';
	let newClassPassExpected = '';
	let newClassBlockText = '';
	let newClassBlockExpected = '';
	let newCategoryId = '';
	let newCategoryDescription = '';
	let newCategoryAction = 'allow';

	const submitHandler = async () => {
		const res = await updateRAGConfig(localStorage.token, RAGConfig);
		dispatch('save');
	};

	$: guardrailOptions = [
		{ value: '', label: $i18n.t('None') },
		...(($guardrails ?? []).map((g) => ({ value: g.id, label: g.name })))
	];

	$: modelOptions = [
		{ value: '', label: $i18n.t('Select a model') },
		...$models
			.filter((m) => !m.base_model_id && !m.preset && !(m.arena ?? false))
			.map((m) => ({ value: m.id, label: m.name }))
	];

	$: macroActionOptions = [
		{ value: 'block', label: $i18n.t('Block') },
		{ value: 'flag', label: $i18n.t('Flag') }
	];

	$: categoryActionOptions = [
		{ value: 'allow', label: $i18n.t('Allow') },
		{ value: 'flag', label: $i18n.t('Flag') },
		{ value: 'block', label: $i18n.t('Block') }
	];

	onMount(async () => {
		RAGConfig = await getRAGConfig(localStorage.token);

		// Ensure file_guardrail has default values
		if (!RAGConfig.file_guardrail) {
			RAGConfig.file_guardrail = {
				FILE_GUARDRAIL_ENABLED: false,
				FILE_GUARDRAIL_SCOPES: ['chat', 'knowledge', 'project'],
				FILE_GUARDRAIL_IDS: [],
				FILE_GUARDRAIL_EXIF_ENABLED: false,
				FILE_GUARDRAIL_MACRO_ENABLED: false,
				FILE_GUARDRAIL_MACRO_ACTION: 'block',
				FILE_GUARDRAIL_NSFW_ENABLED: false,
				FILE_GUARDRAIL_NSFW_MODEL: '',
				FILE_GUARDRAIL_NSFW_PROMPT:
					"Analyze this image for inappropriate content (sexual, violent, hateful, or self-harm). Respond with ONLY 'PASS' if the image is safe, or 'BLOCK' if inappropriate.",
				FILE_GUARDRAIL_NSFW_PASS_EXAMPLES: [],
				FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES: [],
				FILE_GUARDRAIL_CLASSIFICATION_ENABLED: false,
				FILE_GUARDRAIL_CLASSIFICATION_MODEL: '',
				FILE_GUARDRAIL_CLASSIFICATION_PROMPT:
					'You are a document classification system.\nAnalyze the document content and classify it into exactly one sensitivity category.\n\nCategories:\n{categories}\n\nConsider: titles, headers, disclaimers, sensitivity markings, and actual content.\nWhen uncertain, choose the more restrictive category.\n\nRespond with ONLY JSON: {"category": "<CATEGORY_ID>", "confidence": <0.0-1.0>, "reason": "<brief reason>"}',
				FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES: [],
				FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES: [],
				FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS: 8000,
				FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES: [
					{ id: 'PUBLIC', name: 'Public', description: 'Publicly shareable', action: 'allow' },
					{
						id: 'INTERNAL',
						name: 'Internal',
						description: 'Internal use only',
						action: 'allow'
					},
					{
						id: 'CONFIDENTIAL',
						name: 'Confidential',
						description: 'Business sensitive',
						action: 'flag'
					},
					{
						id: 'RESTRICTED',
						name: 'Restricted',
						description: 'Highly sensitive',
						action: 'block'
					}
				]
			};
		}

		// Ensure global_guardrail has default values
		if (!RAGConfig.global_guardrail) {
			RAGConfig.global_guardrail = {
				ENABLE_GLOBAL_GUARDRAIL: false,
				GLOBAL_GUARDRAIL_IDS: []
			};
		}

		// Ensure SCOPES default
		if (!RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES) {
			RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES = ['chat', 'knowledge', 'project', 'channel'];
		}

		// Load guardrails list for selector
		if ($guardrails === null) {
			try {
				const res = await getGuardrails(localStorage.token);
				if (res) {
					guardrails.set(res);
				}
			} catch {
				guardrails.set([]);
			}
		}

		loading = false;
	});
</script>

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else if RAGConfig}
	<form
		class="flex flex-col h-full justify-between text-sm"
		on:submit|preventDefault={() => {
			submitHandler();
		}}
	>
		<div class="overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			{#if isFeatureAllowed($config, 'global_guardrail')}
			<!-- Global Guardrails Section -->
			<div class="my-2">
				<div class="mb-2.5 flex w-full justify-between">
					<div class="text-base font-medium">{$i18n.t('Global Guardrails')}</div>
					<Switch bind:state={RAGConfig.global_guardrail.ENABLE_GLOBAL_GUARDRAIL} />
				</div>

				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t('Applied to all chats and agents regardless of individual agent guardrail settings.')}
				</div>

				{#if RAGConfig.global_guardrail?.ENABLE_GLOBAL_GUARDRAIL}
					<div class="mb-2.5 flex w-full justify-between items-center gap-2">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Select a guardrail to apply to all chats. PII detection, blocked words, and LLM Judge will be enforced globally.'
								)}
								placement="top-start"
							>
								{$i18n.t('Chat Guardrail')}
							</Tooltip>
						</div>
						<div class="min-w-[180px]">
							<Selector
								value={RAGConfig.global_guardrail.GLOBAL_GUARDRAIL_IDS?.[0] ?? ''}
								items={guardrailOptions}
								size="sm"
								on:change={(e) => {
									RAGConfig.global_guardrail.GLOBAL_GUARDRAIL_IDS = e.detail.value
										? [e.detail.value]
										: [];
								}}
							/>
						</div>
					</div>
				{/if}

				<hr class="border-gray-100 dark:border-gray-850 my-3" />
			</div>
			{/if}

			<!-- File Upload Guardrails Section -->
			<div class="my-2">
				<!-- Master Switch -->
				<div class="mb-2.5 flex w-full justify-between">
					<div class="text-base font-medium">{$i18n.t('File Upload Guardrails')}</div>
					<Switch bind:state={RAGConfig.file_guardrail.FILE_GUARDRAIL_ENABLED} />
				</div>

				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t(
						'Apply security checks to uploaded files. When enabled, files are scanned for macros, EXIF metadata, inappropriate content, and sensitive information before being processed.'
					)}
				</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				{#if RAGConfig.file_guardrail?.FILE_GUARDRAIL_ENABLED}
					<!-- Scope Selection -->
					<div class="mb-4">
						<div class="mb-2">
							<div class="text-xs font-medium mb-0.5">
								{$i18n.t('Applied Scopes')}
							</div>
							<div class="text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t(
									'Select which upload contexts the guardrails apply to. Unchecked contexts will skip all guardrail checks.'
								)}
							</div>
						</div>

						<div class="flex flex-wrap gap-2 mt-2">
							{#each [
								{ id: 'chat', label: $i18n.t('Chat') },
								{ id: 'knowledge', label: $i18n.t('Knowledge') },
								{ id: 'project', label: $i18n.t('Project') }
							] as scope}
								<div
									class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer transition
										{RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES?.includes(scope.id)
										? 'bg-gray-200 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
										: 'bg-gray-50 text-gray-500 dark:bg-gray-900/50 dark:text-gray-400'}"
								>
									<Checkbox
										state={RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES?.includes(scope.id) ? 'checked' : 'unchecked'}
										on:change={(e) => {
											if (e.detail === 'checked') {
												RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES = [
													...(RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES ?? []),
													scope.id
												];
											} else {
												RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES =
													(RAGConfig.file_guardrail.FILE_GUARDRAIL_SCOPES ?? []).filter(
														(s) => s !== scope.id
													);
											}
										}}
									/>
									{scope.label}
								</div>
							{/each}
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- A. Text Guardrails (single select dropdown) -->
					<div class="mb-2.5 flex w-full justify-between items-center gap-2">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Scan extracted document text with a guardrail. If a violation is detected (e.g. PII, sensitive data), the file upload will be blocked.'
								)}
								placement="top-start"
							>
								{$i18n.t('Text Content Guardrails')}
							</Tooltip>
						</div>
						<div class="min-w-[180px]">
							<Selector
								value={RAGConfig.file_guardrail.FILE_GUARDRAIL_IDS?.[0] ?? ''}
								items={guardrailOptions}
								size="sm"
								on:change={(e) => {
									RAGConfig.file_guardrail.FILE_GUARDRAIL_IDS = e.detail.value
										? [e.detail.value]
										: [];
								}}
							/>
						</div>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- B. EXIF Metadata Stripping -->
					<div class="mb-2.5 flex w-full justify-between">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Automatically strip GPS, camera info and other EXIF metadata from uploaded images.'
								)}
								placement="top-start"
							>
								{$i18n.t('EXIF Metadata Stripping')}
							</Tooltip>
						</div>
						<Switch bind:state={RAGConfig.file_guardrail.FILE_GUARDRAIL_EXIF_ENABLED} />
					</div>

					<!-- C-1. Macro Detection -->
					<div class="mb-2.5 flex w-full justify-between">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Detect VBA macros in Office files. Macro-enabled files can be blocked or flagged.'
								)}
								placement="top-start"
							>
								{$i18n.t('Macro Detection')}
							</Tooltip>
						</div>
						<Switch bind:state={RAGConfig.file_guardrail.FILE_GUARDRAIL_MACRO_ENABLED} />
					</div>

					{#if RAGConfig.file_guardrail?.FILE_GUARDRAIL_MACRO_ENABLED}
						<div class="mb-2.5 flex w-full justify-between items-center ml-4 gap-2">
							<div class="self-center text-xs font-medium">{$i18n.t('Action')}</div>
							<div class="min-w-[120px]">
								<Selector
									value={RAGConfig.file_guardrail.FILE_GUARDRAIL_MACRO_ACTION}
									items={macroActionOptions}
									size="sm"
									on:change={(e) => {
										RAGConfig.file_guardrail.FILE_GUARDRAIL_MACRO_ACTION = e.detail.value;
									}}
								/>
							</div>
						</div>
					{/if}

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- C. NSFW Image Detection -->
					<div class="mb-2.5 flex w-full justify-between">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Use a Vision LLM to detect inappropriate images during upload.'
								)}
								placement="top-start"
							>
								{$i18n.t('NSFW Image Detection')}
							</Tooltip>
						</div>
						<Switch bind:state={RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_ENABLED} />
					</div>

					{#if RAGConfig.file_guardrail?.FILE_GUARDRAIL_NSFW_ENABLED}
						<div class="mb-2.5 flex w-full justify-between items-center ml-4 gap-2">
							<div class="self-center text-xs font-medium">{$i18n.t('Model')}</div>
							<div class="min-w-[180px]">
								<Selector
									value={RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_MODEL}
									items={modelOptions}
									size="sm"
									searchEnabled
									on:change={(e) => {
										RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_MODEL = e.detail.value;
									}}
								/>
							</div>
						</div>

						<div class="space-y-1.5 mb-2.5 ml-4">
							<Textarea
								bind:value={RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PROMPT}
								label={$i18n.t('Prompt')}
								size="sm"
								rows={3}
							/>
						</div>

						<div class="space-y-1.5 mb-2.5 ml-4">
							<div class="text-xs font-medium">{$i18n.t('Pass Examples')}</div>
							{#each RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES as ex, idx}
								<div
									class="flex items-center gap-2 p-1.5 bg-green-50 dark:bg-green-900/20 rounded-lg text-xs"
								>
									<span class="flex-1">{ex}</span>
									<Button
										kind="text"
										size="sm"
										status="error"
										on:click={() => {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES =
												RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES.filter(
													(_, i) => i !== idx
												);
										}}
									>
										×
									</Button>
								</div>
							{/each}
							<div class="flex gap-2 items-end">
								<div class="flex-1">
									<Input
										bind:value={newNsfwPassExample}
										placeholder={$i18n.t('Describe a safe image example')}
										size="sm"
									/>
								</div>
								<Button
									kind="filled"
									size="sm"
									on:click={() => {
										if (newNsfwPassExample.trim()) {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES = [
												...RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_PASS_EXAMPLES,
												newNsfwPassExample.trim()
											];
											newNsfwPassExample = '';
										}
									}}
								>
									{$i18n.t('Add')}
								</Button>
							</div>
						</div>

						<div class="space-y-1.5 mb-2.5 ml-4">
							<div class="text-xs font-medium">{$i18n.t('Block Examples')}</div>
							{#each RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES as ex, idx}
								<div
									class="flex items-center gap-2 p-1.5 bg-red-50 dark:bg-red-900/20 rounded-lg text-xs"
								>
									<span class="flex-1">{ex}</span>
									<Button
										kind="text"
										size="sm"
										status="error"
										on:click={() => {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES =
												RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES.filter(
													(_, i) => i !== idx
												);
										}}
									>
										×
									</Button>
								</div>
							{/each}
							<div class="flex gap-2 items-end">
								<div class="flex-1">
									<Input
										bind:value={newNsfwBlockExample}
										placeholder={$i18n.t('Describe an inappropriate image example')}
										size="sm"
									/>
								</div>
								<Button
									kind="filled"
									size="sm"
									status="error"
									on:click={() => {
										if (newNsfwBlockExample.trim()) {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES = [
												...RAGConfig.file_guardrail.FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES,
												newNsfwBlockExample.trim()
											];
											newNsfwBlockExample = '';
										}
									}}
								>
									{$i18n.t('Add')}
								</Button>
							</div>
						</div>
					{/if}

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- D. Document Classification -->
					<div class="mb-2.5 flex w-full justify-between">
						<div class="self-center text-xs font-medium">
							<Tooltip
								content={$i18n.t(
									'Use an LLM to classify document sensitivity. Categories can be configured with allow/flag/block actions.'
								)}
								placement="top-start"
							>
								{$i18n.t('Document Classification')}
							</Tooltip>
						</div>
						<Switch
							bind:state={RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_ENABLED}
						/>
					</div>

					{#if RAGConfig.file_guardrail?.FILE_GUARDRAIL_CLASSIFICATION_ENABLED}
						<div class="mb-2.5 flex w-full justify-between items-center ml-4 gap-2">
							<div class="self-center text-xs font-medium">{$i18n.t('Model')}</div>
							<div class="min-w-[180px]">
								<Selector
									value={RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_MODEL}
									items={modelOptions}
									size="sm"
									searchEnabled
									on:change={(e) => {
										RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_MODEL = e.detail.value;
									}}
								/>
							</div>
						</div>

						<div class="mb-2.5 flex w-full justify-between items-center ml-4 gap-2">
							<div class="self-center text-xs font-medium">
								{$i18n.t('Max Characters')}
							</div>
							<div class="w-28">
								<Input
									type="number"
									bind:value={RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS}
									size="sm"
								/>
							</div>
						</div>

						<div class="space-y-1.5 mb-2.5 ml-4">
							<Textarea
								bind:value={RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_PROMPT}
								label={$i18n.t('Prompt')}
								size="sm"
								rows={5}
							/>
						</div>

						<!-- Categories -->
						<div class="space-y-1.5 mb-2.5 ml-4">
							<div class="text-xs font-medium">{$i18n.t('Categories')}</div>
							<div class="space-y-1">
								{#each RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES as cat, idx}
									<div
										class="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-850 rounded-lg text-xs gap-2"
									>
										<div class="flex items-center gap-2 min-w-0 flex-1">
											<span class="font-medium shrink-0">{cat.id}</span>
											<span class="text-gray-500 dark:text-gray-400 truncate"
												>{cat.description}</span
											>
										</div>
										<div class="flex items-center gap-1 shrink-0">
											<div class="min-w-[100px]">
												<Selector
													value={cat.action}
													items={categoryActionOptions}
													size="sm"
													on:change={(e) => {
														cat.action = e.detail.value;
														RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES =
															RAGConfig.file_guardrail
																.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES;
													}}
												/>
											</div>
											<Button
												kind="text"
												size="sm"
												status="error"
												on:click={() => {
													RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES =
														RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES.filter(
															(_, i) => i !== idx
														);
												}}
											>
												×
											</Button>
										</div>
									</div>
								{/each}
							</div>
							<div class="flex gap-2 items-end">
								<div class="w-24">
									<Input
										bind:value={newCategoryId}
										placeholder={$i18n.t('ID')}
										size="sm"
									/>
								</div>
								<div class="flex-1">
									<Input
										bind:value={newCategoryDescription}
										placeholder={$i18n.t('Description')}
										size="sm"
									/>
								</div>
								<div class="min-w-[100px]">
									<Selector
										value={newCategoryAction}
										items={categoryActionOptions}
										size="sm"
										on:change={(e) => {
											newCategoryAction = e.detail.value;
										}}
									/>
								</div>
								<Button
									kind="filled"
									size="sm"
									on:click={() => {
										if (newCategoryId.trim()) {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES =
												[
													...RAGConfig.file_guardrail
														.FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES,
													{
														id: newCategoryId.trim().toUpperCase(),
														name: newCategoryId.trim(),
														description: newCategoryDescription.trim(),
														action: newCategoryAction
													}
												];
											newCategoryId = '';
											newCategoryDescription = '';
											newCategoryAction = 'allow';
										}
									}}
								>
									{$i18n.t('Add')}
								</Button>
							</div>
						</div>

						<!-- Classification Pass Examples -->
						<div class="space-y-1.5 mb-2.5 ml-4">
							<div class="text-xs font-medium">{$i18n.t('Pass Examples')}</div>
							{#each RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES as ex, idx}
								<div
									class="flex items-center gap-2 p-1.5 bg-green-50 dark:bg-green-900/20 rounded-lg text-xs"
								>
									<span class="flex-1 truncate">"{ex.text}" → {ex.expected}</span>
									<Button
										kind="text"
										size="sm"
										status="error"
										on:click={() => {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES =
												RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES.filter(
													(_, i) => i !== idx
												);
										}}
									>
										×
									</Button>
								</div>
							{/each}
							<div class="flex gap-2 items-end">
								<div class="flex-1">
									<Input
										bind:value={newClassPassText}
										placeholder={$i18n.t('Sample text')}
										size="sm"
									/>
								</div>
								<div class="w-24">
									<Input
										bind:value={newClassPassExpected}
										placeholder={$i18n.t('Category')}
										size="sm"
									/>
								</div>
								<Button
									kind="filled"
									size="sm"
									on:click={() => {
										if (newClassPassText.trim() && newClassPassExpected.trim()) {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES =
												[
													...RAGConfig.file_guardrail
														.FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES,
													{
														text: newClassPassText.trim(),
														expected: newClassPassExpected.trim().toUpperCase()
													}
												];
											newClassPassText = '';
											newClassPassExpected = '';
										}
									}}
								>
									{$i18n.t('Add')}
								</Button>
							</div>
						</div>

						<!-- Classification Block Examples -->
						<div class="space-y-1.5 mb-2.5 ml-4">
							<div class="text-xs font-medium">{$i18n.t('Block Examples')}</div>
							{#each RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES as ex, idx}
								<div
									class="flex items-center gap-2 p-1.5 bg-red-50 dark:bg-red-900/20 rounded-lg text-xs"
								>
									<span class="flex-1 truncate">"{ex.text}" → {ex.expected}</span>
									<Button
										kind="text"
										size="sm"
										status="error"
										on:click={() => {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES =
												RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES.filter(
													(_, i) => i !== idx
												);
										}}
									>
										×
									</Button>
								</div>
							{/each}
							<div class="flex gap-2 items-end">
								<div class="flex-1">
									<Input
										bind:value={newClassBlockText}
										placeholder={$i18n.t('Sample text')}
										size="sm"
									/>
								</div>
								<div class="w-24">
									<Input
										bind:value={newClassBlockExpected}
										placeholder={$i18n.t('Category')}
										size="sm"
									/>
								</div>
								<Button
									kind="filled"
									size="sm"
									status="error"
									on:click={() => {
										if (newClassBlockText.trim() && newClassBlockExpected.trim()) {
											RAGConfig.file_guardrail.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES =
												[
													...RAGConfig.file_guardrail
														.FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES,
													{
														text: newClassBlockText.trim(),
														expected: newClassBlockExpected.trim().toUpperCase()
													}
												];
											newClassBlockText = '';
											newClassBlockExpected = '';
										}
									}}
								>
									{$i18n.t('Add')}
								</Button>
							</div>
						</div>
					{/if}
				{/if}
			</div>
		</div>

	<div class="flex justify-end pt-3">
		<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
	</form>
{/if}
