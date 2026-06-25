<script>
	import { createEventDispatcher, getContext } from 'svelte';

	import Modal from '$lib/components/common/Modal.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { addNewMemory, updateMemoryById } from '$lib/apis/memories';
	import { toast } from 'svelte-sonner';

	const dispatch = createEventDispatcher();

	export let show;
	const i18n = getContext('i18n');

	let loading = false;
	let content = '';

	const submitHandler = async () => {
		loading = true;

		const res = await addNewMemory(localStorage.token, content).catch((error) => {
			toast.error($i18n.t(`${error}`));

			return null;
		});

		if (res) {
			console.log(res);
			toast.success($i18n.t('Memory added successfully'));
			content = '';
			show = false;
			dispatch('save');
		}

		loading = false;
	};
</script>

<Modal bind:show size="sm">
	<div>
		<div class=" flex justify-between items-center dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-semibold self-center">
				{$i18n.t('Add Memory')}
			</div>
			<button
				type="button"
				class="self-center p-1 rounded-md hover:bg-[var(--cloo-bg-neutral-hovered)] transition"
				aria-label={$i18n.t('Close')}
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

		<div class="flex flex-col w-full px-5 pb-4 dark:text-gray-200">
			<form
				class="flex flex-col w-full gap-3"
				on:submit|preventDefault={() => {
					submitHandler();
				}}
			>
				<div class="space-y-1.5">
					<Textarea
						bind:value={content}
						rows={5}
						autoResize={false}
						size="md"
						placeholder={$i18n.t('Enter a detail about yourself for your LLMs to recall')}
					/>
					<div class="text-xs text-gray-500 dark:text-gray-400">
						ⓘ {$i18n.t('Refer to yourself as "User" (e.g., "User is learning Spanish")')}
					</div>
				</div>

				<div class="flex justify-end">
					<Button kind="filled" size="md" type="submit" {loading}>
						{$i18n.t('Add')}
					</Button>
				</div>
			</form>
		</div>
	</div>
</Modal>
