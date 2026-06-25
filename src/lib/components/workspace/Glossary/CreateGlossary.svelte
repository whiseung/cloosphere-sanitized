<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user, userPermissions } from '$lib/stores';
	import { createNewGlossary } from '$lib/apis/glossary';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const { name, description, accessControl } = e.detail;
		const res = await createNewGlossary(localStorage.token, name, description, accessControl).catch(
			(err) => {
				toast.error($i18n.t(`${err}`));
				return null;
			}
		);
		if (res) {
			toast.success($i18n.t('Glossary created successfully.'));
			goto('/workspace/glossary');
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a glossary')}
	nameLabel={$i18n.t('What knowledge does this contain?')}
	namePlaceholder={$i18n.t('Name your glossary')}
	descriptionLabel={$i18n.t('How can this data be utilized?')}
	descriptionPlaceholder={$i18n.t('Describe your glossary and its purpose')}
	backHref="/workspace/glossary"
	allowPublic={$userPermissions?.sharing?.public_glossaries || $user?.role === 'admin'}
	bind:loading
	on:submit={handleSubmit}
/>
