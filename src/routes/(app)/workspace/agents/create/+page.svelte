<script>
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { config, models, settings } from '$lib/stores';

	import { onMount, tick, getContext } from 'svelte';
	import { createNewModel, getModelById } from '$lib/apis/models';
	import { getModels } from '$lib/apis';

	import AgentEditor from '$lib/components/workspace/Agents/AgentEditor.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { brandingUrls } from '$lib/stores/branding';

	const i18n = getContext('i18n');

	let importInputElement;

	const onSubmit = async (modelInfo) => {
		if ($models.find((m) => m.id === modelInfo.id)) {
			toast.error(
				`Error: An agent with the ID '${modelInfo.id}' already exists. Please select a different ID to proceed.`
			);
			return;
		}

		if (modelInfo.id === '') {
			toast.error($i18n.t('Error: Agent ID cannot be empty. Please enter a valid ID to proceed.'));
			return;
		}

		if (modelInfo) {
			const res = await createNewModel(localStorage.token, {
				...modelInfo,
				meta: {
					...modelInfo.meta,
					profile_image_url: modelInfo.meta.profile_image_url ?? $brandingUrls.favicon,
					suggestion_prompts: modelInfo.meta.suggestion_prompts
						? modelInfo.meta.suggestion_prompts.filter((prompt) => prompt.content !== '')
						: null
				},
				params: { ...modelInfo.params }
			}).catch((error) => {
				toast.error($i18n.t(`${error}`));
				return null;
			});

			if (res) {
				await models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
				toast.success($i18n.t('Agent created successfully!'));
				await goto('/workspace/agents');
			}
		}
	};

	let model = null;

	onMount(async () => {
		window.addEventListener('message', async (event) => {
			if (
				!['https://openwebui.com', 'https://www.openwebui.com', 'http://localhost:5173'].includes(
					event.origin
				)
			) {
				return;
			}

			let data = JSON.parse(event.data);

			if (data?.info) {
				data = data.info;
			}

			model = data;
		});

		if (window.opener ?? false) {
			window.opener.postMessage('loaded', '*');
		}

		if (sessionStorage.model) {
			model = JSON.parse(sessionStorage.model);
			sessionStorage.removeItem('model');
		}
	});

	const handleFileImport = (event) => {
		const file = event.target?.files?.[0];
		if (!file) return;
		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				let data = JSON.parse(e.target.result);
				// Export format: [{...}] or {...}
				if (Array.isArray(data)) data = data[0];
				if (data?.info) data = data.info;
				model = { ...data, id: `${data.id || 'imported'}-${Date.now()}` };
				toast.success($i18n.t('Agent imported. Review and save.'));
			} catch {
				toast.error($i18n.t('Failed to parse JSON file.'));
			}
			event.target.value = '';
		};
		reader.readAsText(file);
	};
</script>

<input bind:this={importInputElement} type="file" accept=".json" hidden on:change={handleFileImport} />

{#key model}
	<AgentEditor {model} {onSubmit}>
		<svelte:fragment slot="header-actions">
			<Button kind="outlined" size="md" on:click={() => importInputElement?.click()}>
				<svelte:fragment slot="prefix">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5">
						<path fill-rule="evenodd" d="M4 2a1.5 1.5 0 0 0-1.5 1.5v9A1.5 1.5 0 0 0 4 14h8a1.5 1.5 0 0 0 1.5-1.5V6.621a1.5 1.5 0 0 0-.44-1.06L9.94 2.439A1.5 1.5 0 0 0 8.878 2H4Zm4 9.5a.75.75 0 0 1-.75-.75V8.06l-.72.72a.75.75 0 0 1-1.06-1.06l2-2a.75.75 0 0 1 1.06 0l2 2a.75.75 0 1 1-1.06 1.06l-.72-.72v2.69a.75.75 0 0 1-.75.75Z" clip-rule="evenodd" />
					</svg>
				</svelte:fragment>
				{$i18n.t('Import')}
			</Button>
		</svelte:fragment>
	</AgentEditor>
{/key}
