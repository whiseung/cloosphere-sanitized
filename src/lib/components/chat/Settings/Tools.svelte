<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { getModels as _getModels, getToolServersData } from '$lib/apis';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import { models, settings, toolServers, user } from '$lib/stores';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Connection from './Tools/Connection.svelte';

	import AddServerModal from '$lib/components/AddServerModal.svelte';

	export let saveSettings: Function;

	let servers = null;
	let showConnectionModal = false;

	const addConnectionHandler = async (server) => {
		servers = [...servers, server];
		await updateHandler();
	};

	const updateHandler = async () => {
		await saveSettings({
			toolServers: servers
		});

		toolServers.set(await getToolServersData($i18n, $settings?.toolServers ?? []));
	};

	onMount(async () => {
		servers = $settings?.toolServers ?? [];
	});
</script>

<AddServerModal bind:show={showConnectionModal} onSubmit={addConnectionHandler} direct />

<form
	class="flex flex-col h-full justify-between text-sm"
	on:submit|preventDefault={() => {
		updateHandler();
	}}
>
	<div class=" overflow-y-scroll scrollbar-hidden h-full">
		{#if servers !== null}
			<div class="pr-1.5 space-y-2">
				<div class="flex justify-between items-center">
					<div class=" text-base font-semibold">{$i18n.t('Manage Tool Servers')}</div>

					<Tooltip content={$i18n.t(`Add Connection`)}>
						<Button
							kind="text"
							size="sm"
							on:click={() => {
								showConnectionModal = true;
							}}
						>
							<svelte:fragment slot="prefix">
								<Plus className="size-3.5" />
							</svelte:fragment>
							{$i18n.t('Add')}
						</Button>
					</Tooltip>
				</div>

				<div class="flex flex-col gap-1.5">
					{#each servers as server, idx}
						<Connection
							bind:connection={server}
							direct
							onSubmit={() => {
								updateHandler();
							}}
							onDelete={() => {
								servers = servers.filter((_, i) => i !== idx);
								updateHandler();
							}}
						/>
					{/each}
				</div>

				<div class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Connect to your own OpenAPI compatible external tool servers.')}
					<br />
					{$i18n.t(
						'CORS must be properly configured by the provider to allow requests from Open WebUI.'
					)}
				</div>

				<div class="text-xs text-gray-600 dark:text-gray-300">
					<a class="underline" href="/guide" target="_blank">
						{$i18n.t('Learn more about OpenAPI tool servers.')}
					</a>
				</div>
			</div>
		{:else}
			<div class="flex h-full justify-center">
				<div class="my-auto">
					<Spinner className="size-6" />
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>
