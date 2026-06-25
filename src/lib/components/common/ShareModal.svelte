<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { user } from '$lib/stores';
	import Button from './Button.svelte';
	import Modal from './Modal.svelte';
	import UserSearchSelect from './UserSearchSelect.svelte';

	const dispatch = createEventDispatcher();

	export let show = false;
	export let selectedUserIds: string[] = [];
	export let description = '';
	export let saveLabel = '';
</script>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between items-center px-5 pt-4 pb-2">
			<h3 class="text-lg font-medium dark:text-white">
				{$i18n.t('Share')}
			</h3>
			<button
				class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={() => (show = false)}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-5 h-5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M6 18 18 6M6 6l12 12"
					/>
				</svg>
			</button>
		</div>
		{#if description}
			<div class="px-5 pb-2">
				<p class="text-xs text-gray-400 dark:text-gray-500">
					{description}
				</p>
			</div>
		{/if}
		<div class="px-5 pb-4">
			<UserSearchSelect
				bind:selectedUserIds
				excludeUserIds={[$user?.id].filter(Boolean)}
				excludeAdmins={false}
				searchFirst={true}
			/>
		</div>
		<div class="flex justify-end gap-2 px-5 pb-4">
			<Button kind="outlined" size="md" on:click={() => (show = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" on:click={() => dispatch('save')}>
				{$i18n.t(saveLabel || 'Save')}
			</Button>
		</div>
	</div>
</Modal>
