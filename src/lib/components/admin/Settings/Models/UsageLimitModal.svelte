<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext, onMount } from 'svelte';
	const i18n: any = getContext('i18n');

	import Modal from '$lib/components/common/Modal.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import TokenInput from '$lib/components/common/TokenInput.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import { getUsageLimitConfig, updateUsageLimitConfig } from '$lib/apis/auths';

	export let show = false;

	let loading = false;
	let initialized = false;
	let config: any = null;

	$: if (show && !initialized) {
		init();
	}

	$: if (!show) {
		initialized = false;
	}

	$: exceedActionItems = [
		{ value: 'warn', label: $i18n.t('Warn') },
		{ value: 'block', label: $i18n.t('Block') }
	];

	const init = async () => {
		loading = true;
		try {
			const data = await getUsageLimitConfig(localStorage.token);
			if (!data) {
				throw new Error('empty response');
			}
			config = data;
			initialized = true;
		} catch (err) {
			toast.error($i18n.t('Failed to load configuration'));
			show = false;
		} finally {
			loading = false;
		}
	};

	const save = async () => {
		if (!config) return;
		loading = true;
		try {
			await updateUsageLimitConfig(localStorage.token, {
				ENABLE_USAGE_LIMIT: !!config.ENABLE_USAGE_LIMIT,
				USAGE_LIMIT_DEFAULT_DAILY_TOKENS: Number(config.USAGE_LIMIT_DEFAULT_DAILY_TOKENS) || 0,
				USAGE_LIMIT_EXCEED_ACTION: config.USAGE_LIMIT_EXCEED_ACTION || 'warn'
			});
			toast.success($i18n.t('Token Limit Management saved'));
			show = false;
		} catch (err) {
			toast.error($i18n.t('Failed to save configuration'));
		}
		loading = false;
	};

	onMount(() => {
		if (show) init();
	});
</script>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('Token Limit Management')}
			</div>
			<button
				class="self-center"
				type="button"
				on:click={() => {
					show = false;
				}}
				aria-label={$i18n.t('Close')}
			>
				<XMark className="w-5 h-5" />
			</button>
		</div>

		<div class="px-5 pb-5 dark:text-gray-200">
			{#if loading || !config}
				<div class="flex justify-center py-6">
					<Spinner />
				</div>
			{:else}
				<form class="flex flex-col gap-3 text-sm" on:submit|preventDefault={save}>
					<LabelBase label={$i18n.t('Enable Usage Limit')} size="md">
						<svelte:fragment slot="right">
							<Switch bind:state={config.ENABLE_USAGE_LIMIT} />
						</svelte:fragment>
					</LabelBase>

					{#if config.ENABLE_USAGE_LIMIT}
						<div class="flex flex-col gap-1.5">
							<LabelBase
								label={$i18n.t('Default Daily Token Limit')}
								caption={$i18n.t(
									'Applies to every model unless that model has its own base limit set on its row.'
								)}
								size="md"
							/>
							<TokenInput bind:value={config.USAGE_LIMIT_DEFAULT_DAILY_TOKENS} />
							<div class="text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Set to 0 for unlimited. Empty = no limit set.')}
							</div>
						</div>

						<div class="flex flex-col gap-1.5">
							<LabelBase
								label={$i18n.t('Exceed Action')}
								caption={$i18n.t('Warn: Show warning but allow usage. Block: Prevent further usage.')}
								size="md"
							/>
							<Selector
								value={config.USAGE_LIMIT_EXCEED_ACTION ?? 'warn'}
								items={exceedActionItems}
								searchEnabled={false}
								size="md"
								className="w-full"
								ariaLabel={$i18n.t('Exceed Action')}
								on:change={(event) => {
									config.USAGE_LIMIT_EXCEED_ACTION = event.detail.value;
								}}
							/>
						</div>
					{/if}

					<div class="flex justify-end pt-2">
						<Button kind="filled" size="md" type="submit" disabled={loading}>
							{$i18n.t('Save')}
						</Button>
					</div>
				</form>
			{/if}
		</div>
	</div>
</Modal>
