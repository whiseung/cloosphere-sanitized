<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getNotificationConfig,
		updateNotificationConfig,
		type EmailChannelConfig,
		type WebhookChannelConfig,
		type NotificationConfig
	} from '$lib/apis/notifications';

	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';

	import EmailChannelModal from './Notifications/EmailChannelModal.svelte';
	import WebhookChannelModal from './Notifications/WebhookChannelModal.svelte';
	import TeamsBotConfig from './Notifications/TeamsBotConfig.svelte';
	import ExternalApiConfig from './Notifications/ExternalApiConfig.svelte';

	let showTeamsBotModal = false;
	let showExternalApiModal = false;

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveHandler: () => void;

	let loaded = false;

	let emailChannels: EmailChannelConfig[] = [];
	let webhookChannels: WebhookChannelConfig[] = [];
	let notificationEvents: string[] = [];

	// Modal state
	let showEmailModal = false;
	let showWebhookModal = false;
	let editingEmailIndex = -1;
	let editingWebhookIndex = -1;

	const openAddEmail = () => {
		editingEmailIndex = -1;
		showEmailModal = true;
	};

	const openEditEmail = (idx: number) => {
		editingEmailIndex = idx;
		showEmailModal = true;
	};

	const openAddWebhook = () => {
		editingWebhookIndex = -1;
		showWebhookModal = true;
	};

	const openEditWebhook = (idx: number) => {
		editingWebhookIndex = idx;
		showWebhookModal = true;
	};

	const handleEmailSubmit = async (ch: EmailChannelConfig) => {
		if (editingEmailIndex === -1) {
			emailChannels = [...emailChannels, ch];
		} else {
			// preserve existing password if blank
			const existing = emailChannels[editingEmailIndex];
			if (!ch.smtp.password) ch.smtp.password = existing.smtp.password;
			if (!ch.sendgrid.api_key) ch.sendgrid.api_key = existing.sendgrid.api_key;
			emailChannels = emailChannels.map((c, i) => (i === editingEmailIndex ? ch : c));
		}
		await persistConfig();
	};

	const handleEmailDelete = async () => {
		emailChannels = emailChannels.filter((_, i) => i !== editingEmailIndex);
		await persistConfig();
	};

	const handleWebhookSubmit = async (ch: WebhookChannelConfig) => {
		if (editingWebhookIndex === -1) {
			webhookChannels = [...webhookChannels, ch];
		} else {
			webhookChannels = webhookChannels.map((c, i) => (i === editingWebhookIndex ? ch : c));
		}
		await persistConfig();
	};

	const handleWebhookDelete = async () => {
		webhookChannels = webhookChannels.filter((_, i) => i !== editingWebhookIndex);
		await persistConfig();
	};

	const persistConfig = async () => {
		const config: NotificationConfig = {
			emails: emailChannels,
			webhooks: webhookChannels,
			events: notificationEvents
		};
		const res = await updateNotificationConfig(localStorage.token, config);
		if (res) {
			emailChannels = res.emails;
			webhookChannels = res.webhooks;
			notificationEvents = res.events;
			saveHandler();
		} else {
			toast.error($i18n.t('Failed to update notification settings'));
		}
	};

	const engineLabel = (engine: string) => {
		if (engine === 'smtp') return 'SMTP';
		if (engine === 'sendgrid') return 'SendGrid';
		return '—';
	};

	const providerLabel = (provider: string) => {
		if (provider === 'slack') return 'Slack';
		if (provider === 'teams') return 'Microsoft Teams';
		if (provider === 'discord') return 'Discord';
		return '—';
	};

	onMount(async () => {
		const res = await getNotificationConfig(localStorage.token);
		if (res) {
			emailChannels = res.emails ?? [];
			webhookChannels = res.webhooks ?? [];
			notificationEvents = res.events ?? [];
		}
		loaded = true;
	});
</script>

<!-- Email modal -->
<EmailChannelModal
	bind:show={showEmailModal}
	edit={editingEmailIndex !== -1}
	index={editingEmailIndex}
	channel={editingEmailIndex !== -1 ? emailChannels[editingEmailIndex] : null}
	onSubmit={handleEmailSubmit}
	onDelete={handleEmailDelete}
/>

<!-- Webhook modal -->
<WebhookChannelModal
	bind:show={showWebhookModal}
	edit={editingWebhookIndex !== -1}
	index={editingWebhookIndex}
	channel={editingWebhookIndex !== -1 ? webhookChannels[editingWebhookIndex] : null}
	onSubmit={handleWebhookSubmit}
	onDelete={handleWebhookDelete}
/>

<div class="flex flex-col h-full text-sm">
	{#if loaded}
		<div class="overflow-y-scroll scrollbar-hidden h-full">
			<!-- ═══════════════════ 알림 (Outbound Notifications) ═══════════════════ -->
			<div class="mb-6">
				<div
					class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mb-2"
				>
					{$i18n.t('Notifications')}
				</div>

				<!-- ── Email Channels ── -->
				<div class="my-2 pr-1.5">
					<div class="flex justify-between items-center">
						<div class="font-medium">{$i18n.t('Email')}</div>
						<Tooltip content={$i18n.t('Add Email Channel')}>
							<button class="px-1" type="button" on:click={openAddEmail}>
								<Plus />
							</button>
						</Tooltip>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						{#each emailChannels as ch, idx (idx)}
							<div class="flex w-full gap-2 items-center min-h-[2rem]">
								<div class="flex-1 flex items-center gap-2 min-w-0">
									<span class="text-sm truncate">
										{ch.name || $i18n.t('(unnamed)')}
									</span>
									<span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">
										{engineLabel(ch.engine)}
									</span>
								</div>
								<Tooltip content={$i18n.t('Configure')} className="self-center">
									<button
										class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
										type="button"
										on:click={() => openEditEmail(idx)}
									>
										<Cog6 />
									</button>
								</Tooltip>
							</div>
						{:else}
							<div class="text-xs text-gray-400 dark:text-gray-500 text-center py-3">
								{$i18n.t('No email channels configured.')}
							</div>
						{/each}
					</div>
				</div>

				<hr class="border-gray-100 dark:border-gray-850" />

				<!-- ── Webhook Channels ── -->
				<div class="my-2 pr-1.5">
					<div class="flex justify-between items-center">
						<div class="font-medium">{$i18n.t('Webhook')}</div>
						<Tooltip content={$i18n.t('Add Webhook Channel')}>
							<button class="px-1" type="button" on:click={openAddWebhook}>
								<Plus />
							</button>
						</Tooltip>
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						{#each webhookChannels as ch, idx (idx)}
							<div class="flex w-full gap-2 items-center min-h-[2rem]">
								<div class="flex-1 flex items-center gap-2 min-w-0">
									<span class="text-sm truncate">
										{ch.name || $i18n.t('(unnamed)')}
									</span>
									<span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">
										{providerLabel(ch.provider)}
									</span>
								</div>
								<Tooltip content={$i18n.t('Configure')} className="self-center">
									<button
										class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
										type="button"
										on:click={() => openEditWebhook(idx)}
									>
										<Cog6 />
									</button>
								</Tooltip>
							</div>
						{:else}
							<div class="text-xs text-gray-400 dark:text-gray-500 text-center py-3">
								{$i18n.t('No webhook channels configured.')}
							</div>
						{/each}
					</div>
				</div>
			</div>

			<!-- ═══════════════════ 봇 연결 (Inbound Bot Channels) ═══════════════════ -->
			<div class="mb-6">
				<div
					class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mb-2"
				>
					{$i18n.t('Bot Connection')}
				</div>

				<div class="my-2 pr-1.5">
					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						<div class="flex w-full gap-2 items-center min-h-[2rem]">
							<div class="flex-1 flex items-center gap-2 min-w-0">
								<span class="text-sm truncate">{$i18n.t('Microsoft Teams')}</span>
							</div>
							<Tooltip content={$i18n.t('Configure')} className="self-center">
								<button
									class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
									type="button"
									aria-label={$i18n.t('Configure Microsoft Teams')}
									data-testid="configure-teams-bot"
									on:click={() => (showTeamsBotModal = true)}
								>
									<Cog6 />
								</button>
							</Tooltip>
						</div>
					</div>
				</div>
			</div>

			<!-- ═══════════════════ API 연동 (External API / IDP Passthrough) ═════════ -->
			<div class="mb-6">
				<div
					class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mb-2"
				>
					{$i18n.t('API Access')}
				</div>

				<div class="my-2 pr-1.5">
					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-1.5">
						<div class="flex w-full gap-2 items-center min-h-[2rem]">
							<div class="flex-1 flex items-center gap-2 min-w-0">
								<span class="text-sm truncate">{$i18n.t('External IDP Passthrough')}</span>
							</div>
							<Tooltip content={$i18n.t('Configure')} className="self-center">
								<button
									class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
									type="button"
									aria-label={$i18n.t('Configure External IDP Passthrough')}
									data-testid="configure-external-idp"
									on:click={() => (showExternalApiModal = true)}
								>
									<Cog6 />
								</button>
							</Tooltip>
						</div>
					</div>
				</div>
			</div>
		</div>
	{:else}
		<div class="flex items-center justify-center h-full">
			<Spinner />
		</div>
	{/if}
</div>

<!-- Teams 봇 설정 모달 -->
<Modal size="md" bind:show={showTeamsBotModal}>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('Microsoft Teams')}
			</div>
			<button
				class="self-center"
				type="button"
				aria-label={$i18n.t('Close')}
				data-testid="teams-bot-modal-close"
				on:click={() => (showTeamsBotModal = false)}
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
		<hr class="border-gray-100 dark:border-gray-850" />
		<div class="px-5 py-4 max-h-[80vh] overflow-y-auto">
			<TeamsBotConfig {saveHandler} />
		</div>
	</div>
</Modal>

<!-- API 연동 설정 모달 -->
<Modal size="md" bind:show={showExternalApiModal}>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('External IDP Passthrough')}
			</div>
			<button
				class="self-center"
				type="button"
				aria-label={$i18n.t('Close')}
				data-testid="external-idp-modal-close"
				on:click={() => (showExternalApiModal = false)}
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
		<hr class="border-gray-100 dark:border-gray-850" />
		<div class="px-5 py-4 max-h-[80vh] overflow-y-auto">
			<ExternalApiConfig {saveHandler} />
		</div>
	</div>
</Modal>
