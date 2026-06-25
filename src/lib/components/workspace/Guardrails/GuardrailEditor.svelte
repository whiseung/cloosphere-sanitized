<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { goto } from '$app/navigation';

	import { WEBUI_NAME, guardrails, models, user } from '$lib/stores';
	import {
		getGuardrails,
		getGuardrailById,
		updateGuardrail,
		testGuardrail,
		type GuardrailForm
	} from '$lib/apis/guardrails';

	import { getGroups } from '$lib/apis/groups';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Card from '$lib/components/common/Card.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import AccessControlModal from '$lib/components/workspace/common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '$lib/components/workspace/common/WorkspaceDetailHeader.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	export let id: string | null = null;

	let loaded = false;
	let saving = false;
	let testing = false;

	let showAccessControlModal = false;
	let tagSelector: any;
	let group_ids: string[] = [];
	let guardrailUserId: string | null = null;

	$: isOwnerOrAdmin = $user?.role === 'admin' || guardrailUserId === $user?.id;

	$: canWrite =
		$user?.role === 'admin' ||
		($user?.permissions?.workspace?.guardrails === 'write' &&
			(guardrailUserId === $user?.id ||
				accessControl?.write?.user_ids?.includes($user?.id) ||
				accessControl?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))));

	// Form data
	let name = '';
	let description = '';
	let accessControl: any = {
		read: {
			group_ids: [],
			user_ids: [$user?.id]
		},
		write: {
			group_ids: [],
			user_ids: [$user?.id]
		}
	};

	// Rule-based settings
	let piiTypes: string[] = [];
	let piiStrategy = 'redact';
	let customPatterns: { name: string; pattern: string }[] = [];
	let blockedWords: string[] = [];
	let applyToInput = true;
	let applyToOutput = false;

	// LLM-as-a-Judge settings
	let llmJudgeEnabled = false;
	let llmJudgeModel = '';
	let llmJudgePrompt = '';
	let llmJudgePassExamples: string[] = [];
	let llmJudgeBlockExamples: string[] = [];
	let llmJudgeApplyToInput = true;
	let llmJudgeApplyToOutput = false;

	// Test
	let testText = '';
	let testResult: { processed_text: string; violations: any[]; blocked: boolean } | null = null;

	// 걸림(차단 또는 감지) 여부 = 결과 배경색. 걸리면 빨강, 깨끗하면 초록.
	$: testCaught = !!testResult && (testResult.blocked || testResult.violations.length > 0);

	// New pattern/word input
	let newPatternName = '';
	let newPatternValue = '';
	let newBlockedWord = '';
	let newPassExample = '';
	let newBlockExample = '';

	// PII type definitions with tooltips
	$: PII_TYPES = [
		{
			id: 'email',
			label: $i18n.t('Email'),
			description: $i18n.t('Detects email addresses (e.g., user@domain.com)')
		},
		{
			id: 'credit_card',
			label: $i18n.t('Credit Card'),
			description: $i18n.t('Detects credit card numbers (validated with Luhn algorithm)')
		},
		{
			id: 'ip',
			label: $i18n.t('IP Address'),
			description: $i18n.t('Detects IPv4 addresses (e.g., 192.168.1.1)')
		},
		{
			id: 'mac',
			label: $i18n.t('MAC Address'),
			description: $i18n.t('Detects MAC addresses (e.g., 00:1A:2B:3C:4D:5E)')
		},
		{ id: 'url', label: $i18n.t('URL'), description: $i18n.t('Detects URLs (http/https links)') },
		{
			id: 'api_key',
			label: $i18n.t('API Key'),
			description: $i18n.t('Detects API keys (sk-xxx pattern)')
		}
	];

	// Strategy options with tooltips
	$: STRATEGIES = [
		{
			id: 'block',
			label: $i18n.t('Block'),
			description: $i18n.t(
				'Completely blocks the message when sensitive information is detected. The user will see an error message and the request will not be processed.'
			)
		},
		{
			id: 'redact',
			label: $i18n.t('Redact'),
			description: $i18n.t(
				'Removes sensitive information and replaces it with a label like [REDACTED_EMAIL]. The message continues to be processed with the redacted content.'
			)
		},
		{
			id: 'mask',
			label: $i18n.t('Mask'),
			description: $i18n.t(
				'Partially hides sensitive information while keeping some characters visible. For example, an email becomes "j***@***.com" or a card number becomes "****-****-****-1234".'
			)
		},
		{
			id: 'hash',
			label: $i18n.t('Hash'),
			description: $i18n.t(
				'Converts sensitive information into a unique code (hash). Useful when you need to track or match the same information later without exposing the original value.'
			)
		},
		{
			id: 'log',
			label: $i18n.t('Log'),
			description: $i18n.t(
				'Detects sensitive information and logs it without modifying the message. Useful for monitoring.'
			)
		}
	];

	// Judge model options for the Selector.
	$: modelItems = $models
		.filter((m: any) => !m?.info?.base_model_id && !m?.preset && m?.owned_by !== 'arena')
		.map((m: any) => ({ value: m.id, label: m.name ?? m.id }));

	const togglePiiType = (typeId: string) => {
		if (piiTypes.includes(typeId)) {
			piiTypes = piiTypes.filter((t) => t !== typeId);
		} else {
			piiTypes = [...piiTypes, typeId];
		}
	};

	const handleModelChange = (e: CustomEvent<{ value: string | number }>) => {
		llmJudgeModel = String(e.detail.value);
	};

	const addCustomPattern = () => {
		if (newPatternName && newPatternValue) {
			customPatterns = [...customPatterns, { name: newPatternName, pattern: newPatternValue }];
			newPatternName = '';
			newPatternValue = '';
		}
	};

	const removeCustomPattern = (index: number) => {
		customPatterns = customPatterns.filter((_, i) => i !== index);
	};

	const addBlockedWord = () => {
		if (newBlockedWord && !blockedWords.includes(newBlockedWord)) {
			blockedWords = [...blockedWords, newBlockedWord];
			newBlockedWord = '';
		}
	};

	const removeBlockedWord = (word: string) => {
		blockedWords = blockedWords.filter((w) => w !== word);
	};

	// 공통 Input 은 native keydown 을 CustomEvent.detail 로 forward 한다 (Input.svelte).
	const handleBlockedWordKeydown = (e: CustomEvent<KeyboardEvent>) => {
		if (e.detail.key === 'Enter') {
			e.detail.preventDefault();
			addBlockedWord();
		}
	};

	const addPassExample = () => {
		if (newPassExample) {
			llmJudgePassExamples = [...llmJudgePassExamples, newPassExample];
			newPassExample = '';
		}
	};

	const removePassExample = (index: number) => {
		llmJudgePassExamples = llmJudgePassExamples.filter((_, i) => i !== index);
	};

	const addBlockExample = () => {
		if (newBlockExample) {
			llmJudgeBlockExamples = [...llmJudgeBlockExamples, newBlockExample];
			newBlockExample = '';
		}
	};

	const removeBlockExample = (index: number) => {
		llmJudgeBlockExamples = llmJudgeBlockExamples.filter((_, i) => i !== index);
	};

	const getFormData = (): GuardrailForm => ({
		name,
		description,
		pii_types: piiTypes,
		pii_strategy: piiStrategy,
		custom_patterns: customPatterns,
		blocked_words: blockedWords,
		apply_to_input: applyToInput,
		apply_to_output: applyToOutput,
		llm_judge_enabled: llmJudgeEnabled,
		llm_judge_model: llmJudgeModel || undefined,
		llm_judge_prompt: llmJudgePrompt || undefined,
		llm_judge_pass_examples: llmJudgePassExamples,
		llm_judge_block_examples: llmJudgeBlockExamples,
		llm_judge_apply_to_input: llmJudgeApplyToInput,
		llm_judge_apply_to_output: llmJudgeApplyToOutput,
		access_control: accessControl
	});

	const handleSave = async () => {
		if (!name) {
			toast.error($i18n.t('Name is required'));
			return;
		}

		saving = true;

		try {
			// 태그 먼저 커밋
			if (tagSelector?.commitChanges) {
				await tagSelector.commitChanges();
			}

			const formData = getFormData();
			await updateGuardrail(localStorage.token, id!, formData);
			toast.success($i18n.t('Guardrail updated successfully'));
			guardrails.set(await getGuardrails(localStorage.token));
			goto('/workspace/guardrails');
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			saving = false;
		}
	};

	const handleTest = async () => {
		if (!testText) {
			toast.error($i18n.t('Please enter test text'));
			return;
		}

		testing = true;
		testResult = null;

		try {
			const formData = getFormData();
			const result = await testGuardrail(localStorage.token, null, formData, testText);
			testResult = result;
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			testing = false;
		}
	};

	onMount(async () => {
		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		if (id) {
			try {
				const guardrail = await getGuardrailById(localStorage.token, id);
				if (guardrail) {
					guardrailUserId = guardrail.user_id || null;
					name = guardrail.name;
					description = guardrail.description || '';
					piiTypes = guardrail.pii_types || [];
					piiStrategy = guardrail.pii_strategy || 'redact';
					customPatterns = guardrail.custom_patterns || [];
					blockedWords = guardrail.blocked_words || [];
					applyToInput = guardrail.apply_to_input ?? true;
					applyToOutput = guardrail.apply_to_output ?? false;
					llmJudgeEnabled = guardrail.llm_judge_enabled ?? false;
					llmJudgeModel = guardrail.llm_judge_model || '';
					llmJudgePrompt = guardrail.llm_judge_prompt || '';
					llmJudgePassExamples = guardrail.llm_judge_pass_examples || [];
					llmJudgeBlockExamples = guardrail.llm_judge_block_examples || [];
					llmJudgeApplyToInput = guardrail.llm_judge_apply_to_input ?? true;
					llmJudgeApplyToOutput = guardrail.llm_judge_apply_to_output ?? false;
					accessControl = guardrail.access_control || null;
				}
			} catch (e) {
				toast.error($i18n.t(`${e}`));
				goto('/workspace/guardrails');
			}
		}
		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Edit Guardrail')} | {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<AccessControlModal
		bind:show={showAccessControlModal}
		bind:accessControl
		allowPublic={$user?.permissions?.sharing?.public_guardrails || $user?.role === 'admin'}
		accessRoles={['read', 'write']}
	/>

	<div class="flex flex-col w-full h-full translate-y-1">
		<!-- Header -->
		<WorkspaceDetailHeader
			backHref="/workspace/guardrails"
			badgeContent={$i18n.t('Guardrail')}
			bind:name
			namePlaceholder={$i18n.t('Guardrail Name')}
			bind:description
			descriptionPlaceholder={$i18n.t('Guardrail Description')}
			resourceType="guardrail"
			resourceId={id ?? ''}
			bind:tagSelector
			showAccess={isOwnerOrAdmin && canWrite}
			{canWrite}
			{saving}
			on:access={() => (showAccessControlModal = true)}
			on:save={handleSave}
		/>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto pb-4">
			<div class="max-w-[860px] mx-auto w-full flex flex-col gap-4 px-4 sm:px-0">
				<!-- Card: Rule-based Detection (always active) -->
				<Card padding="none">
					<svelte:fragment slot="header">
						<div class="px-6 py-3">
							<LabelBase
								label={$i18n.t('Rule-based Detection')}
								caption={$i18n.t('Define PII types, patterns, and blocked words as rules')}
								size="md"
							/>
						</div>
					</svelte:fragment>

					<div class="px-6 py-4 flex flex-col gap-3">
						<!-- PII Types -->
						<div class="flex flex-col sm:flex-row sm:items-center gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('PII Types')}
							</div>
							<div class="flex-1 min-w-0 flex flex-wrap gap-2">
								{#each PII_TYPES as piiType}
									<Tooltip content={piiType.description}>
										<Button
											kind="outlined"
											size="md"
											className={piiTypes.includes(piiType.id)
												? '!bg-[var(--cloo-bg-neutral-hovered)]'
												: ''}
											on:click={() => togglePiiType(piiType.id)}
										>
											{piiType.label}
										</Button>
									</Tooltip>
								{/each}
							</div>
						</div>

						<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

						<!-- Strategy -->
						<div class="flex flex-col sm:flex-row sm:items-center gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('Strategy')}
							</div>
							<div class="flex-1 min-w-0 flex flex-wrap gap-2">
								{#each STRATEGIES as strategy}
									<Tooltip content={strategy.description}>
										<Button
											kind="outlined"
											size="md"
											className={piiStrategy === strategy.id
												? '!bg-[var(--cloo-bg-neutral-hovered)]'
												: ''}
											on:click={() => (piiStrategy = strategy.id)}
										>
											{strategy.label}
										</Button>
									</Tooltip>
								{/each}
							</div>
						</div>

						<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

						<!-- Apply To -->
						<div class="flex flex-col sm:flex-row sm:items-center gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('Apply to')}
							</div>
							<div class="flex-1 min-w-0 flex flex-wrap gap-2">
								<Tooltip content={$i18n.t('Check user input messages')}>
									<Button
										kind="outlined"
										size="md"
										className={applyToInput ? '!bg-[var(--cloo-bg-neutral-hovered)]' : ''}
										on:click={() => (applyToInput = !applyToInput)}
									>
										{$i18n.t('Input')}
									</Button>
								</Tooltip>
								<Tooltip content={$i18n.t('Check LLM response messages')}>
									<Button
										kind="outlined"
										size="md"
										className={applyToOutput ? '!bg-[var(--cloo-bg-neutral-hovered)]' : ''}
										on:click={() => (applyToOutput = !applyToOutput)}
									>
										{$i18n.t('Output')}
									</Button>
								</Tooltip>
							</div>
						</div>
						{#if applyToOutput}
							<div class="text-xs text-amber-600 dark:text-amber-400 sm:pl-[198px]">
								⚠ {$i18n.t(
									'Output guardrail disables real-time streaming. Responses will be sent after security check is complete.'
								)}
							</div>
						{/if}

						<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

						<!-- Custom Patterns (Regex) -->
						<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('Custom Patterns (Regex)')}
							</div>
							<div class="flex-1 min-w-0 flex flex-col gap-2">
								<div class="flex gap-2 items-center">
									<div class="flex-1 min-w-0">
										<Input
											bind:value={newPatternName}
											size="md"
											placeholder={$i18n.t('Pattern name')}
										/>
									</div>
									<div class="flex-1 min-w-0">
										<Input
											bind:value={newPatternValue}
											size="md"
											placeholder={$i18n.t('Regex pattern')}
										/>
									</div>
									<Button kind="outlined" size="md" on:click={addCustomPattern}>
										<Plus slot="prefix" className="size-3.5" strokeWidth="2" />
										{$i18n.t('Add')}
									</Button>
								</div>
								{#if customPatterns.length > 0}
									<div class="flex flex-wrap gap-1.5">
										{#each customPatterns as pattern, index}
											<div
												class="flex items-center gap-1.5 px-2 py-1 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] text-xs"
											>
												<span class="font-medium text-[var(--cloo-text-primary)]"
													>{pattern.name}:</span
												>
												<span class="text-[var(--cloo-text-muted)]">{pattern.pattern}</span>
												<button
													type="button"
													class="text-[var(--cloo-text-muted)] hover:text-[var(--cloo-color-danger)]"
													aria-label={$i18n.t('Remove')}
													on:click={() => removeCustomPattern(index)}
												>
													<XMark className="size-3.5" strokeWidth="2" />
												</button>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						</div>

						<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

						<!-- Blocked Words -->
						<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('Blocked Words')}
							</div>
							<div class="flex-1 min-w-0 flex flex-col gap-2">
								<div class="flex gap-2 items-center">
									<div class="flex-1 min-w-0">
										<Input
											bind:value={newBlockedWord}
											size="md"
											placeholder={$i18n.t('Enter word to block')}
											on:keydown={handleBlockedWordKeydown}
										/>
									</div>
									<Button kind="outlined" size="md" on:click={addBlockedWord}>
										<Plus slot="prefix" className="size-3.5" strokeWidth="2" />
										{$i18n.t('Add')}
									</Button>
								</div>
								{#if blockedWords.length > 0}
									<div class="flex flex-wrap gap-1.5">
										{#each blockedWords as word}
											<div
												class="flex items-center gap-1.5 px-2 py-1 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)] text-xs"
											>
												<span class="text-[var(--cloo-text-primary)]">{word}</span>
												<button
													type="button"
													class="text-[var(--cloo-text-muted)] hover:text-[var(--cloo-color-danger)]"
													aria-label={$i18n.t('Remove')}
													on:click={() => removeBlockedWord(word)}
												>
													<XMark className="size-3.5" strokeWidth="2" />
												</button>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						</div>

						<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

						<!-- Test Guardrail -->
						<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
							<div
								class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
							>
								{$i18n.t('Test Guardrail')}
							</div>
							<div class="flex-1 min-w-0 flex flex-col gap-2">
								<div class="flex gap-2 items-center">
									<div class="flex-1 min-w-0">
										<Input
											bind:value={testText}
											size="md"
											placeholder={$i18n.t(
												'Enter text to test (e.g., "My email is test@example.com")'
											)}
										/>
									</div>
									<Button
										kind="outlined"
										size="md"
										loading={testing}
										disabled={testing}
										on:click={handleTest}
									>
										{$i18n.t('Test')}
									</Button>
								</div>

								{#if testResult}
									<div
										class="p-3 rounded-[var(--cloo-radius-default)] text-xs {testCaught
											? 'bg-red-50 dark:bg-red-900/20'
											: 'bg-green-50 dark:bg-green-900/20'}"
									>
										<div
											class="font-medium mb-1.5 {testCaught
												? 'text-red-600 dark:text-red-400'
												: 'text-green-600 dark:text-green-400'}"
										>
											{testResult.blocked
												? $i18n.t('Blocked')
												: testResult.violations.length > 0
													? $i18n.t('Detected')
													: $i18n.t('Passed')}
										</div>
										<div>
											<strong>{$i18n.t('Processed Text')}:</strong>
											{testResult.processed_text}
										</div>
										{#if testResult.violations.length > 0}
											<div class="mt-1.5">
												<strong>{$i18n.t('Violations')}:</strong>
												<ul class="list-disc list-inside mt-0.5">
													{#each testResult.violations as violation}
														<li>
															{violation.type}: {violation.matched}
															{#if violation.pii_type}({violation.pii_type}){/if}
														</li>
													{/each}
												</ul>
											</div>
										{/if}
									</div>
								{/if}
							</div>
						</div>
					</div>
				</Card>

				<!-- Card: LLM-as-a-Judge (toggleable) -->
				<Card padding="none">
					<svelte:fragment slot="header">
						<div class="px-6 py-3">
							<LabelBase
								label={$i18n.t('LLM-as-a-Judge')}
								caption={$i18n.t(
									'Enable LLM Judge to use semantic content validation with an LLM.'
								)}
								size="md"
							>
								<svelte:fragment slot="right">
									<Switch bind:state={llmJudgeEnabled} />
								</svelte:fragment>
							</LabelBase>
						</div>
					</svelte:fragment>

					{#if llmJudgeEnabled}
						<div class="px-6 py-4 flex flex-col gap-3">
							<!-- Model Selection -->
							<div class="flex flex-col sm:flex-row sm:items-center gap-2 w-full">
								<div
									class="sm:w-[190px] shrink-0 text-sm font-semibold text-[var(--cloo-text-primary)]"
								>
									{$i18n.t('Model')}
								</div>
								<div class="flex-1 min-w-0 flex sm:justify-end">
									<div class="w-full sm:w-64">
										<Selector
											value={llmJudgeModel}
											items={modelItems}
											size="md"
											searchEnabled
											placeholder={$i18n.t('Select a model')}
											on:change={handleModelChange}
										/>
									</div>
								</div>
							</div>

							<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

							<!-- Judge Prompt -->
							<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
								<div
									class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
								>
									{$i18n.t('Judge Prompt')}
								</div>
								<div class="flex-1 min-w-0">
									<Textarea
										bind:value={llmJudgePrompt}
										size="md"
										rows={3}
										placeholder={$i18n.t(
											'You are a content moderator. Evaluate the following content and respond with either "PASS" if appropriate, or "BLOCK" if it should be blocked.'
										)}
									/>
								</div>
							</div>

							<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

							<!-- Apply To -->
							<div class="flex flex-col sm:flex-row sm:items-center gap-2 w-full">
								<div
									class="sm:w-[190px] shrink-0 text-sm font-semibold text-[var(--cloo-text-primary)]"
								>
									{$i18n.t('Apply LLM Judge to')}
								</div>
								<div class="flex-1 min-w-0 flex flex-wrap gap-2">
									<Button
										kind="outlined"
										size="md"
										className={llmJudgeApplyToInput ? '!bg-[var(--cloo-bg-neutral-hovered)]' : ''}
										on:click={() => (llmJudgeApplyToInput = !llmJudgeApplyToInput)}
									>
										{$i18n.t('Input')}
									</Button>
									<Button
										kind="outlined"
										size="md"
										className={llmJudgeApplyToOutput ? '!bg-[var(--cloo-bg-neutral-hovered)]' : ''}
										on:click={() => (llmJudgeApplyToOutput = !llmJudgeApplyToOutput)}
									>
										{$i18n.t('Output')}
									</Button>
								</div>
							</div>

							<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

							<!-- Pass Examples -->
							<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
								<div
									class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
								>
									{$i18n.t('Pass Examples')}
								</div>
								<div class="flex-1 min-w-0 flex flex-col gap-2">
									<div class="flex gap-2 items-center">
										<div class="flex-1 min-w-0">
											<Input
												bind:value={newPassExample}
												size="md"
												placeholder={$i18n.t('Example of content that should PASS')}
											/>
										</div>
										<Button kind="outlined" size="md" on:click={addPassExample}>
											<Plus slot="prefix" className="size-3.5" strokeWidth="2" />
											{$i18n.t('Add')}
										</Button>
									</div>
									{#if llmJudgePassExamples.length > 0}
										<div class="flex flex-col gap-1">
											{#each llmJudgePassExamples as example, index}
												<div
													class="flex items-center justify-between gap-2 p-1.5 rounded-[var(--cloo-radius-default)] bg-green-50 dark:bg-green-900/20 text-xs"
												>
													<span class="min-w-0 truncate">{example}</span>
													<button
														type="button"
														class="shrink-0 text-[var(--cloo-text-muted)] hover:text-[var(--cloo-color-danger)]"
														aria-label={$i18n.t('Remove')}
														on:click={() => removePassExample(index)}
													>
														<XMark className="size-3.5" strokeWidth="2" />
													</button>
												</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>

							<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

							<!-- Block Examples -->
							<div class="flex flex-col sm:flex-row sm:items-start gap-2 w-full">
								<div
									class="sm:w-[190px] shrink-0 sm:pt-1.5 text-sm font-semibold text-[var(--cloo-text-primary)]"
								>
									{$i18n.t('Block Examples')}
								</div>
								<div class="flex-1 min-w-0 flex flex-col gap-2">
									<div class="flex gap-2 items-center">
										<div class="flex-1 min-w-0">
											<Input
												bind:value={newBlockExample}
												size="md"
												placeholder={$i18n.t('Example of content that should be BLOCKED')}
											/>
										</div>
										<Button kind="outlined" size="md" on:click={addBlockExample}>
											<Plus slot="prefix" className="size-3.5" strokeWidth="2" />
											{$i18n.t('Add')}
										</Button>
									</div>
									{#if llmJudgeBlockExamples.length > 0}
										<div class="flex flex-col gap-1">
											{#each llmJudgeBlockExamples as example, index}
												<div
													class="flex items-center justify-between gap-2 p-1.5 rounded-[var(--cloo-radius-default)] bg-red-50 dark:bg-red-900/20 text-xs"
												>
													<span class="min-w-0 truncate">{example}</span>
													<button
														type="button"
														class="shrink-0 text-[var(--cloo-text-muted)] hover:text-[var(--cloo-color-danger)]"
														aria-label={$i18n.t('Remove')}
														on:click={() => removeBlockExample(index)}
													>
														<XMark className="size-3.5" strokeWidth="2" />
													</button>
												</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						</div>
					{/if}
				</Card>
			</div>
		</div>
	</div>
{:else}
	<div class="flex justify-center items-center h-64">
		<Spinner />
	</div>
{/if}
