<script lang="ts">
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import { getContext, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let admin = false;

	export let params = {
		// Advanced
		stream_response: null, // Set stream responses for this model individually
		function_calling: null,
		seed: null,
		stop: null,
		temperature: null,
		reasoning_effort: null,
		logit_bias: null,
		frequency_penalty: null,
		repeat_last_n: null,
		mirostat: null,
		mirostat_eta: null,
		mirostat_tau: null,
		top_k: null,
		top_p: null,
		min_p: null,
		tfs_z: null,
		num_ctx: null,
		num_batch: null,
		num_keep: null,
		max_tokens: null,
		use_mmap: null,
		use_mlock: null,
		num_thread: null,
		num_gpu: null,
		template: null
	};

	let customFieldName = '';
	let customFieldValue = '';

	$: if (params) {
		dispatch('change', params);
	}
</script>

<div class=" space-y-1 text-xs pb-safe-bottom">
	<div>
		<Tooltip
			content={$i18n.t(
				'When enabled, the model will respond to each chat message in real-time, generating a response as soon as the user sends a message. This mode is useful for live chat applications, but may impact performance on slower hardware.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Stream Chat Response')} size="md">
				<svelte:fragment slot="right">
					<div class="w-[10rem]">
						<Selector
							value={params.stream_response === null
								? 'default'
								: params.stream_response
									? 'on'
									: 'off'}
							items={[
								{ value: 'default', label: $i18n.t('Default') },
								{ value: 'on', label: $i18n.t('On') },
								{ value: 'off', label: $i18n.t('Off') }
							]}
							size="sm"
							searchEnabled={false}
							portal="body"
							contentClassName="z-[10000]"
							on:change={(e) => {
								params.stream_response =
									e.detail.value === 'default' ? null : e.detail.value === 'on';
							}}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>
		</Tooltip>
	</div>

	<div>
		<Tooltip
			content={$i18n.t(
				'Default mode works with a wider range of models by calling tools once before execution. Native mode leverages the model’s built-in tool-calling capabilities, but requires the model to inherently support this feature.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Function Calling')} size="md">
				<svelte:fragment slot="right">
					<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={params.function_calling === null || params.function_calling === undefined ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.function_calling = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={params.function_calling === 'native' ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.function_calling = 'native'; }}
						>
							{$i18n.t('Native')}
						</Button>
					</div>
				</svelte:fragment>
			</LabelBase>
		</Tooltip>
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Sets the random number seed to use for generation. Setting this to a specific number will make the model generate the same text for the same prompt.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Seed')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.seed ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.seed = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.seed ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.seed = 0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.seed ?? null) !== null}
			<Input
			type="number"
			bind:value={params.seed}
			placeholder={$i18n.t('Enter Seed')}
			size="md"
			autocomplete="off"
		/>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Sets the stop sequences to use. When this pattern is encountered, the LLM will stop generating text and return. Multiple stop patterns may be set by specifying multiple separate stop parameters in a modelfile.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Stop Sequence')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.stop ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.stop = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.stop ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.stop = ''; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.stop ?? null) !== null}
			<Input
			bind:value={params.stop}
			placeholder={$i18n.t('Enter stop sequence')}
			size="md"
			autocomplete="off"
		/>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'The temperature of the model. Increasing the temperature will make the model answer more creatively.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Temperature')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.temperature ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.temperature = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.temperature ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.temperature = 0.8; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.temperature ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.temperature}</span>
				</div>
				<input
					type="range"
					min="0"
					max="2"
					step="0.05"
					bind:value={params.temperature}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Constrains effort on reasoning for reasoning models. Only applicable to reasoning models from specific providers that support reasoning effort.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Reasoning Effort')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.reasoning_effort ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.reasoning_effort = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.reasoning_effort ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.reasoning_effort = 'medium'; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.reasoning_effort ?? null) !== null}
			<Input
			bind:value={params.reasoning_effort}
			placeholder={$i18n.t('Enter reasoning effort')}
			size="md"
			autocomplete="off"
		/>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Boosting or penalizing specific tokens for constrained responses. Bias values will be clamped between -100 and 100 (inclusive). (Default: none)'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Logit Bias')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.logit_bias ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.logit_bias = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.logit_bias ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.logit_bias = ''; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.logit_bias ?? null) !== null}
			<Input
			bind:value={params.logit_bias}
			placeholder={$i18n.t(
							'Enter comma-seperated "token:bias_value" pairs (example: 5432:100, 413:-100)'
						)}
			size="md"
			autocomplete="off"
		/>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t('Enable Mirostat sampling for controlling perplexity.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Mirostat')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.mirostat ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.mirostat ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat = 0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.mirostat ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.mirostat}</span>
				</div>
				<input
					type="range"
					min="0"
					max="2"
					step="1"
					bind:value={params.mirostat}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Influences how quickly the algorithm responds to feedback from the generated text. A lower learning rate will result in slower adjustments, while a higher learning rate will make the algorithm more responsive.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Mirostat Eta')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.mirostat_eta ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat_eta = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.mirostat_eta ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat_eta = 0.1; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.mirostat_eta ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.mirostat_eta}</span>
				</div>
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					bind:value={params.mirostat_eta}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>1</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Controls the balance between coherence and diversity of the output. A lower value will result in more focused and coherent text.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Mirostat Tau')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.mirostat_tau ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat_tau = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.mirostat_tau ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.mirostat_tau = 5.0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.mirostat_tau ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.mirostat_tau}</span>
				</div>
				<input
					type="range"
					min="0"
					max="10"
					step="0.5"
					bind:value={params.mirostat_tau}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>10</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Reduces the probability of generating nonsense. A higher value (e.g. 100) will give more diverse answers, while a lower value (e.g. 10) will be more conservative.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Top K')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.top_k ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.top_k = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.top_k ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.top_k = 40; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.top_k ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.top_k}</span>
				</div>
				<input
					type="range"
					min="0"
					max="1000"
					step="0.5"
					bind:value={params.top_k}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>1000</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Works together with top-k. A higher value (e.g., 0.95) will lead to more diverse text, while a lower value (e.g., 0.5) will generate more focused and conservative text.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Top P')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.top_p ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.top_p = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.top_p ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.top_p = 0.9; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.top_p ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.top_p}</span>
				</div>
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					bind:value={params.top_p}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>1</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Alternative to the top_p, and aims to ensure a balance of quality and variety. The parameter p represents the minimum probability for a token to be considered, relative to the probability of the most likely token. For example, with p=0.05 and the most likely token having a probability of 0.9, logits with a value less than 0.045 are filtered out.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Min P')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.min_p ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.min_p = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.min_p ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.min_p = 0.0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.min_p ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.min_p}</span>
				</div>
				<input
					type="range"
					min="0"
					max="1"
					step="0.05"
					bind:value={params.min_p}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>1</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Sets a scaling bias against tokens to penalize repetitions, based on how many times they have appeared. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 0.9) will be more lenient. At 0, it is disabled.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Frequency Penalty')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.frequency_penalty ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.frequency_penalty = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.frequency_penalty ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.frequency_penalty = 1.1; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.frequency_penalty ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.frequency_penalty}</span>
				</div>
				<input
					type="range"
					min="-2"
					max="2"
					step="0.05"
					bind:value={params.frequency_penalty}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-2</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Sets a flat bias against tokens that have appeared at least once. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 0.9) will be more lenient. At 0, it is disabled.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Presence Penalty')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.presence_penalty ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.presence_penalty = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.presence_penalty ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.presence_penalty = 0.0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.presence_penalty ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.presence_penalty}</span>
				</div>
				<input
					type="range"
					min="-2"
					max="2"
					step="0.05"
					bind:value={params.presence_penalty}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-2</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t('Sets how far back for the model to look back to prevent repetition.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Repeat Last N')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.repeat_last_n ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.repeat_last_n = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.repeat_last_n ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.repeat_last_n = 64; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.repeat_last_n ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.repeat_last_n}</span>
				</div>
				<input
					type="range"
					min="-1"
					max="128"
					step="1"
					bind:value={params.repeat_last_n}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-1</span>
					<span>128</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher value (e.g., 2.0) will reduce the impact more, while a value of 1.0 disables this setting.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Tfs Z')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.tfs_z ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.tfs_z = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.tfs_z ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.tfs_z = 1; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.tfs_z ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.tfs_z}</span>
				</div>
				<input
					type="range"
					min="0"
					max="2"
					step="0.05"
					bind:value={params.tfs_z}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'This option controls how many tokens are preserved when refreshing the context. For example, if set to 2, the last 2 tokens of the conversation context will be retained. Preserving context can help maintain the continuity of a conversation, but it may reduce the ability to respond to new topics.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Tokens To Keep On Context Refresh (num_keep)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.num_keep ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_keep = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.num_keep ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_keep = 24; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.num_keep ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.num_keep}</span>
				</div>
				<input
					type="range"
					min="-1"
					max="10240000"
					step="1"
					bind:value={params.num_keep}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-1</span>
					<span>10240000</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'This option sets the maximum number of tokens the model can generate in its response. Increasing this limit allows the model to provide longer answers, but it may also increase the likelihood of unhelpful or irrelevant content being generated.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Max Tokens (num_predict)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.max_tokens ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.max_tokens = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.max_tokens ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.max_tokens = 128; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.max_tokens ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.max_tokens}</span>
				</div>
				<input
					type="range"
					min="-2"
					max="131072"
					step="1"
					bind:value={params.max_tokens}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-2</span>
					<span>131072</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'Control the repetition of token sequences in the generated text. A higher value (e.g., 1.5) will penalize repetitions more strongly, while a lower value (e.g., 1.1) will be more lenient. At 1, it is disabled.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Repeat Penalty (Ollama)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.repeat_penalty ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.repeat_penalty = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.repeat_penalty ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.repeat_penalty = 1.1; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.repeat_penalty ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.repeat_penalty}</span>
				</div>
				<input
					type="range"
					min="-2"
					max="2"
					step="0.05"
					bind:value={params.repeat_penalty}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-2</span>
					<span>2</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t('Sets the size of the context window used to generate the next token.')}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={`${$i18n.t('Context Length')} ${$i18n.t('(Ollama)')}`} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.num_ctx ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_ctx = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.num_ctx ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_ctx = 2048; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.num_ctx ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.num_ctx}</span>
				</div>
				<input
					type="range"
					min="-1"
					max="10240000"
					step="1"
					bind:value={params.num_ctx}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>-1</span>
					<span>10240000</span>
				</div>
			</div>
		{/if}
	</div>

	<div class=" py-0.5 w-full justify-between">
		<Tooltip
			content={$i18n.t(
				'The batch size determines how many text requests are processed together at once. A higher batch size can increase the performance and speed of the model, but it also requires more memory.'
			)}
			placement="top-start"
			className="inline-tooltip"
		>
			<LabelBase label={$i18n.t('Batch Size (num_batch)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.num_batch ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_batch = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.num_batch ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_batch = 512; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
		</Tooltip>

		{#if (params?.num_batch ?? null) !== null}
			<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.num_batch}</span>
				</div>
				<input
					type="range"
					min="256"
					max="8192"
					step="256"
					bind:value={params.num_batch}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>256</span>
					<span>8192</span>
				</div>
			</div>
		{/if}
	</div>

	{#if admin}
		<div class=" py-0.5 w-full justify-between">
			<Tooltip
				content={$i18n.t(
					'Enable Memory Mapping (mmap) to load model data. This option allows the system to use disk storage as an extension of RAM by treating disk files as if they were in RAM. This can improve model performance by allowing for faster data access. However, it may not work correctly with all systems and can consume a significant amount of disk space.'
				)}
				placement="top-start"
				className="inline-tooltip"
			>
				<LabelBase label={$i18n.t('use_mmap (Ollama)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.use_mmap ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.use_mmap = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.use_mmap ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.use_mmap = true; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
			</Tooltip>

			{#if (params?.use_mmap ?? null) !== null}
				<div class="flex justify-between items-center mt-1">
					<div class="text-xs text-gray-500">
						{params.use_mmap ? 'Enabled' : 'Disabled'}
					</div>
					<div class=" pr-2">
						<Switch bind:state={params.use_mmap} />
					</div>
				</div>
			{/if}
		</div>

		<div class=" py-0.5 w-full justify-between">
			<Tooltip
				content={$i18n.t(
					"Enable Memory Locking (mlock) to prevent model data from being swapped out of RAM. This option locks the model's working set of pages into RAM, ensuring that they will not be swapped out to disk. This can help maintain performance by avoiding page faults and ensuring fast data access."
				)}
				placement="top-start"
				className="inline-tooltip"
			>
				<LabelBase label={$i18n.t('use_mlock (Ollama)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.use_mlock ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.use_mlock = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.use_mlock ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.use_mlock = true; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
			</Tooltip>

			{#if (params?.use_mlock ?? null) !== null}
				<div class="flex justify-between items-center mt-1">
					<div class="text-xs text-gray-500">
						{params.use_mlock ? 'Enabled' : 'Disabled'}
					</div>

					<div class=" pr-2">
						<Switch bind:state={params.use_mlock} />
					</div>
				</div>
			{/if}
		</div>

		<div class=" py-0.5 w-full justify-between">
			<Tooltip
				content={$i18n.t(
					'Set the number of worker threads used for computation. This option controls how many threads are used to process incoming requests concurrently. Increasing this value can improve performance under high concurrency workloads but may also consume more CPU resources.'
				)}
				placement="top-start"
				className="inline-tooltip"
			>
				<LabelBase label={$i18n.t('num_thread (Ollama)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.num_thread ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_thread = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.num_thread ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_thread = 2; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
			</Tooltip>

			{#if (params?.num_thread ?? null) !== null}
				<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.num_thread}</span>
				</div>
				<input
					type="range"
					min="1"
					max="256"
					step="1"
					bind:value={params.num_thread}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>1</span>
					<span>256</span>
				</div>
			</div>
			{/if}
		</div>

		<div class=" py-0.5 w-full justify-between">
			<Tooltip
				content={$i18n.t(
					'Set the number of layers, which will be off-loaded to GPU. Increasing this value can significantly improve performance for models that are optimized for GPU acceleration but may also consume more power and GPU resources.'
				)}
				placement="top-start"
				className="inline-tooltip"
			>
				<LabelBase label={$i18n.t('num_gpu (Ollama)')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.num_gpu ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_gpu = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.num_gpu ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.num_gpu = 0; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>
			</Tooltip>

			{#if (params?.num_gpu ?? null) !== null}
				<div class="cloo-param-slider">
				<div class="cloo-param-slider__value-row">
					<span class="cloo-param-slider__value">{params.num_gpu}</span>
				</div>
				<input
					type="range"
					min="0"
					max="256"
					step="1"
					bind:value={params.num_gpu}
					class="cloo-param-slider__range"
				/>
				<div class="cloo-param-slider__labels">
					<span>0</span>
					<span>256</span>
				</div>
			</div>
			{/if}
		</div>

		<!-- <div class=" py-0.5 w-full justify-between">
			<LabelBase label={$i18n.t('Template')} size="md">
			<svelte:fragment slot="right">
				<div class="flex items-center gap-1 w-[10rem]">
						<Button
							kind={(params?.template ?? null) === null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.template = null; }}
						>
							{$i18n.t('Default')}
						</Button>
						<Button
							kind={(params?.template ?? null) !== null ? 'filled' : 'outlined'}
							size="sm"
							className="flex-1 justify-center"
							on:click={() => { params.template = ''; }}
						>
							{$i18n.t('Custom')}
						</Button>
					</div>
			</svelte:fragment>
		</LabelBase>

			{#if (params?.template ?? null) !== null}
				<div class="flex mt-0.5 space-x-2">
					<div class=" flex-1">
						<textarea
							class="px-3 py-1.5 text-sm w-full bg-transparent border dark:border-gray-600 outline-hidden rounded-lg -mb-1"
							placeholder={$i18n.t('Write your model template content here')}
							rows="4"
							bind:value={params.template}
						/>
					</div>
				</div>
			{/if}
		</div> -->
	{/if}
</div>

<style>
	.cloo-param-slider {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
		margin-top: 0.375rem;
	}

	.cloo-param-slider__value-row {
		display: flex;
		justify-content: flex-end;
	}

	.cloo-param-slider__value {
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
		color: var(--cloo-text-primary);
		min-width: 2.5rem;
		text-align: right;
	}

	.cloo-param-slider__range {
		width: 100%;
		accent-color: var(--cloo-color-info);
		cursor: pointer;
	}

	.cloo-param-slider__labels {
		display: flex;
		justify-content: space-between;
		font-size: 0.6875rem;
		line-height: 0.875rem;
		color: var(--cloo-text-muted);
	}
</style>
