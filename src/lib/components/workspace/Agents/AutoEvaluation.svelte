<script lang="ts">
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { models } from '$lib/stores';
	import Form from '$lib/components/common/Form.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	type I18nStore = Readable<{
		t: (key: string) => string;
	}>;
	type JudgeModel = {
		id: string;
		name?: string;
		preset?: boolean;
		arena?: boolean;
	};

	const i18n = getContext<I18nStore>('i18n');

	export let autoEvaluation: {
		enabled: boolean;
		samplingRate: number;
		evaluationTypes: string[];
		judgeModelId: string | null;
	} = {
		enabled: false,
		samplingRate: 0.1,
		evaluationTypes: [],
		judgeModelId: null
	};

	const evaluationTypeOptions = [
		{
			id: 'retrieval',
			name: 'Retrieval Quality',
			description: 'Evaluates the relevance and quality of retrieved documents from knowledge base'
		},
		{
			id: 'faithfulness',
			name: 'Faithfulness',
			description:
				'Checks if the response is faithful to the retrieved context and does not hallucinate'
		},
		{
			id: 'quality',
			name: 'Response Quality',
			description: 'Evaluates overall response quality including helpfulness and accuracy'
		}
	];

	$: judgeModels = ($models as JudgeModel[]).filter((m) => !m?.preset && !(m?.arena ?? false));
	$: judgeModelItems = [
		{
			value: '',
			label: $i18n.t('Select a model...')
		},
		...judgeModels.map((model) => ({
			value: model.id,
			label: model.name || model.id
		}))
	];
	$: evaluationFormItems = evaluationTypeOptions.map((option) => ({
		id: option.id,
		label: $i18n.t(option.name),
		caption: $i18n.t(option.description),
		state: autoEvaluation.evaluationTypes.includes(option.id)
	}));

	function toggleEvaluationType(type: string) {
		if (autoEvaluation.evaluationTypes.includes(type)) {
			autoEvaluation.evaluationTypes = autoEvaluation.evaluationTypes.filter((t) => t !== type);
		} else {
			autoEvaluation.evaluationTypes = [...autoEvaluation.evaluationTypes, type];
		}
	}

	function formatSamplingRate(rate: number): string {
		return `${Math.round(rate * 100)}%`;
	}
</script>

<div class="auto-evaluation">
	<div class="auto-evaluation__header">
		<div class="auto-evaluation__heading">
			<h3>{$i18n.t('Auto Evaluation')}</h3>
			<p>{$i18n.t('Automatically evaluate model responses using LLM-as-a-Judge for quality monitoring.')}</p>
		</div>

		<div class="auto-evaluation__toggle">
			<Switch
				state={autoEvaluation.enabled}
				ariaLabel={$i18n.t('Auto Evaluation')}
				on:change={(event) => {
					autoEvaluation.enabled = event.detail;
				}}
			/>
		</div>
	</div>

	{#if autoEvaluation.enabled}
		<div class="auto-evaluation__stack">
			<div class="auto-evaluation__panel">
				<LabelBase
					label={$i18n.t('Judge Model')}
					caption={$i18n.t('The model that will perform the evaluation. Recommend using a capable model.')}
					size="md"
				>
					<svelte:fragment slot="right">
						<div class="auto-evaluation__selector-wrap">
							<Selector
								value={autoEvaluation.judgeModelId ?? ''}
								items={judgeModelItems}
								placeholder={$i18n.t('Select a model...')}
								ariaLabel={$i18n.t('Judge Model')}
								size="md"
								on:change={(event) => {
									autoEvaluation.judgeModelId = event.detail.value || null;
								}}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>

			<div class="auto-evaluation__panel">
				<div class="auto-evaluation__sampling-header">
					<LabelBase
						label={$i18n.t('Sampling Rate')}
						caption={$i18n.t('Choose how often responses should be evaluated automatically.')}
						size="md"
					/>
					<span class="auto-evaluation__sampling-value">{formatSamplingRate(autoEvaluation.samplingRate)}</span>
				</div>

				<input
					type="range"
					min="0.01"
					max="1"
					step="0.01"
					bind:value={autoEvaluation.samplingRate}
					class="auto-evaluation__range"
				/>

				<div class="auto-evaluation__range-labels">
					<span>1%</span>
					<span>50%</span>
					<span>100%</span>
				</div>
			</div>

			<Form
				label={$i18n.t('Evaluation Types')}
				caption={$i18n.t('Select which quality checks should run during evaluation.')}
				items={evaluationFormItems}
				on:change={(event) => {
					const optionId = event.detail.item.id;
					toggleEvaluationType(optionId);
				}}
			/>

			{#if autoEvaluation.evaluationTypes.length === 0}
				<div class="auto-evaluation__notice">
					{$i18n.t('Please select at least one evaluation type')}
				</div>
			{/if}

			{#if autoEvaluation.judgeModelId === null}
				<div class="auto-evaluation__notice">
					{$i18n.t('Please select a judge model')}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.auto-evaluation {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.auto-evaluation__header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.auto-evaluation__heading {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.auto-evaluation__heading h3 {
		margin: 0;
		font-size: 1rem;
		line-height: 1.5rem;
		font-weight: 600;
		color: var(--cloo-text-primary);
	}

	.auto-evaluation__heading p {
		margin: 0;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	.auto-evaluation__stack {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.auto-evaluation__panel {
		padding: 0.5rem 1.5rem;
		border: 1px solid var(--cloo-border-default);
		border-radius: 0.75rem;
		background: var(--cloo-bg-surface);
	}

	.auto-evaluation__selector-wrap {
		width: 100%;
	}

	.auto-evaluation__panel :global(.cloo-label-base__left) {
		flex: 0 0 33%;
	}

	.auto-evaluation__panel :global(.cloo-label-base__right) {
		flex: 0 0 25%;
		justify-content: flex-end;
	}

	.auto-evaluation__sampling-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.auto-evaluation__sampling-value {
		flex-shrink: 0;
		padding-top: 0.125rem;
		font-size: 0.875rem;
		line-height: 1.25rem;
		font-weight: 500;
		color: var(--cloo-text-primary);
	}

	.auto-evaluation__range {
		width: 100%;
		margin-top: 0.75rem;
		accent-color: var(--cloo-color-info);
	}

	.auto-evaluation__range-labels {
		display: flex;
		justify-content: space-between;
		margin-top: 0.25rem;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	.auto-evaluation__notice {
		padding: 0.75rem 1rem;
		border: 1px solid color-mix(in srgb, var(--token-scale-warning-300) 80%, transparent);
		border-radius: 0.75rem;
		background: color-mix(in srgb, var(--token-scale-warning-50) 92%, var(--cloo-bg-surface));
		color: var(--token-scale-warning-700);
		font-size: 0.75rem;
		line-height: 1rem;
	}

	:global(.dark) .auto-evaluation__notice {
		background: color-mix(in srgb, var(--token-scale-warning-950) 75%, var(--cloo-bg-surface));
		color: var(--token-scale-warning-300);
		border-color: color-mix(in srgb, var(--token-scale-warning-700) 70%, transparent);
	}

	@media (max-width: 767px) {
		.auto-evaluation__header,
		.auto-evaluation__sampling-header {
			flex-direction: column;
			align-items: stretch;
		}

		.auto-evaluation__selector-wrap {
			width: 100%;
		}

		.auto-evaluation__toggle {
			align-self: flex-start;
		}
	}
</style>
