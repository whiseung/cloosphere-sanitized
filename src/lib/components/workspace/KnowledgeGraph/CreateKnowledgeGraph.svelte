<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user } from '$lib/stores';
	import { createKnowledgeGraph } from '$lib/apis/knowledge-graph';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const { name, description, accessControl } = e.detail;
		const res = await createKnowledgeGraph(
			localStorage.token,
			name,
			description,
			{ sources: { glossary_ids: [], knowledge_ids: [] } },
			accessControl
		).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});
		if (res) {
			toast.success($i18n.t('Knowledge graph created'));
			goto(`/workspace/knowledge-graph/${res.id}`);
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a knowledge graph')}
	nameLabel={$i18n.t('What are you working on?')}
	namePlaceholder={$i18n.t('Name your knowledge graph')}
	descriptionLabel={$i18n.t('What are you trying to achieve?')}
	descriptionPlaceholder={$i18n.t('Describe your knowledge graph and objectives')}
	backHref="/workspace/knowledge-graph"
	allowPublic={$user?.role === 'admin'}
	bind:loading
	on:submit={handleSubmit}
/>
