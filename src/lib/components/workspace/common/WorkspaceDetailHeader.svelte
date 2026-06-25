<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { goto } from '$app/navigation';

	import Button from '$lib/components/common/Button.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher();

	export let backHref: string = '';

	export let badgeContent: string = '';
	export let badgeType: 'info' | 'success' | 'warning' | 'error' | 'muted' = 'muted';

	export let name: string | null = '';
	export let namePlaceholder: string = '';
	export let nameRequired: boolean = false;
	export let nameDisabled: boolean = false;

	export let showDescription: boolean = true;
	export let description: string | null = '';
	export let descriptionPlaceholder: string = '';
	export let descriptionRequired: boolean = false;
	export let descriptionDisabled: boolean = false;

	export let resourceType: string = '';
	export let resourceId: string | null | undefined = '';
	export let tagSelector: any = null;

	export let showAccess: boolean = false;
	export let showCancel: boolean = true;
	export let showSave: boolean = true;

	export let canWrite: boolean = true;
	export let saving: boolean = false;
	export let saveLabel: string = '';
	export let cancelLabel: string = '';
	export let saveType: 'button' | 'submit' = 'button';

	$: computedSaveLabel = saveLabel || $i18n.t('Save & Update');
	$: computedCancelLabel = cancelLabel || $i18n.t('Cancel');

	const onBack = () => {
		dispatch('back');
		if (backHref) goto(backHref);
	};
	const onCancel = () => {
		dispatch('cancel');
		if (backHref) goto(backHref);
	};
</script>

<div class="w-full mb-2.5">
	<div class="flex items-center justify-between px-0.5 mb-1 gap-2">
		<div class="flex items-center gap-2 flex-1 min-w-0">
			<button
				type="button"
				class="p-1.5 rounded-lg dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-gray-850 shrink-0"
				on:click={onBack}
			>
				<ChevronLeft strokeWidth="2.5" className="size-4" />
			</button>

			{#if badgeContent}
				<Badge type={badgeType} content={badgeContent} />
			{/if}

			<input
				type="text"
				class="text-left flex-1 font-semibold text-2xl bg-transparent outline-hidden min-w-0"
				bind:value={name}
				placeholder={namePlaceholder}
				required={nameRequired}
				disabled={nameDisabled}
				on:input={() => dispatch('change', { field: 'name' })}
			/>
		</div>

		<div class="flex items-center gap-1.5 self-center shrink-0">
			<slot name="actions-prefix" />

			{#if resourceType && resourceId}
				<WorkspaceTagSelector bind:this={tagSelector} {resourceType} {resourceId} />
			{/if}

			{#if showAccess}
				<Button kind="outlined" size="md" on:click={() => dispatch('access')}>
					<svelte:fragment slot="prefix">
						<LockClosed strokeWidth="2.5" className="size-3.5" />
					</svelte:fragment>
					{$i18n.t('Access')}
				</Button>
			{/if}

			{#if showCancel}
				<Button kind="outlined" size="md" type="button" on:click={onCancel}>
					{computedCancelLabel}
				</Button>
			{/if}

			<slot name="save-button">
				{#if showSave}
					<Button
						kind="filled"
						size="md"
						type={saveType}
						loading={saving}
						disabled={!canWrite}
						on:click={() => dispatch('save')}
					>
						{computedSaveLabel}
					</Button>
				{/if}
			</slot>
		</div>
	</div>

	{#if showDescription}
		<div class="pl-10 pr-1">
			<input
				type="text"
				class="text-left text-xs w-full text-gray-500 dark:text-gray-400 bg-transparent outline-hidden"
				bind:value={description}
				placeholder={descriptionPlaceholder}
				required={descriptionRequired}
				disabled={descriptionDisabled}
				on:input={() => dispatch('change', { field: 'description' })}
			/>
		</div>
	{/if}

	<slot name="below" />
</div>
