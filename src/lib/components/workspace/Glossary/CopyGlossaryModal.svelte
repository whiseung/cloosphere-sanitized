<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	import { copyGlossary } from '$lib/apis/glossary';
	import { goto } from '$app/navigation';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let glossary: { id: string; name: string } | null = null;
	export let userGroups: { id: string; name: string }[] = [];

	let name = '';
	let targetGroupId = '';
	let submitting = false;

	$: groupItems = [
		{ value: '', label: $i18n.t('Private (no group)') },
		...userGroups.map((g) => ({ value: g.id, label: g.name }))
	];

	$: if (show && glossary) {
		name = `${glossary.name} (${$i18n.t('Copy')})`;
		targetGroupId = '';
	}

	const handleSubmit = async () => {
		if (!glossary || submitting) return;
		submitting = true;
		try {
			const res = await copyGlossary(localStorage.token, glossary.id, {
				name: name?.trim() || undefined,
				target_group_id: targetGroupId || null
			});
			if (res?.id) {
				toast.success($i18n.t('Glossary copied'));
				show = false;
				dispatch('copied', res);
				await goto(`/workspace/glossary/${res.id}`);
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			submitting = false;
		}
	};
</script>

<Modal bind:show size="sm">
	<div class="px-5 py-4 flex flex-col gap-4">
		<div>
			<div class="text-base font-semibold text-gray-900 dark:text-white">
				{$i18n.t('Copy Glossary')}
			</div>
			<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
				{$i18n.t('Forks an independent copy. No auto-sync with the original.')}
			</div>
		</div>

		<Input
			label={$i18n.t('Name')}
			bind:value={name}
			placeholder={$i18n.t('Glossary name')}
			size="md"
		/>

		<div class="flex flex-col gap-1.5">
			<div class="text-xs font-medium text-gray-700 dark:text-gray-300">
				{$i18n.t('Target group')}
			</div>
			<Selector
				bind:value={targetGroupId}
				items={groupItems}
				size="md"
				placeholder={$i18n.t('Select target group')}
				searchEnabled={userGroups.length > 5}
			/>
			<div class="text-[11px] text-gray-500 dark:text-gray-400">
				{$i18n.t('Only groups you are a member of are shown. Empty = private (owner only).')}
			</div>
		</div>

		<div class="flex justify-end gap-2 mt-2">
			<Button kind="outlined" size="md" on:click={() => (show = false)} disabled={submitting}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" on:click={handleSubmit} loading={submitting}>
				{$i18n.t('Copy')}
			</Button>
		</div>
	</div>
</Modal>
