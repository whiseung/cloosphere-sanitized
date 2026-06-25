<script lang="ts">
	import { settings, playingNotificationSound, isLastActiveTab } from '$lib/stores';
	import { brandingUrls } from '$lib/stores/branding';
	import DOMPurify from 'dompurify';

	import { marked } from 'marked';
	import { createEventDispatcher, onMount } from 'svelte';

	const dispatch = createEventDispatcher();

	export let onClick: Function = () => {};
	export let title: string = 'HI';
	export let content: string;

	onMount(() => {
		if (!navigator.userActivation.hasBeenActive) {
			return;
		}

		if ($settings?.notificationSound ?? true) {
			if (!$playingNotificationSound && $isLastActiveTab) {
				playingNotificationSound.set(true);

				const audio = new Audio(`/audio/notification.mp3`);
				audio.play().finally(() => {
					// Ensure the global state is reset after the sound finishes
					playingNotificationSound.set(false);
				});
			}
		}
	});
</script>

<button
	class="flex gap-2.5 text-left min-w-[var(--width)] w-full bg-[var(--cloo-bg-surface)] text-[var(--cloo-text-default)] border border-[var(--cloo-border-subtle)] rounded-xl px-3.5 py-3.5"
	on:click={() => {
		onClick();
		dispatch('closeToast');
	}}
>
	<div class="shrink-0 self-top -translate-y-0.5">
		<img src={$brandingUrls.favicon} alt="favicon" class="size-7 rounded-full dark:hidden" />
		<img src={$brandingUrls.faviconDark} alt="favicon" class="size-7 rounded-full hidden dark:block" />
	</div>

	<div>
		{#if title}
			<div class=" text-[13px] font-medium mb-0.5 line-clamp-1 capitalize">{title}</div>
		{/if}

		<div class=" line-clamp-2 text-xs self-center text-[var(--cloo-text-muted)] font-normal">
			{@html DOMPurify.sanitize(marked(content))}
		</div>
	</div>
</button>
