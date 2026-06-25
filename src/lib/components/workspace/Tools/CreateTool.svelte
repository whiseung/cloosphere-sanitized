<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user, userPermissions } from '$lib/stores';
	import { createNewToolConnection } from '$lib/apis/tool-connections';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	let loading = false;

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		loading = true;
		const { name, description, accessControl } = e.detail;
		const res = await createNewToolConnection(localStorage.token, {
			name: name.trim(),
			description: description.trim(),
			data: {
				connection: {
					type: 'openapi',
					url: '',
					path: 'openapi.json',
					auth_type: 'bearer',
					key: '',
					enabled: true
				}
			},
			access_control: accessControl
		}).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});
		if (res) {
			toast.success($i18n.t('Tool created successfully'));
			goto(`/workspace/tools/${res.id}`);
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a tool')}
	nameLabel={$i18n.t('What does this tool do?')}
	namePlaceholder={$i18n.t('Name your tool')}
	descriptionLabel={$i18n.t('How can this tool be used?')}
	descriptionPlaceholder={$i18n.t('Describe your tool and its purpose')}
	backHref="/workspace/tools"
	allowPublic={$userPermissions?.sharing?.public_tools || $user?.role === 'admin'}
	bind:loading
	on:submit={handleSubmit}
/>
