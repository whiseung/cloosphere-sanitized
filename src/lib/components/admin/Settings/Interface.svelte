<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';

	import { getBackendConfig, getTaskConfig, updateTaskConfig } from '$lib/apis';
	import { setDefaultPromptSuggestions } from '$lib/apis/configs';
	import { config, models, settings, user } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext } from 'svelte';

	import { banners as _banners } from '$lib/stores';
	import type { Banner } from '$lib/types';

	import { getBanners, setBanners } from '$lib/apis/configs';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	let taskConfig = {
		TASK_MODEL: '',
		TASK_MODEL_EXTERNAL: '',
		ENABLE_TITLE_GENERATION: true,
		TITLE_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_AUTOCOMPLETE_GENERATION: true,
		AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH: -1,
		TAGS_GENERATION_PROMPT_TEMPLATE: '',
		ENABLE_TAGS_GENERATION: true,
		ENABLE_FOLLOW_UP_GENERATION: false,
		FOLLOW_UP_GENERATION_PROMPT_TEMPLATE: ''
	};

	let promptSuggestions = [];
	let banners: Banner[] = [];

	$: localModelOptions = [
		{ value: '', label: $i18n.t('Current Model') },
		...$models
			.filter((m) => m.owned_by === 'ollama')
			.map((m) => ({ value: m.id, label: m.name }))
	];

	$: externalModelOptions = [
		{ value: '', label: $i18n.t('Current Model') },
		...$models.map((m) => ({ value: m.id, label: m.name }))
	];

	$: bannerTypeOptions = [
		{ value: 'info', label: $i18n.t('Info') },
		{ value: 'warning', label: $i18n.t('Warning') },
		{ value: 'error', label: $i18n.t('Error') },
		{ value: 'success', label: $i18n.t('Success') }
	];

	const updateInterfaceHandler = async () => {
		taskConfig = await updateTaskConfig(localStorage.token, taskConfig);

		promptSuggestions = await setDefaultPromptSuggestions(localStorage.token, promptSuggestions);
		await updateBanners();

		await config.set(await getBackendConfig());
	};

	onMount(async () => {
		taskConfig = await getTaskConfig(localStorage.token);

		promptSuggestions = $config?.default_prompt_suggestions ?? [];
		banners = await getBanners(localStorage.token);
	});

	const updateBanners = async () => {
		_banners.set(await setBanners(localStorage.token, banners));
	};
</script>

{#if taskConfig}
	<form
		class="flex flex-col h-full justify-between space-y-3 text-sm"
		on:submit|preventDefault={() => {
			updateInterfaceHandler();
			dispatch('save');
		}}
	>
		<div class="  overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div class="mb-3.5">
				<div class=" mb-2.5 text-base font-medium">{$i18n.t('Tasks')}</div>

				<hr class=" border-gray-100 dark:border-gray-850 my-2" />

				<LabelBase
					label={$i18n.t('Set Task Model')}
					caption={$i18n.t(
						'A task model is used when performing tasks such as generating titles for chats and web search queries'
					)}
					size="sm"
				/>

				<div class=" mb-2.5 flex w-full gap-2 mt-1.5">
					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('Local Models')}</div>
						<Selector
							value={taskConfig.TASK_MODEL ?? ''}
							items={localModelOptions}
							placeholder={$i18n.t('Select a model')}
							size="sm"
							on:change={(e) => {
								taskConfig.TASK_MODEL = e.detail.value;
							}}
						/>
					</div>

					<div class="flex-1">
						<div class=" text-xs mb-1">{$i18n.t('External Models')}</div>
						<Selector
							value={taskConfig.TASK_MODEL_EXTERNAL ?? ''}
							items={externalModelOptions}
							placeholder={$i18n.t('Select a model')}
							size="sm"
							on:change={(e) => {
								taskConfig.TASK_MODEL_EXTERNAL = e.detail.value;
							}}
						/>
					</div>
				</div>

				<div class="mb-2.5">
					<LabelBase label={$i18n.t('Title Generation')} size="sm">
						<svelte:fragment slot="right">
							<Switch bind:state={taskConfig.ENABLE_TITLE_GENERATION} />
						</svelte:fragment>
					</LabelBase>
				</div>

				{#if taskConfig.ENABLE_TITLE_GENERATION}
					<div class="mb-2.5">
						<Textarea
							bind:value={taskConfig.TITLE_GENERATION_PROMPT_TEMPLATE}
							label={$i18n.t('Title Generation Prompt')}
							caption={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placeholder={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							size="sm"
						/>
					</div>
				{/if}

				<div class="mb-2.5">
					<LabelBase label={$i18n.t('Tags Generation')} size="sm">
						<svelte:fragment slot="right">
							<Switch bind:state={taskConfig.ENABLE_TAGS_GENERATION} />
						</svelte:fragment>
					</LabelBase>
				</div>

				{#if taskConfig.ENABLE_TAGS_GENERATION}
					<div class="mb-2.5">
						<Textarea
							bind:value={taskConfig.TAGS_GENERATION_PROMPT_TEMPLATE}
							label={$i18n.t('Tags Generation Prompt')}
							caption={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placeholder={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							size="sm"
						/>
					</div>
				{/if}

				<div class="mb-2.5">
					<LabelBase label={$i18n.t('Follow-Up Generation')} size="sm">
						<svelte:fragment slot="right">
							<Switch bind:state={taskConfig.ENABLE_FOLLOW_UP_GENERATION} />
						</svelte:fragment>
					</LabelBase>
				</div>

				{#if taskConfig.ENABLE_FOLLOW_UP_GENERATION}
					<div class="mb-2.5">
						<Textarea
							bind:value={taskConfig.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE}
							label={$i18n.t('Follow-Up Generation Prompt')}
							caption={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							placeholder={$i18n.t('Leave empty to use the default prompt, or enter a custom prompt')}
							size="sm"
						/>
					</div>
				{/if}

				<div class="mb-2.5">
					<LabelBase
						label={$i18n.t('Autocomplete Generation')}
						caption={$i18n.t('Enable autocomplete generation for chat messages')}
						size="sm"
					>
						<svelte:fragment slot="right">
							<Switch bind:state={taskConfig.ENABLE_AUTOCOMPLETE_GENERATION} />
						</svelte:fragment>
					</LabelBase>
				</div>

				{#if taskConfig.ENABLE_AUTOCOMPLETE_GENERATION}
					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium">
							{$i18n.t('Autocomplete Generation Input Max Length')}
						</div>

						<Tooltip
							content={$i18n.t('Character limit for autocomplete generation input')}
							placement="top-start"
						>
							<input
								class="w-full outline-hidden bg-transparent"
								bind:value={taskConfig.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH}
								placeholder={$i18n.t('-1 for no limit, or a positive integer for a specific limit')}
							/>
						</Tooltip>
					</div>
				{/if}
			</div>

			<div class="mb-3.5">
				<div class=" mb-2.5 text-base font-medium">{$i18n.t('UI')}</div>

				<hr class=" border-gray-100 dark:border-gray-850 my-2" />

				<div class="  {banners.length > 0 ? ' mb-3' : ''}">
					<div class="mb-2.5 flex w-full justify-between items-center">
						<div class=" self-center text-sm font-semibold">
							{$i18n.t('Banners')}
						</div>

						<Button
							kind="text"
							size="sm"
							type="button"
							on:click={() => {
								if (banners.length === 0 || banners.at(-1).content !== '') {
									banners = [
										...banners,
										{
											id: uuidv4(),
											type: '',
											title: '',
											content: '',
											dismissible: true,
											timestamp: Math.floor(Date.now() / 1000)
										}
									];
								}
							}}
						>
							<Plus className="size-4" />
						</Button>
					</div>

					<div class=" flex flex-col space-y-1.5">
						{#each banners as banner, bannerIdx}
							<div class="flex gap-2 items-center">
								<div class="w-28">
									<Selector
										value={banner.type}
										items={bannerTypeOptions}
										placeholder={$i18n.t('Type')}
										size="sm"
										searchEnabled={false}
										on:change={(e) => {
											banner.type = e.detail.value;
										}}
									/>
								</div>

								<div class="flex-1">
									<Input
										bind:value={banner.content}
										placeholder={$i18n.t('Content')}
										size="sm"
									/>
								</div>

								<Tooltip content={$i18n.t('Dismissible')} className="flex h-fit items-center">
									<Switch bind:state={banner.dismissible} />
								</Tooltip>

								<Button
									kind="text"
									size="sm"
									status="error"
									type="button"
									on:click={() => {
										banners.splice(bannerIdx, 1);
										banners = banners;
									}}
								>
									<XMark className="size-4" />
								</Button>
							</div>
						{/each}
					</div>
				</div>

				{#if $user?.role === 'admin'}
					<div class=" space-y-3">
						<div class="flex w-full justify-between items-center mb-2">
							<div class=" self-center text-sm font-semibold">
								{$i18n.t('Default Prompt Suggestions')}
							</div>

							<Button
								kind="text"
								size="sm"
								type="button"
								on:click={() => {
									if (promptSuggestions.length === 0 || promptSuggestions.at(-1).content !== '') {
										promptSuggestions = [...promptSuggestions, { content: '', title: ['', ''] }];
									}
								}}
							>
								<Plus className="size-4" />
							</Button>
						</div>
						<div class="grid lg:grid-cols-2 flex-col gap-1.5">
							{#each promptSuggestions as prompt, promptIdx}
								<div
									class=" flex border border-gray-100 dark:border-none dark:bg-gray-850 rounded-xl py-1.5 pr-1"
								>
									<div class="flex flex-col flex-1 pl-1 gap-1.5">
										<div class="flex gap-1.5">
											<div class="flex-1">
												<Input
													bind:value={prompt.title[0]}
													placeholder={$i18n.t('Title (e.g. Tell me a fun fact)')}
													size="sm"
												/>
											</div>
											<div class="flex-1">
												<Input
													bind:value={prompt.title[1]}
													placeholder={$i18n.t('Subtitle (e.g. about the Roman Empire)')}
													size="sm"
												/>
											</div>
										</div>

										<Textarea
											bind:value={prompt.content}
											placeholder={$i18n.t(
												'Prompt (e.g. Tell me a fun fact about the Roman Empire)'
											)}
											rows={3}
											size="sm"
										/>
									</div>

									<div class="flex items-start pt-1">
										<Button
											kind="text"
											size="sm"
											status="error"
											type="button"
											on:click={() => {
												promptSuggestions.splice(promptIdx, 1);
												promptSuggestions = promptSuggestions;
											}}
										>
											<XMark className="size-4" />
										</Button>
									</div>
								</div>
							{/each}
						</div>

						{#if promptSuggestions.length > 0}
							<div class="text-xs text-left w-full mt-2">
								{$i18n.t('Adjusting these settings will apply changes universally to all users.')}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>

	<div class="flex justify-end text-sm font-medium">
		<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
	</form>
{/if}
