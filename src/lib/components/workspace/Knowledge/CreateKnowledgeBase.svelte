<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { knowledge, user, userPermissions } from '$lib/stores';
	import { createNewKnowledge, getKnowledgeBases } from '$lib/apis/knowledge';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const { name, description, accessControl } = e.detail;
		const res = await createNewKnowledge(
			localStorage.token,
			name,
			description,
			accessControl
		).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});
		if (res) {
			toast.success($i18n.t('Knowledge created successfully.'));
			knowledge.set(await getKnowledgeBases(localStorage.token));
			goto(`/workspace/knowledge/${res.id}`);
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a knowledge base')}
	nameLabel={$i18n.t('What are you working on?')}
	namePlaceholder={$i18n.t('Name your knowledge base')}
	descriptionLabel={$i18n.t('What are you trying to achieve?')}
	descriptionPlaceholder={$i18n.t('Describe your knowledge base and objectives')}
	backHref="/workspace/knowledge"
	allowPublic={$userPermissions?.sharing?.public_knowledge || $user?.role === 'admin'}
	bind:loading
	on:submit={handleSubmit}
/>
