<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user, userPermissions } from '$lib/stores';
	import { createNewDbSphere } from '$lib/apis/dbsphere';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const { name, description, accessControl } = e.detail;
		const res = await createNewDbSphere(localStorage.token, name, description, accessControl).catch(
			(err) => {
				toast.error($i18n.t(`${err}`));
				return null;
			}
		);
		if (res) {
			toast.success($i18n.t('Database created successfully.'));
			goto('/workspace/database');
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a database')}
	nameLabel={$i18n.t('What data does this database contain?')}
	namePlaceholder={$i18n.t('Name your database')}
	descriptionLabel={$i18n.t('How can this data be utilized?')}
	descriptionPlaceholder={$i18n.t('Describe your database and objectives')}
	backHref="/workspace/database"
	allowPublic={$userPermissions?.sharing?.public_databases || $user?.role === 'admin'}
	bind:loading
	on:submit={handleSubmit}
/>
