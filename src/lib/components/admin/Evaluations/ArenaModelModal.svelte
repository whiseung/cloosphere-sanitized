<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	import Modal from '$lib/components/common/Modal.svelte';
	import { models } from '$lib/stores';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import PencilSolid from '$lib/components/icons/PencilSolid.svelte';
	import { toast } from 'svelte-sonner';
	import AccessControl from '$lib/components/workspace/common/AccessControl.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	export let show = false;
	export let edit = false;

	export let model = null;

	let name = '';
	let id = '';

	$: if (name) {
		generateId();
	}

	const generateId = () => {
		if (!edit) {
			id = name
				.toLowerCase()
				.replace(/[^a-z0-9]/g, '-')
				.replace(/-+/g, '-')
				.replace(/^-|-$/g, '');
		}
	};

	let profileImageUrl = '/favicon.png';
	let description = '';

	let selectedModelId = '';
	let modelIds = [];
	let filterMode = 'include';

	let accessControl: any = null;

	let imageInputElement;
	let loading = false;
	let showDeleteConfirmDialog = false;

	$: modelOptions = [
		{ value: '', label: $i18n.t('Select a model') },
		...$models
			.filter((m: any) => m?.owned_by !== 'arena')
			.map((m: any) => ({ value: m.id, label: m.name }))
	];

	const addModelHandler = () => {
		if (selectedModelId) {
			modelIds = [...modelIds, selectedModelId];
			selectedModelId = '';
		}
	};

	const submitHandler = () => {
		loading = true;

		if (!name || !id) {
			loading = false;
			toast.error($i18n.t('Name and ID are required, please fill them out'));
			return;
		}

		if (!edit) {
			if ($models.find((model) => model.name === name)) {
				loading = false;
				name = '';
				toast.error($i18n.t('Model name already exists, please choose a different one'));
				return;
			}
		}

		const model = {
			id: id,
			name: name,
			meta: {
				profile_image_url: profileImageUrl,
				description: description || null,
				model_ids: modelIds.length > 0 ? modelIds : null,
				filter_mode: modelIds.length > 0 ? (filterMode ? filterMode : null) : null,
				access_control: accessControl
			}
		};

		dispatch('submit', model);
		loading = false;
		show = false;

		name = '';
		id = '';
		profileImageUrl = '/favicon.png';
		description = '';
		modelIds = [];
		selectedModelId = '';
	};

	const initModel = () => {
		if (model) {
			name = model.name;
			id = model.id;
			profileImageUrl = model.meta.profile_image_url;
			description = model.meta.description;
			modelIds = model.meta.model_ids || [];
			filterMode = model.meta?.filter_mode ?? 'include';
			accessControl = 'access_control' in model.meta ? model.meta.access_control : null;
		}
	};

	$: if (show) {
		initModel();
	}

	onMount(() => {
		initModel();
	});
</script>

<ConfirmDialog
	bind:show={showDeleteConfirmDialog}
	on:confirm={() => {
		dispatch('delete', model);
		show = false;
	}}
/>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center font-primary">
				{#if edit}
					{$i18n.t('Edit Arena Model')}
				{:else}
					{$i18n.t('Add Arena Model')}
				{/if}
			</div>
			<Button
				kind="text"
				size="sm"
				type="button"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-5" />
			</Button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<div class="px-1">
						<div class="flex justify-center pb-3">
							<input
								bind:this={imageInputElement}
								type="file"
								hidden
								accept="image/*"
								on:change={(e) => {
									const files = e.target.files ?? [];
									let reader = new FileReader();
									reader.onload = (event) => {
										let originalImageUrl = `${event.target.result}`;

										const img = new Image();
										img.src = originalImageUrl;

										img.onload = function () {
											const canvas = document.createElement('canvas');
											const ctx = canvas.getContext('2d');

											// Calculate the aspect ratio of the image
											const aspectRatio = img.width / img.height;

											// Calculate the new width and height to fit within 250x250
											let newWidth, newHeight;
											if (aspectRatio > 1) {
												newWidth = 250 * aspectRatio;
												newHeight = 250;
											} else {
												newWidth = 250;
												newHeight = 250 / aspectRatio;
											}

											// Set the canvas size
											canvas.width = 250;
											canvas.height = 250;

											// Calculate the position to center the image
											const offsetX = (250 - newWidth) / 2;
											const offsetY = (250 - newHeight) / 2;

											// Draw the image on the canvas
											ctx.drawImage(img, offsetX, offsetY, newWidth, newHeight);

											// Get the base64 representation of the compressed image
											const compressedSrc = canvas.toDataURL('image/jpeg');

											// Display the compressed image
											profileImageUrl = compressedSrc;

											e.target.files = null;
										};
									};

									if (
										files.length > 0 &&
										['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(
											files[0]['type']
										)
									) {
										reader.readAsDataURL(files[0]);
									}
								}}
							/>

							<button
								class="relative rounded-full w-fit h-fit shrink-0"
								type="button"
								on:click={() => {
									imageInputElement.click();
								}}
							>
								<img
									src={profileImageUrl}
									class="size-16 rounded-full object-cover shrink-0"
									alt="Profile"
								/>

								<div
									class="absolute flex justify-center rounded-full bottom-0 left-0 right-0 top-0 h-full w-full overflow-hidden bg-gray-700 bg-fixed opacity-0 transition duration-300 ease-in-out hover:opacity-50"
								>
									<div class="my-auto text-white">
										<PencilSolid className="size-4" />
									</div>
								</div>
							</button>
						</div>
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={name}
									label={$i18n.t('Name')}
									placeholder={$i18n.t('Model Name')}
									size="sm"
									autocomplete="off"
									required
								/>
							</div>

							<div class="flex-1">
								<Input
									bind:value={id}
									label={$i18n.t('ID')}
									placeholder={$i18n.t('Model ID')}
									size="sm"
									autocomplete="off"
									required
									disabled={edit}
								/>
							</div>
						</div>

						<div class="mt-2">
							<Input
								bind:value={description}
								label={$i18n.t('Description')}
								placeholder={$i18n.t('Enter description')}
								size="sm"
								autocomplete="off"
							/>
						</div>

						<hr class=" border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

						<div class="my-2 -mx-2">
							<div class="px-3 py-2 bg-gray-50 dark:bg-gray-950 rounded-lg">
								<AccessControl bind:accessControl />
							</div>
						</div>

						<hr class=" border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

						<div class="flex flex-col w-full">
							<div class="mb-1 flex justify-between">
								<div class="text-xs text-gray-500">{$i18n.t('Models')}</div>

								<div>
									<button
										class=" text-xs text-gray-500"
										type="button"
										on:click={() => {
											filterMode = filterMode === 'include' ? 'exclude' : 'include';
										}}
									>
										{#if filterMode === 'include'}
											{$i18n.t('Include')}
										{:else}
											{$i18n.t('Exclude')}
										{/if}
									</button>
								</div>
							</div>

							{#if modelIds.length > 0}
								<div class="flex flex-col">
									{#each modelIds as modelId, modelIdx}
										<div class=" flex gap-2 w-full justify-between items-center">
											<div class=" text-sm flex-1 py-1 rounded-lg">
												{$models.find((model) => model.id === modelId)?.name}
											</div>
											<div class="shrink-0">
												<Button
													kind="text"
													size="sm"
													type="button"
													on:click={() => {
														modelIds = modelIds.filter((_, idx) => idx !== modelIdx);
													}}
												>
													<Minus strokeWidth="2" className="size-3.5" />
												</Button>
											</div>
										</div>
									{/each}
								</div>
							{:else}
								<div class="text-gray-500 text-xs text-center py-2">
									{$i18n.t('Leave empty to include all models or select specific models')}
								</div>
							{/if}
						</div>

						<hr class=" border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

						<div class="flex items-center gap-2">
							<div class="flex-1">
								<Selector
									value={selectedModelId}
									items={modelOptions}
									placeholder={$i18n.t('Select a model')}
									size="sm"
									on:change={(e) => {
										selectedModelId = e.detail.value;
									}}
								/>
							</div>

							<Button
								kind="text"
								size="sm"
								type="button"
								on:click={() => {
									addModelHandler();
								}}
							>
								<Plus className="size-3.5" strokeWidth="2" />
							</Button>
						</div>
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						{#if edit}
							<Button
								kind="outlined"
								size="md"
								status="error"
								type="button"
								on:click={() => {
									showDeleteConfirmDialog = true;
								}}
							>
								{$i18n.t('Delete')}
							</Button>
						{/if}

						<Button kind="filled" size="md" type="submit" disabled={loading} {loading}>
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
