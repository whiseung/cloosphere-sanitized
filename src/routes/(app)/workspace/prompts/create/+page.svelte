<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { prompts } from '$lib/stores';
	import { onMount, tick, getContext } from 'svelte';

	const i18n = getContext('i18n');

	import { createNewPrompt, getPrompts } from '$lib/apis/prompts';
	import PromptEditor from '$lib/components/workspace/Prompts/PromptEditor.svelte';
	import Button from '$lib/components/common/Button.svelte';

	let prompt = null;
	let importInputElement: HTMLInputElement;
	const onSubmit = async (_prompt) => {
		const prompt = await createNewPrompt(localStorage.token, _prompt).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (prompt) {
			toast.success($i18n.t('Prompt created successfully'));

			await prompts.set(await getPrompts(localStorage.token));
			await goto('/workspace/prompts');
		}
	};

	onMount(async () => {
		window.addEventListener('message', async (event) => {
			if (
				!['https://openwebui.com', 'https://www.openwebui.com', 'http://localhost:5173'].includes(
					event.origin
				)
			)
				return;
			const _prompt = JSON.parse(event.data);
			console.log(_prompt);

			prompt = {
				title: _prompt.title,
				command: _prompt.command,
				content: _prompt.content,
				access_control: null
			};
		});

		if (window.opener ?? false) {
			window.opener.postMessage('loaded', '*');
		}

		if (sessionStorage.prompt) {
			const _prompt = JSON.parse(sessionStorage.prompt);

			prompt = {
				title: _prompt.title,
				command: _prompt.command,
				content: _prompt.content,
				access_control: null
			};
			sessionStorage.removeItem('prompt');
		}
	});

	const handleFileImport = (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input?.files?.[0];
		if (!file) return;
		const reader = new FileReader();
		reader.onload = (e) => {
			try {
				let data = JSON.parse(e.target?.result as string);
				if (Array.isArray(data)) data = data[0];
				prompt = {
					title: data.title ?? data.name ?? '',
					command: data.command ?? `/${(data.title || 'imported').toLowerCase().replace(/\s+/g, '-')}`,
					content: data.content ?? '',
					access_control: data.access_control ?? null
				};
				toast.success($i18n.t('Prompt imported. Review and save.'));
			} catch {
				toast.error($i18n.t('Failed to parse JSON file.'));
			}
			input.value = '';
		};
		reader.readAsText(file);
	};
</script>

<input bind:this={importInputElement} type="file" accept=".json" hidden on:change={handleFileImport} />

{#key prompt}
	<PromptEditor {prompt} {onSubmit}>
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
	</PromptEditor>
{/key}
