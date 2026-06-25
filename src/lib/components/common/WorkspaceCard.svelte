<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { brandingUrls } from '$lib/stores/branding';

	export let id: string = '';
	export let profileImage: string | null | undefined = undefined;
	export let showAvatar: boolean = false;
	export let name: string = '';
	export let description: string = '';
	export let isActive: boolean = true;
	export let className: string = '';

	const dispatch = createEventDispatcher<{ click: void }>();

	function handleCardClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		if (target.closest('[data-no-card-click]')) {
			return;
		}
		dispatch('click');
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' || e.key === ' ') {
			const target = e.target as HTMLElement;
			if (target.closest('[data-no-card-click]')) {
				return;
			}
			e.preventDefault();
			dispatch('click');
		}
	}
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<div
	{id}
	class="workspace-card {className}"
	role="button"
	tabindex="0"
	on:click={handleCardClick}
	on:keydown={handleKeydown}
>
	<!-- Top Row: Badge + Actions -->
	<div class="flex items-center justify-between">
		<div class="flex items-center gap-1">
			<slot name="badge" />
		</div>

		<div class="flex items-center gap-2.5" data-no-card-click>
			<slot name="actions" />
		</div>
	</div>

	<!-- Middle Row: Avatar + Title + Description -->
	<div class="flex items-center gap-[var(--cloo-space-4)] py-[var(--cloo-space-4)]">
		{#if showAvatar}
			<div
				class="shrink-0 size-[44px] rounded-full border border-[var(--cloo-surface-border)] bg-[var(--cloo-bg-surface)] overflow-hidden {isActive
					? ''
					: 'opacity-50'}"
			>
				<img
					src={profileImage ?? $brandingUrls.favicon}
					alt="{name} profile"
					class="size-full object-cover"
				/>
			</div>
		{/if}

		<div class="flex-1 min-w-0 {isActive ? '' : 'opacity-50'}">
			<slot name="title">
				<div class="text-base font-semibold leading-6 text-[var(--cloo-text-primary)] line-clamp-1">
					{name}
				</div>
			</slot>

			<div class="text-sm leading-5 text-[var(--cloo-text-muted)] line-clamp-2 min-h-[2.5rem]">
				{#if description.trim()}
					{description}
				{:else}
					<slot name="description-fallback" />
				{/if}
			</div>
		</div>
	</div>

	{#if $$slots.meta}
		<div class="pb-[var(--cloo-space-3)] min-w-0">
			<slot name="meta" />
		</div>
	{/if}

	<!-- Bottom Row -->
	<div class="flex items-center justify-between gap-[var(--cloo-space-2)] flex-wrap">
		<div class="min-w-0 flex-1">
			<slot name="footer-left" />
		</div>

		<div class="ml-auto shrink-0" data-no-card-click>
			<slot name="footer-right" />
		</div>
	</div>
</div>
