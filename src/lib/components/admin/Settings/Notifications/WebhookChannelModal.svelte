<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { testWebhook } from '$lib/apis/notifications';
	import type { WebhookChannelConfig } from '$lib/apis/notifications';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let edit = false;
	export let index = -1;
	export let channel: WebhookChannelConfig | null = null;
	export let onSubmit: (ch: WebhookChannelConfig) => void = () => {};
	export let onDelete: () => void = () => {};

	let name = '';
	let provider = '';
	let url = '';
	let bot_token = '';
	let chat_id = '';

	let testingWebhook = false;

	$: providerOptions = [
		{ value: '', label: $i18n.t('Select a provider') },
		{ value: 'slack', label: 'Slack' },
		{ value: 'teams', label: 'Microsoft Teams' },
		{ value: 'discord', label: 'Discord' },
		{ value: 'telegram', label: 'Telegram' },
		{ value: 'google_chat', label: 'Google Chat' }
	];

	const init = () => {
		if (channel) {
			name = channel.name ?? '';
			provider = channel.provider ?? '';
			url = channel.url ?? '';
			bot_token = channel.bot_token ?? '';
			chat_id = channel.chat_id ?? '';
		} else {
			name = '';
			provider = '';
			url = '';
			bot_token = '';
			chat_id = '';
		}
	};

	$: if (show) init();

	const urlPlaceholder = (p: string) => {
		if (p === 'slack') return 'https://hooks.slack.com/services/...';
		if (p === 'teams') return 'https://outlook.office.com/webhook/...';
		if (p === 'discord') return 'https://discord.com/api/webhooks/...';
		if (p === 'google_chat') return 'https://chat.googleapis.com/v1/spaces/.../messages?key=...';
		return 'https://...';
	};

	const providerHint = (p: string): string => {
		if (p === 'slack')
			return $i18n.t('Create an Incoming Webhook in your Slack workspace settings.');
		if (p === 'teams')
			return $i18n.t('Create an Incoming Webhook connector in your Teams channel.');
		if (p === 'discord') return $i18n.t('Create a Webhook in your Discord server settings.');
		return '';
	};

	const handleTestWebhook = async () => {
		testingWebhook = true;
		const result = await testWebhook(localStorage.token, index);
		testingWebhook = false;
		if (result.success) {
			toast.success($i18n.t('Webhook test sent successfully'));
		} else {
			toast.error($i18n.t('Webhook test failed') + ': ' + result.message);
		}
	};

	const submitHandler = () => {
		onSubmit({ name, provider, url, bot_token, chat_id });
		show = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<!-- Header -->
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{edit ? $i18n.t('Edit Webhook Channel') : $i18n.t('Add Webhook Channel')}
			</div>
			<button
				class="self-center"
				type="button"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<!-- Body -->
		<div class="flex flex-col w-full px-4 pb-4 dark:text-gray-200">
			<form class="flex flex-col w-full" on:submit|preventDefault={submitHandler}>
				<div class="px-1 flex flex-col gap-3">
					<!-- Channel name -->
					<Input
						bind:value={name}
						label={$i18n.t('Channel Name')}
						placeholder="e.g. slack-ops"
						size="md"
					/>

					<!-- Provider -->
					<LabelBase label={$i18n.t('Webhook Provider')} size="md">
						<svelte:fragment slot="right">
							<div class="min-w-[14rem]">
								<Selector
									value={provider ?? ''}
									items={providerOptions}
									size="sm"
									searchEnabled={false}
									on:change={(event) => {
										provider = event.detail.value;
									}}
								/>
							</div>
						</svelte:fragment>
					</LabelBase>

					{#if provider}
						{#if provider === 'telegram'}
							<!-- Bot Token -->
							<div>
								<LabelBase label={$i18n.t('Bot Token')} size="md" />
								<SensitiveInput
									placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
									bind:value={bot_token}
									required={false}
								/>
							</div>

							<!-- Chat ID -->
							<Input
								bind:value={chat_id}
								label={$i18n.t('Chat ID')}
								placeholder="-1001234567890"
								size="md"
							/>

							<div class="text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Create a bot with @BotFather and invite it to your group chat.')}
							</div>
						{:else}
							<!-- URL -->
							<Input
								bind:value={url}
								label={$i18n.t('Webhook URL')}
								caption={providerHint(provider)}
								type="url"
								placeholder={urlPlaceholder(provider)}
								size="md"
							/>
						{/if}
					{/if}

					<!-- Test section (edit mode only) -->
					{#if edit && provider}
						<hr class="border-gray-100 dark:border-gray-700/10 my-0.5" />

						<LabelBase label={$i18n.t('Test Webhook')} size="md">
							<svelte:fragment slot="right">
								<Button
									kind="outlined"
									size="sm"
									type="button"
									loading={testingWebhook}
									disabled={testingWebhook}
									on:click={handleTestWebhook}
								>
									{$i18n.t('Test')}
								</Button>
							</svelte:fragment>
						</LabelBase>
					{/if}
				</div>

				<!-- Footer -->
				<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
					{#if edit}
						<Button
							kind="outlined"
							size="md"
							type="button"
							on:click={() => {
								onDelete();
								show = false;
							}}
						>
							{$i18n.t('Delete')}
						</Button>
					{/if}
					<Button kind="filled" size="md" type="submit">
						{$i18n.t('Save')}
					</Button>
				</div>
			</form>
		</div>
	</div>
</Modal>
