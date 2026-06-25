<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { getNotificationChannelList } from '$lib/apis/notifications';
	import type { NotificationChannelList } from '$lib/apis/notifications';
	import { models } from '$lib/stores';
	import Selector from '$lib/components/common/Selector.svelte';

	const i18n = getContext('i18n');

	export let notifications: any[] = [];
	export let titleTemplate: string = ''; // kept for backward compat but no longer shown at top
	export let targetModelId: string = '';

	let channels: NotificationChannelList = { emails: [], webhooks: [] };
	let loaded = false;

	// Track last focused template input for variable insertion
	type TemplateField = 'title_template' | 'subject_template' | 'body_template' | 'message_template';
	let lastFocusedInput: HTMLInputElement | HTMLTextAreaElement | null = null;
	let lastFocusedNotifIndex: number = -1;
	let lastFocusedField: TemplateField | 'title_template' | null = null;

	// Ref for title template input
	let titleTemplateInput: HTMLInputElement;

	function trackFocus(
		el: HTMLInputElement | HTMLTextAreaElement,
		notifIndex: number,
		field: TemplateField
	) {
		lastFocusedInput = el;
		lastFocusedNotifIndex = notifIndex;
		lastFocusedField = field;
	}

	function trackTitleFocus(el: HTMLInputElement) {
		lastFocusedInput = el;
		lastFocusedNotifIndex = -1;
		lastFocusedField = 'title_template';
	}

	function insertVariable(variable: string) {
		if (!lastFocusedInput || !lastFocusedField) {
			// Fallback: copy to clipboard
			navigator.clipboard.writeText(variable);
			return;
		}

		const el = lastFocusedInput;
		const start = el.selectionStart ?? el.value.length;
		const end = el.selectionEnd ?? el.value.length;
		const before = el.value.slice(0, start);
		const after = el.value.slice(end);
		const newVal = before + variable + after;

		if (lastFocusedField === 'title_template') {
			titleTemplate = newVal;
		} else if (lastFocusedNotifIndex >= 0) {
			notifications[lastFocusedNotifIndex][lastFocusedField] = newVal;
			notifications = [...notifications];
		}

		// Restore cursor position after the inserted text
		requestAnimationFrame(() => {
			el.focus();
			const pos = start + variable.length;
			el.setSelectionRange(pos, pos);
		});
	}

	// Extract structured output schema fields from the selected model
	$: structuredFields = (() => {
		if (!targetModelId) return [];
		const model = $models.find((m) => m.id === targetModelId);
		const rf = (model?.info?.meta as any)?.responseFormat;
		if (rf?.type !== 'json_schema' || !rf?.json_schema?.schema?.properties) return [];
		return extractSchemaFields(rf.json_schema.schema, 'result');
	})();

	function extractSchemaFields(schema: any, prefix: string): Array<{ name: string; path: string }> {
		const fields: Array<{ name: string; path: string }> = [];
		if (!schema?.properties) return fields;
		for (const [key, value] of Object.entries(schema.properties) as [string, any][]) {
			const path = prefix ? `${prefix}.${key}` : key;
			fields.push({ name: key, path });
			if (value.type === 'object' && value.properties) {
				fields.push(...extractSchemaFields(value, path));
			}
		}
		return fields;
	}

	onMount(async () => {
		try {
			channels = await getNotificationChannelList(localStorage.token);
		} catch {
			// Silently fail
		}
		loaded = true;
	});

	$: hasEmailChannels = channels.emails.length > 0;
	$: hasWebhookChannels = channels.webhooks.length > 0;
	$: channelTypeItems = [
		...(hasEmailChannels ? [{ value: 'email', label: $i18n.t('Email') }] : []),
		...(hasWebhookChannels ? [{ value: 'webhook', label: $i18n.t('Webhook') }] : []),
		{ value: 'webhook_url', label: $i18n.t('Direct URL') }
	];
	$: triggerItems = [
		{ value: 'always', label: $i18n.t('Always') },
		{ value: 'on_success', label: $i18n.t('On success') },
		{ value: 'on_failure', label: $i18n.t('On failure') }
	];

	// Check if any notification uses template fields
	$: hasTemplateInputs = notifications.some(
		(n) =>
			n.channel_type === 'email' || n.channel_type === 'webhook' || n.channel_type === 'webhook_url'
	);

	function addNotification() {
		if (hasEmailChannels) {
			notifications = [
				...notifications,
				{
					channel_type: 'email',
					channel_name: channels.emails[0].name,
					trigger: 'always',
					title_template: '[{{schedule_name}}] {{result.title}}',
					recipients: [],
					subject_template: $i18n.t('[{{schedule_name}}] Result'),
					body_template: '{{result}}'
				}
			];
		} else if (hasWebhookChannels) {
			notifications = [
				...notifications,
				{
					channel_type: 'webhook',
					channel_name: channels.webhooks[0].name,
					trigger: 'always',
					title_template: '[{{schedule_name}}] {{result.title}}',
					message_template: ''
				}
			];
		} else {
			notifications = [
				...notifications,
				{
					channel_type: 'webhook_url',
					webhook_url: '',
					trigger: 'always',
					title_template: '[{{schedule_name}}] {{result.title}}',
					message_template: ''
				}
			];
		}
	}

	function removeNotification(index: number) {
		notifications = notifications.filter((_, i) => i !== index);
	}

	function handleTypeChange(index: number) {
		const type = notifications[index].channel_type;
		const trigger = notifications[index].trigger || 'always';
		const title_template =
			notifications[index].title_template || '[{{schedule_name}}] {{result.title}}';
		if (type === 'email') {
			notifications[index] = {
				channel_type: 'email',
				channel_name: hasEmailChannels ? channels.emails[0].name : '',
				trigger,
				title_template,
				recipients: [],
				subject_template: $i18n.t('[{{schedule_name}}] Result'),
				body_template: '{{result}}'
			};
		} else if (type === 'webhook') {
			notifications[index] = {
				channel_type: 'webhook',
				channel_name: hasWebhookChannels ? channels.webhooks[0].name : '',
				trigger,
				title_template,
				message_template: ''
			};
		} else {
			notifications[index] = {
				channel_type: 'webhook_url',
				webhook_url: '',
				trigger,
				title_template,
				message_template: ''
			};
		}
		notifications = [...notifications];
	}

	let recipientInputs: { [key: number]: string } = {};

	function addRecipient(index: number) {
		const email = (recipientInputs[index] || '').trim();
		if (email && !notifications[index].recipients.includes(email)) {
			notifications[index].recipients = [...notifications[index].recipients, email];
			notifications = [...notifications];
		}
		recipientInputs[index] = '';
	}

	function removeRecipient(notifIndex: number, recipientIndex: number) {
		notifications[notifIndex].recipients = notifications[notifIndex].recipients.filter(
			(_: string, i: number) => i !== recipientIndex
		);
		notifications = [...notifications];
	}
</script>

{#if loaded}
	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between">
			<div class="text-sm">{$i18n.t('Notifications (optional)')}</div>
			<button
				type="button"
				class="text-xs px-2 py-1 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
				on:click={addNotification}
			>
				+ {$i18n.t('Add Notification')}
			</button>
		</div>

		{#if notifications.length === 0}
			<div class="text-xs text-gray-400 dark:text-gray-500 py-2">
				{$i18n.t(
					'Chat history will always be saved. Add notifications to also receive results via email or webhook.'
				)}
			</div>
		{/if}

		{#each notifications as notif, index}
			<div class="rounded-lg border border-gray-200 dark:border-gray-700 p-3 flex flex-col gap-2">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2 flex-1 min-w-0">
						<!-- Channel type -->
						<div class="w-[128px] shrink-0">
							<Selector
								items={channelTypeItems}
								value={notif.channel_type}
								searchEnabled={false}
								size="sm"
								on:change={(e) => {
									notifications[index].channel_type = e.detail.value;
									notifications = [...notifications];
									handleTypeChange(index);
								}}
							/>
						</div>

						<!-- Channel name or URL -->
						{#if notif.channel_type === 'email'}
							<div class="flex-1 min-w-0">
								<Selector
									items={channels.emails.map((ch) => ({
										value: ch.name,
										label: `${ch.name} (${ch.engine})`
									}))}
									value={notif.channel_name}
									size="sm"
									on:change={(e) => {
										notifications[index].channel_name = e.detail.value;
										notifications = [...notifications];
									}}
								/>
							</div>
						{:else if notif.channel_type === 'webhook'}
							<div class="flex-1 min-w-0">
								<Selector
									items={channels.webhooks.map((ch) => ({
										value: ch.name,
										label: `${ch.name} (${ch.provider})`
									}))}
									value={notif.channel_name}
									size="sm"
									on:change={(e) => {
										notifications[index].channel_name = e.detail.value;
										notifications = [...notifications];
									}}
								/>
							</div>
						{:else if notif.channel_type === 'webhook_url'}
							<input
								type="url"
								class="rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden flex-1 min-w-0"
								bind:value={notif.webhook_url}
								placeholder="https://hooks.slack.com/..."
							/>
						{/if}

						<!-- Trigger condition -->
						<div class="w-[130px] shrink-0">
							<Selector
								items={triggerItems}
								value={notif.trigger}
								searchEnabled={false}
								size="sm"
								on:change={(e) => {
									notifications[index].trigger = e.detail.value;
									notifications = [...notifications];
								}}
							/>
						</div>
					</div>

					<button
						type="button"
						class="text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition shrink-0"
						on:click={() => removeNotification(index)}
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 20 20"
							fill="currentColor"
							class="w-4 h-4"
						>
							<path
								d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
							/>
						</svg>
					</button>
				</div>

				<!-- Title template (all notification types) -->
				<div>
					<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
						{$i18n.t('Title template')}
					</div>
					<input
						type="text"
						class="w-full rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						bind:value={notif.title_template}
						placeholder={'[{{schedule_name}}] {{result.title}}'}
						on:focus={(e) => trackFocus(e.currentTarget, index, 'title_template')}
					/>
				</div>

				{#if notif.channel_type === 'email'}
					<!-- Recipients -->
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Recipients')}
						</div>
						<div class="flex flex-wrap gap-1 mb-1.5">
							{#each notif.recipients || [] as recipient, rIdx}
								<span
									class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300"
								>
									{recipient}
									<button
										type="button"
										class="hover:text-red-500 dark:hover:text-red-400"
										on:click={() => removeRecipient(index, rIdx)}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 16 16"
											fill="currentColor"
											class="w-3 h-3"
										>
											<path
												d="M5.28 4.22a.75.75 0 00-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 101.06 1.06L8 9.06l2.72 2.72a.75.75 0 101.06-1.06L9.06 8l2.72-2.72a.75.75 0 00-1.06-1.06L8 6.94 5.28 4.22z"
											/>
										</svg>
									</button>
								</span>
							{/each}
						</div>
						<div class="flex gap-1">
							<input
								type="email"
								class="flex-1 rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
								placeholder="email@example.com"
								bind:value={recipientInputs[index]}
								on:keydown={(e) => {
									if (e.key === 'Enter') {
										e.preventDefault();
										addRecipient(index);
									}
								}}
							/>
							<button
								type="button"
								class="text-xs px-2 py-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 transition"
								on:click={() => addRecipient(index)}
							>
								{$i18n.t('Add')}
							</button>
						</div>
					</div>

					<!-- Subject template -->
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Subject template')}
						</div>
						<input
							type="text"
							class="w-full rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							bind:value={notif.subject_template}
							placeholder={$i18n.t('[{{schedule_name}}] Result')}
							on:focus={(e) => trackFocus(e.currentTarget, index, 'subject_template')}
						/>
					</div>

					<!-- Body template -->
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Body template')}
						</div>
						<textarea
							class="w-full resize-none rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							rows="3"
							bind:value={notif.body_template}
							placeholder={'{{result}}'}
							on:focus={(e) => trackFocus(e.currentTarget, index, 'body_template')}
						/>
					</div>
				{/if}

				{#if notif.channel_type === 'webhook' || notif.channel_type === 'webhook_url'}
					<!-- Webhook message template -->
					<div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">
							{$i18n.t('Message template')}
							<span class="text-gray-400 dark:text-gray-500">({$i18n.t('optional')})</span>
						</div>
						<textarea
							class="w-full resize-none rounded-lg py-1.5 px-3 text-xs bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							rows="2"
							bind:value={notif.message_template}
							placeholder={$i18n.t('Leave empty to send full result')}
							on:focus={(e) => trackFocus(e.currentTarget, index, 'message_template')}
						/>
					</div>
				{/if}
			</div>
		{/each}

		<!-- Template variable hints -->
		<div class="rounded-lg bg-gray-50 dark:bg-gray-900 p-2.5 flex flex-col gap-1.5">
			<div class="text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('Template variables')}
				<span class="text-gray-400 dark:text-gray-500"
					>— {$i18n.t('Click to insert into template')}</span
				>
			</div>
			<div class="flex flex-wrap gap-1">
				{#each ['{{schedule_name}}', '{{prompt}}', '{{result}}', '{{completed_at}}'] as v}
					<button
						type="button"
						class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-700 transition cursor-pointer"
						on:click={() => insertVariable(v)}
					>
						{v}
					</button>
				{/each}
			</div>

			{#if structuredFields.length > 0}
				<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
					{$i18n.t('Structured Output fields')}
					<span class="text-gray-400 dark:text-gray-500"
						>— {$i18n.t('Use individual JSON fields from the agent response')}</span
					>
				</div>
				<div class="flex flex-wrap gap-1">
					{#each structuredFields as field}
						<button
							type="button"
							class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition cursor-pointer"
							on:click={() => insertVariable(`{{${field.path}}}`)}
						>
							{`{{${field.path}}}`}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{/if}
