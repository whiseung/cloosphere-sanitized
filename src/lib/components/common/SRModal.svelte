<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext } from 'svelte';
	import { submitSR } from '$lib/apis/sr';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	export let show = false;

	const SR_TYPES: Record<string, string> = {
		usage_limit: 'Usage Limit',
		feature: 'Feature Inquiry',
		bug: 'Bug Report',
		account: 'Account / Permission',
		other: 'Other'
	};

	let title = '';
	let type = '';
	let content = '';
	let submitting = false;

	function resetForm() {
		title = '';
		type = '';
		content = '';
	}

	async function handleSubmit() {
		if (!title.trim()) {
			toast.error($i18n.t('Title is required'));
			return;
		}
		if (!type) {
			toast.error($i18n.t('Please select a type'));
			return;
		}
		if (!content.trim()) {
			toast.error($i18n.t('Content is required'));
			return;
		}

		submitting = true;
		try {
			await submitSR(localStorage.token, { title, type, content });
			toast.success($i18n.t('Service request submitted successfully'));
			resetForm();
			show = false;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to submit service request'));
		} finally {
			submitting = false;
		}
	}
</script>

<Modal bind:show size="md">
	<div class="px-6 py-5">
		<div class="flex items-center justify-between mb-4">
			<h2 class="text-lg font-semibold dark:text-gray-100">
				{$i18n.t('Service Request')}
			</h2>
			<button
				class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
				on:click={() => (show = false)}
			>
				<svg xmlns="http://www.w3.org/2000/svg" class="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-3">
			<!-- Type -->
			<div>
				<label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
					{$i18n.t('Type')} <span class="text-red-500">*</span>
				</label>
				<select
					bind:value={type}
					class="w-full rounded-lg py-2 px-3 text-sm bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-300 dark:border-gray-700 outline-hidden"
				>
					<option value="">{$i18n.t('Select type')}</option>
					{#each Object.entries(SR_TYPES) as [value, label]}
						<option {value}>{$i18n.t(label)}</option>
					{/each}
				</select>
			</div>

			<!-- Title -->
			<div>
				<label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
					{$i18n.t('Title')} <span class="text-red-500">*</span>
				</label>
				<input
					type="text"
					bind:value={title}
					placeholder={$i18n.t('Brief description of your request')}
					class="w-full rounded-lg py-2 px-3 text-sm bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-300 dark:border-gray-700 outline-hidden"
				/>
			</div>

			<!-- Content -->
			<div>
				<label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
					{$i18n.t('Content')} <span class="text-red-500">*</span>
				</label>
				<textarea
					bind:value={content}
					rows="6"
					placeholder={$i18n.t('Describe your request in detail')}
					class="w-full rounded-lg py-2 px-3 text-sm bg-white dark:bg-gray-900 dark:text-gray-200 border border-gray-300 dark:border-gray-700 outline-hidden resize-none"
				></textarea>
			</div>

			<!-- Submit -->
			<div class="flex justify-end gap-2 mt-1">
				<button
					type="button"
					class="px-4 py-2 text-sm rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
					on:click={() => (show = false)}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					type="submit"
					class="px-4 py-2 text-sm rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition flex items-center gap-2 disabled:opacity-50"
					disabled={submitting}
				>
					{#if submitting}
						<Spinner className="size-4" />
					{/if}
					{$i18n.t('Submit')}
				</button>
			</div>
		</form>
	</div>
</Modal>
