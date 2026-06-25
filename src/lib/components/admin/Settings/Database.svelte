<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { downloadDatabase, downloadLiteLLMConfig } from '$lib/apis/utils';
	import { onMount, getContext } from 'svelte';
	import { config, user } from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import { getAllUserChats } from '$lib/apis/chats';
	import { exportConfig, importConfig } from '$lib/apis/configs';

	import Button from '$lib/components/common/Button.svelte';
	import Download from '$lib/components/icons/Download.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	const exportAllUserChats = async () => {
		let blob = new Blob([JSON.stringify(await getAllUserChats(localStorage.token))], {
			type: 'application/json'
		});
		saveAs(blob, `all-chats-export-${Date.now()}.json`);
	};

	const handleImportConfigFile = (event: Event) => {
		const input = event.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		const reader = new FileReader();

		reader.onload = async (loadEvent) => {
			const result = (loadEvent.target as FileReader).result;
			if (typeof result !== 'string') return;
			const res = await importConfig(localStorage.token, JSON.parse(result)).catch((error) => {
				toast.error($i18n.t(`${error}`));
			});

			if (res) {
				toast.success($i18n.t('Config imported successfully'));
			}
			input.value = '';
		};

		reader.readAsText(file);
	};

	const triggerImportConfigPicker = () => {
		document.getElementById('config-json-input')?.click();
	};

	const exportConfigToFile = async () => {
		const cfg = await exportConfig(localStorage.token);
		const blob = new Blob([JSON.stringify(cfg)], {
			type: 'application/json'
		});
		saveAs(blob, `config-${Date.now()}.json`);
	};

	const downloadDatabaseHandler = () => {
		downloadDatabase(localStorage.token).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});
	};

	onMount(async () => {
		// permissions = await getUserPermissions(localStorage.token);
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveHandler();
	}}
>
	<div class=" space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<div>
			<div class=" mb-2 text-sm font-medium">{$i18n.t('Database')}</div>

			<input
				id="config-json-input"
				hidden
				type="file"
				accept=".json"
				on:change={handleImportConfigFile}
			/>

			<Button
				kind="text"
				size="md"
				type="button"
				className="w-full justify-start"
				on:click={triggerImportConfigPicker}
			>
				<svelte:fragment slot="prefix">
					<Download className="size-4" />
				</svelte:fragment>
				{$i18n.t('Import Config from JSON File')}
			</Button>

			<Button
				kind="text"
				size="md"
				type="button"
				className="w-full justify-start"
				on:click={exportConfigToFile}
			>
				<svelte:fragment slot="prefix">
					<Download className="size-4" />
				</svelte:fragment>
				{$i18n.t('Export Config to JSON File')}
			</Button>

			<hr class="border-gray-100 dark:border-gray-850 my-1" />

			{#if $config?.features.enable_admin_export ?? true}
				<Button
					kind="text"
					size="md"
					type="button"
					className="w-full justify-start"
					on:click={downloadDatabaseHandler}
				>
					<svelte:fragment slot="prefix">
						<Download className="size-4" />
					</svelte:fragment>
					{$i18n.t('Download Database')}
				</Button>

				<Button
					kind="text"
					size="md"
					type="button"
					className="w-full justify-start"
					on:click={exportAllUserChats}
				>
					<svelte:fragment slot="prefix">
						<Download className="size-4" />
					</svelte:fragment>
					{$i18n.t('Export All Chats (All Users)')}
				</Button>
			{/if}
		</div>
	</div>
</form>
