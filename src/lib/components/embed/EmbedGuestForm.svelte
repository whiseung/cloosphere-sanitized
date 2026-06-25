<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { requestGuestToken } from '$lib/apis/embed-widgets';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher<{ login: { token: string } }>();

	export let baseUrl: string = '';
	export let widgetId: string = '';
	export let widgetName: string = '';
	export let guestConfig: Record<string, any> = {};

	let name = '';
	let email = '';
	let submitting = false;

	$: requiredFields = (guestConfig.required_fields as string[]) || ['name'];
	$: optionalFields = (guestConfig.optional_fields as string[]) || ['email'];
	$: allFields = [...new Set([...requiredFields, ...optionalFields])];
	$: showName = allFields.includes('name');
	$: showEmail = allFields.includes('email');
	$: nameRequired = requiredFields.includes('name');
	$: emailRequired = requiredFields.includes('email');

	const handleSubmit = async () => {
		if (nameRequired && !name.trim()) {
			toast.error($i18n.t('Please enter your name'));
			return;
		}
		if (emailRequired && !email.trim()) {
			toast.error($i18n.t('Please enter your email'));
			return;
		}

		submitting = true;
		try {
			const resp = await requestGuestToken(baseUrl, widgetId, {
				name: name.trim() || undefined,
				email: email.trim() || undefined,
				origin_url: window.location.href,
				referrer: document.referrer || undefined
			});
			if (resp?.token) {
				dispatch('login', { token: resp.token });
			} else {
				toast.error($i18n.t('Failed to start session'));
			}
		} catch (err: any) {
			toast.error(err?.message || err || $i18n.t('Failed to start session'));
		} finally {
			submitting = false;
		}
	};
</script>

<div class="flex flex-col items-center justify-center h-full p-6 bg-[var(--cloo-bg-default)]">
	<div class="w-full max-w-sm">
		<div class="text-center mb-6">
			<div class="text-lg font-semibold text-[var(--cloo-text-default)]">
				{widgetName || $i18n.t('Chat')}
			</div>
			<div class="text-xs text-[var(--cloo-text-muted)] mt-1">
				{$i18n.t('Enter your info to start chatting')}
			</div>
		</div>

		<form class="space-y-2" on:submit|preventDefault={handleSubmit}>
			{#if showName}
				<input
					type="text"
					bind:value={name}
					placeholder={$i18n.t('Name') + (nameRequired ? ' *' : '')}
					required={nameRequired}
					class="w-full px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-sm text-[var(--cloo-text-default)] outline-none focus:border-[var(--cloo-color-primary)]"
				/>
			{/if}
			{#if showEmail}
				<input
					type="email"
					bind:value={email}
					placeholder={$i18n.t('Email') + (emailRequired ? ' *' : '')}
					required={emailRequired}
					class="w-full px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-sm text-[var(--cloo-text-default)] outline-none focus:border-[var(--cloo-color-primary)]"
				/>
			{/if}
			<button
				type="submit"
				disabled={submitting}
				class="w-full px-4 py-2.5 rounded-lg bg-[var(--cloo-color-primary)] text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
			>
				{submitting ? $i18n.t('Starting...') : $i18n.t('Start Chatting')}
			</button>
		</form>
	</div>
</div>
