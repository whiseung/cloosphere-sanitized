<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';

	import {
		startGlossaryExtractJob,
		countGlossaryValues,
		extractErrorMessage
	} from '$lib/apis/glossary';
	import { getDbSpheres } from '$lib/apis/dbsphere';
	import { getDbSphereTables, getDbSphereColumns } from '$lib/apis/knowledge-graph';
	import type { DbSphereTableInfo, DbSphereColumnInfo } from '$lib/apis/knowledge-graph';
	import { getModels } from '$lib/apis';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let glossaryId: string = '';
	export let aiModelId: string = '';

	// Form state — stays local. Modal close = component unmount = state reset.
	let extractDbId = '';
	let extractTableName = '';
	let extractColumnName = '';
	let extractSynonymColumn = '';
	let extractDescriptionColumn = '';
	let extractContextColumns: string[] = [];
	let extractCategory = '';
	let extractEnrichLlm = true;
	let extractLlmSynonyms = true;
	let extractLlmDescription = true;
	let extractLlmExample = true;
	let extractModelId = '';
	let extractBatchSize = '10';
	let extractConcurrency = '8';
	let extractSynonymInstructions = '';
	let extractDescriptionInstructions = '';
	let extractExampleInstructions = '';

	let extractTables: DbSphereTableInfo[] = [];
	let extractColumns: DbSphereColumnInfo[] = [];
	let extractTablesLoading = false;
	let extractColumnsLoading = false;
	let extracting = false;
	let extractCounting = false;
	let extractCountResult = 0;

	let allDbspheres: { id: string; name: string }[] = [];
	let modelItems: { value: string; label: string }[] = [];

	const init = async () => {
		try {
			const dbs = await getDbSpheres(localStorage.token);
			allDbspheres = dbs.map((d: any) => ({ id: d.id, name: d.name }));
		} catch {
			allDbspheres = [];
		}
		try {
			const models = await getModels(localStorage.token);
			// 베이스 모델만 — 에이전트(base_model_id 보유) / preset / arena 제외
			modelItems = models
				.filter((m: any) => !m.base_model_id && !m.preset && !(m.arena ?? false))
				.map((m: any) => ({ value: m.id, label: m.name || m.id }));
			if (!extractModelId) {
				if (aiModelId) extractModelId = aiModelId;
				else if (modelItems.length > 0) extractModelId = modelItems[0].value;
			}
		} catch {
			modelItems = [];
		}
	};

	void init();

	const loadExtractTables = async (dbId: string) => {
		if (!dbId) {
			extractTables = [];
			return;
		}
		extractTablesLoading = true;
		try {
			extractTables = await getDbSphereTables(localStorage.token, dbId);
		} catch {
			extractTables = [];
		} finally {
			extractTablesLoading = false;
		}
	};

	const loadExtractColumns = async (dbId: string, table: string) => {
		if (!dbId || !table) {
			extractColumns = [];
			return;
		}
		extractColumnsLoading = true;
		try {
			extractColumns = await getDbSphereColumns(localStorage.token, dbId, table);
		} catch {
			extractColumns = [];
		} finally {
			extractColumnsLoading = false;
		}
	};

	const buildCustomInstructions = (): string => {
		const parts: string[] = [];
		if (extractSynonymInstructions.trim()) {
			parts.push(`[동의어 생성 지시사항]\n${extractSynonymInstructions.trim()}`);
		}
		if (extractDescriptionInstructions.trim()) {
			parts.push(`[설명 생성 지시사항]\n${extractDescriptionInstructions.trim()}`);
		}
		if (extractExampleInstructions.trim()) {
			parts.push(`[예문 생성 지시사항]\n${extractExampleInstructions.trim()}`);
		}
		return parts.join('\n\n');
	};

	const doExtractCount = async () => {
		if (!glossaryId || !extractDbId || !extractTableName || !extractColumnName) return;
		extractCounting = true;
		try {
			const result = await countGlossaryValues(localStorage.token, glossaryId, {
				dbsphere_id: extractDbId,
				table_name: extractTableName,
				column_name: extractColumnName
			});
			extractCountResult = result.distinct_count;
			const ok = confirm(
				$i18n.t('{{count}} distinct values found. Continue?', { count: extractCountResult })
			);
			if (ok) {
				await doExtractStart();
			}
		} catch (e: any) {
			toast.error(extractErrorMessage(e));
		} finally {
			extractCounting = false;
		}
	};

	const doExtractStart = async () => {
		if (!glossaryId || !extractDbId || !extractTableName || !extractColumnName) return;
		const trimmedCategory = extractCategory.trim();
		if (!trimmedCategory) {
			toast.error($i18n.t('Category is required.'));
			return;
		}
		extracting = true;
		try {
			const llmFields: string[] = [];
			if (extractEnrichLlm) {
				if (extractLlmSynonyms && !extractSynonymColumn) llmFields.push('synonyms');
				if (extractLlmDescription && !extractDescriptionColumn) llmFields.push('description');
				if (extractLlmExample) llmFields.push('example');
			}
			const res = await startGlossaryExtractJob(localStorage.token, glossaryId, {
				dbsphere_id: extractDbId,
				table_name: extractTableName,
				column_name: extractColumnName,
				synonym_column: extractSynonymColumn || undefined,
				description_column: extractDescriptionColumn || undefined,
				context_columns: extractContextColumns.length > 0 ? extractContextColumns : undefined,
				model_id: extractEnrichLlm && llmFields.length > 0 ? extractModelId : undefined,
				generate_enrichment: extractEnrichLlm && llmFields.length > 0,
				llm_fields: llmFields.length > 0 ? llmFields : undefined,
				batch_size: parseInt(extractBatchSize) || 10,
				llm_concurrency: parseInt(extractConcurrency) || 8,
				category: trimmedCategory,
				custom_instructions: buildCustomInstructions() || undefined
			});
			toast.success(
				$i18n.t('Extraction started. We will let you know when it is done.')
			);
			// Hand the job back to the parent so it can start polling.
			// Parent owns extractJob state + polling timer (critique H1/H2).
			dispatch('job-started', res);
		} catch (e: any) {
			toast.error(extractErrorMessage(e));
		} finally {
			extracting = false;
		}
	};

	const handleBack = () => {
		dispatch('back');
	};

	$: contextSelectableColumns = extractColumns.filter(
		(c) =>
			c.name !== extractColumnName &&
			c.name !== extractSynonymColumn &&
			c.name !== extractDescriptionColumn
	);
</script>

<div class="px-6 py-5 max-h-[70vh] overflow-y-auto">
	<div class="flex items-center justify-between mb-3">
		<Button kind="text" size="sm" on:click={handleBack}>
			<svelte:fragment slot="prefix">
				<ArrowLeft className="size-3.5" strokeWidth="2" />
			</svelte:fragment>
			{$i18n.t('Back')}
		</Button>
		<div class="text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Import from database')}
		</div>
	</div>

	<div class="flex flex-col gap-[var(--cloo-space-3)]">
		<div>
			<LabelBase label={$i18n.t('Database')} />
			<Selector
				value={extractDbId}
				items={allDbspheres.map((d) => ({ value: d.id, label: d.name }))}
				placeholder={$i18n.t('Select database')}
				searchEnabled
				size="md"
				portal="body"
				contentClassName="z-[10000]"
				on:change={(e) => {
					extractDbId = e.detail.value;
					extractTableName = '';
					extractColumnName = '';
					extractSynonymColumn = '';
					extractDescriptionColumn = '';
					extractContextColumns = [];
					extractTables = [];
					extractColumns = [];
					loadExtractTables(e.detail.value);
				}}
			/>
		</div>

		{#if extractTablesLoading}
			<div class="text-xs text-[var(--cloo-text-muted)] italic py-2">
				{$i18n.t('Loading...')}
			</div>
		{:else}
			<div>
				<LabelBase label={$i18n.t('Table')} />
				<Selector
					value={extractTableName}
					items={extractTables.map((t) => ({ value: t.table_name, label: t.table_name }))}
					placeholder={$i18n.t('Select table')}
					searchEnabled
					size="md"
					portal="body"
					contentClassName="z-[10000]"
					disabled={extractTables.length === 0}
					on:change={(e) => {
						extractTableName = e.detail.value;
						extractColumnName = '';
						extractSynonymColumn = '';
						extractDescriptionColumn = '';
						loadExtractColumns(extractDbId, e.detail.value);
					}}
				/>
			</div>
		{/if}

		{#if extractColumnsLoading}
			<div class="text-xs text-[var(--cloo-text-muted)] italic py-2">
				{$i18n.t('Loading...')}
			</div>
		{:else}
			<div>
				<LabelBase label={$i18n.t('Term column')} />
				<Selector
					value={extractColumnName}
					items={extractColumns.map((c) => ({
						value: c.name,
						label: `${c.name} (${c.data_type})`
					}))}
					placeholder={$i18n.t('Select column')}
					searchEnabled
					size="md"
					portal="body"
					contentClassName="z-[10000]"
					disabled={extractColumns.length === 0}
					on:change={(e) => {
						extractColumnName = e.detail.value;
						extractSynonymColumn = '';
						extractDescriptionColumn = '';
						extractContextColumns = extractContextColumns.filter((n) => n !== e.detail.value);
					}}
				/>
			</div>
		{/if}

		{#if extractColumns.length > 0 && extractColumnName}
			<div>
				<LabelBase
					label={$i18n.t('Synonym column')}
					caption={$i18n.t('Column containing aliases or alternate names')}
				/>
				<Selector
					value={extractSynonymColumn}
					items={[
						{ value: '', label: `— ${$i18n.t('None')} —` },
						...extractColumns
							.filter((c) => c.name !== extractColumnName)
							.map((c) => ({ value: c.name, label: `${c.name} (${c.data_type})` }))
					]}
					size="md"
					portal="body"
					contentClassName="z-[10000]"
					on:change={(e) => {
						extractSynonymColumn = e.detail.value;
						if (e.detail.value)
							extractContextColumns = extractContextColumns.filter((n) => n !== e.detail.value);
					}}
				/>
			</div>
			<div>
				<LabelBase
					label={$i18n.t('Description column')}
					caption={$i18n.t('Column containing definitions or descriptions')}
				/>
				<Selector
					value={extractDescriptionColumn}
					items={[
						{ value: '', label: `— ${$i18n.t('None')} —` },
						...extractColumns
							.filter((c) => c.name !== extractColumnName && c.name !== extractSynonymColumn)
							.map((c) => ({ value: c.name, label: `${c.name} (${c.data_type})` }))
					]}
					size="md"
					portal="body"
					contentClassName="z-[10000]"
					on:change={(e) => {
						extractDescriptionColumn = e.detail.value;
						if (e.detail.value)
							extractContextColumns = extractContextColumns.filter((n) => n !== e.detail.value);
					}}
				/>
			</div>
			<div>
				<LabelBase
					label={$i18n.t('Reference columns (LLM hint)')}
					caption={$i18n.t(
						'Same-row column values passed to the LLM as context. Not stored in entries.'
					)}
				/>
				{#if contextSelectableColumns.length === 0}
					<div class="text-xs text-[var(--cloo-text-muted)] italic px-1 py-2">
						{$i18n.t('No additional columns available.')}
					</div>
				{:else}
					<div
						class="flex flex-wrap gap-x-4 gap-y-2 p-2 rounded-[var(--cloo-radius-default)] border border-[var(--cloo-border-subtle)] bg-[var(--cloo-bg-surface)]"
					>
						{#each contextSelectableColumns as col (col.name)}
							<label
								class="flex items-center gap-[var(--cloo-space-2)] text-sm text-[var(--cloo-text-default)] cursor-pointer"
							>
								<Checkbox
									state={extractContextColumns.includes(col.name) ? 'checked' : 'unchecked'}
									on:change={(e) => {
										if (e.detail === 'checked') {
											extractContextColumns = [...extractContextColumns, col.name];
										} else {
											extractContextColumns = extractContextColumns.filter((n) => n !== col.name);
										}
									}}
								/>
								<span>{col.name}</span>
								<span class="text-xs text-[var(--cloo-text-muted)]">({col.data_type})</span>
							</label>
						{/each}
					</div>
				{/if}
			</div>
		{/if}

		<Input
			bind:value={extractCategory}
			label={$i18n.t('Category')}
			placeholder={$i18n.t('e.g. Region, Product, Customer grade')}
			size="md"
			required
		/>

		<LabelBase label={$i18n.t('LLM enrichment')}>
			<svelte:fragment slot="right">
				<Switch bind:state={extractEnrichLlm} />
			</svelte:fragment>
		</LabelBase>

		{#if extractEnrichLlm}
			<div class="flex flex-col gap-[var(--cloo-space-3)] pl-1">
				<!-- Synonyms -->
				<div class="flex flex-col gap-[var(--cloo-space-1)]">
					<div class="flex items-center gap-[var(--cloo-space-2)]">
						<Checkbox
							state={extractLlmSynonyms && !extractSynonymColumn ? 'checked' : 'unchecked'}
							disabled={!!extractSynonymColumn}
							on:change={(e) => {
								extractLlmSynonyms = e.detail === 'checked';
							}}
						/>
						<span
							class="text-sm text-[var(--cloo-text-default)]"
							class:opacity-50={!!extractSynonymColumn}
						>
							{$i18n.t('Synonyms')}
							{#if extractSynonymColumn}
								<span class="text-xs text-[var(--cloo-text-muted)]">
									({$i18n.t('using DB column')})
								</span>
							{/if}
						</span>
					</div>
					{#if extractLlmSynonyms && !extractSynonymColumn}
						<div class="pl-6">
							<Input
								bind:value={extractSynonymInstructions}
								placeholder={$i18n.t(
									'e.g. Extract ISO 2-letter codes as synonyms for country names'
								)}
								size="sm"
							/>
						</div>
					{/if}
				</div>

				<!-- Description -->
				<div class="flex flex-col gap-[var(--cloo-space-1)]">
					<div class="flex items-center gap-[var(--cloo-space-2)]">
						<Checkbox
							state={extractLlmDescription && !extractDescriptionColumn ? 'checked' : 'unchecked'}
							disabled={!!extractDescriptionColumn}
							on:change={(e) => {
								extractLlmDescription = e.detail === 'checked';
							}}
						/>
						<span
							class="text-sm text-[var(--cloo-text-default)]"
							class:opacity-50={!!extractDescriptionColumn}
						>
							{$i18n.t('Description')}
							{#if extractDescriptionColumn}
								<span class="text-xs text-[var(--cloo-text-muted)]">
									({$i18n.t('using DB column')})
								</span>
							{/if}
						</span>
					</div>
					{#if extractLlmDescription && !extractDescriptionColumn}
						<div class="pl-6">
							<Input
								bind:value={extractDescriptionInstructions}
								placeholder={$i18n.t('e.g. Include the official definition from the standard')}
								size="sm"
							/>
						</div>
					{/if}
				</div>

				<!-- Example -->
				<div class="flex flex-col gap-[var(--cloo-space-1)]">
					<div class="flex items-center gap-[var(--cloo-space-2)]">
						<Checkbox
							state={extractLlmExample ? 'checked' : 'unchecked'}
							on:change={(e) => {
								extractLlmExample = e.detail === 'checked';
							}}
						/>
						<span class="text-sm text-[var(--cloo-text-default)]">
							{$i18n.t('Example')}
						</span>
					</div>
					{#if extractLlmExample}
						<div class="pl-6">
							<Input
								bind:value={extractExampleInstructions}
								placeholder={$i18n.t('e.g. Write examples as business report sentences')}
								size="sm"
							/>
						</div>
					{/if}
				</div>
			</div>

			<Selector
				value={extractModelId}
				items={modelItems}
				placeholder={$i18n.t('Select model')}
				searchEnabled
				size="md"
				portal="body"
				contentClassName="z-[10000]"
				on:change={(e) => (extractModelId = e.detail.value)}
			/>
			<Input
				bind:value={extractBatchSize}
				label={$i18n.t('Batch size')}
				type="number"
				placeholder="10"
				size="md"
			/>
			<Input
				bind:value={extractConcurrency}
				label={$i18n.t('Concurrent requests')}
				caption={$i18n.t('Number of batches processed in parallel. Lower if you hit rate limits.')}
				type="number"
				placeholder="8"
				size="md"
			/>
		{/if}
	</div>
</div>

<div class="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex justify-end gap-2">
	<Button kind="outlined" size="md" on:click={handleBack} disabled={extracting}>
		{$i18n.t('Cancel')}
	</Button>
	<Button
		kind="filled"
		size="md"
		loading={extractCounting || extracting}
		disabled={extractCounting || extracting || !extractDbId || !extractTableName || !extractColumnName}
		on:click={doExtractCount}
	>
		{extracting ? $i18n.t('Starting...') : $i18n.t('Extract')}
	</Button>
</div>
