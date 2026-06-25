<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	export let onSubmit: Function = () => {};
	export let show = false;

	let name = '';
	let description = '';
	let userIds = [];

	let loading = false;

	const submitHandler = async () => {
		loading = true;

		const group = {
			name,
			description
		};

		await onSubmit(group);

		loading = false;
		show = false;

		name = '';
		description = '';
		userIds = [];
	};

	onMount(() => {
		console.log('mounted');
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-100 px-5 pt-4 mb-1.5">
			<div class=" text-lg font-medium self-center font-primary">
				{$i18n.t('Add User Group')}
			</div>
			<button
				class="self-center"
				type="button"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit={(e) => {
						e.preventDefault();
						submitHandler();
					}}
				>
					<div class="px-1 flex flex-col w-full gap-2">
						<Input
							bind:value={name}
							label={$i18n.t('Name')}
							placeholder={$i18n.t('Group Name')}
							size="md"
							autocomplete="off"
							required
						/>

						<Textarea
							bind:value={description}
							label={$i18n.t('Description')}
							placeholder={$i18n.t('Group Description')}
							rows={2}
							size="md"
						/>
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
						<Button kind="filled" size="md" type="submit" {loading}>
							{$i18n.t('Create')}
						</Button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
