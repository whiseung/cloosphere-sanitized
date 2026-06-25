<script lang="ts">
	import { getContext } from 'svelte';
	import { fly } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { toastHistory, unreadToastCount, type ToastHistoryItem } from '$lib/stores/toast-history';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	let showPanel = false;
	let panelEl: HTMLDivElement;
	let buttonEl: HTMLButtonElement;

	// Resize from bottom-left
	let panelWidth = 320;
	let panelHeight = 384;
	let resizing = false;
	let resizeStartX = 0;
	let resizeStartY = 0;
	let resizeStartW = 0;
	let resizeStartH = 0;

	function onResizeStart(e: MouseEvent) {
		e.preventDefault();
		resizing = true;
		resizeStartX = e.clientX;
		resizeStartY = e.clientY;
		resizeStartW = panelWidth;
		resizeStartH = panelHeight;
		window.addEventListener('mousemove', onResizeMove);
		window.addEventListener('mouseup', onResizeEnd);
	}

	function onResizeMove(e: MouseEvent) {
		if (!resizing) return;
		panelWidth = Math.max(280, Math.min(resizeStartW - (e.clientX - resizeStartX), window.innerWidth - 32));
		panelHeight = Math.max(200, Math.min(resizeStartH + (e.clientY - resizeStartY), window.innerHeight - 80));
	}

	function onResizeEnd() {
		resizing = false;
		window.removeEventListener('mousemove', onResizeMove);
		window.removeEventListener('mouseup', onResizeEnd);
	}

	$: items = $toastHistory;
	$: unreadCount = $unreadToastCount;

	function togglePanel() {
		showPanel = !showPanel;
		if (showPanel) {
			toastHistory.markAllRead();
		}
	}

	function handleClickOutside(e: MouseEvent) {
		if (showPanel && panelEl && !panelEl.contains(e.target as Node) && !buttonEl.contains(e.target as Node)) {
			showPanel = false;
		}
	}

	function formatTime(ts: number): string {
		const now = Date.now();
		const diff = now - ts;
		if (diff < 60000) return $i18n.t('Just now');
		if (diff < 3600000) {
			const m = Math.floor(diff / 60000);
			return `${m}m`;
		}
		if (diff < 86400000) {
			const h = Math.floor(diff / 3600000);
			return `${h}h`;
		}
		return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}

	function typeIcon(type: ToastHistoryItem['type']): string {
		switch (type) {
			case 'success': return '✓';
			case 'error': return '✕';
			case 'warning': return '!';
			case 'info': return 'i';
			case 'running': return '⟳';
			default: return '';
		}
	}

	function copyMessage(message: string) {
		navigator.clipboard.writeText(message);
	}

	function progressPercent(p: { current: number | null; total: number | null } | null | undefined): number {
		if (!p || !p.total || p.total <= 0) return 0;
		return Math.min(100, Math.round(((p.current ?? 0) / p.total) * 100));
	}

	function openLink(linkTo: string | null | undefined) {
		if (!linkTo) return;
		showPanel = false;
		goto(linkTo);
	}
</script>

<svelte:window on:click={handleClickOutside} />

<div class="relative">
	<Tooltip content={$i18n.t('Notifications')}>
		<button
			bind:this={buttonEl}
			class="select-none flex rounded-xl p-1.5 hover:bg-gray-50 dark:hover:bg-gray-850 transition relative"
			aria-label={$i18n.t('Notifications')}
			on:click={togglePanel}
		>
			<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-5">
				<path stroke-linecap="round" stroke-linejoin="round" d="M14.857 17.082a23.848 23.848 0 0 0 5.454-1.31A8.967 8.967 0 0 1 18 9.75V9A6 6 0 0 0 6 9v.75a8.967 8.967 0 0 1-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 0 1-5.714 0m5.714 0a3 3 0 1 1-5.714 0" />
			</svg>
			{#if unreadCount > 0}
				<span class="absolute -top-0.5 -right-0.5 flex items-center justify-center size-4 text-[10px] font-bold text-white bg-red-500 rounded-full">
					{unreadCount > 9 ? '9+' : unreadCount}
				</span>
			{/if}
		</button>
	</Tooltip>

	{#if showPanel}
		<div
			bind:this={panelEl}
			transition:fly={{ y: -8, duration: 150 }}
			class="absolute right-0 top-10 overflow-hidden flex flex-col bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-xl z-50"
			style="width: {panelWidth}px; height: {panelHeight}px;"
		>
			<!-- Header -->
			<div class="flex items-center justify-between px-3 py-2.5 border-b border-gray-100 dark:border-gray-800">
				<span class="text-sm font-semibold dark:text-gray-100">{$i18n.t('Notifications')}</span>
				{#if items.length > 0}
					<button
						class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
						on:click={() => toastHistory.clear()}
					>
						{$i18n.t('Clear all')}
					</button>
				{/if}
			</div>

			<!-- List -->
			<div class="overflow-y-auto flex-1">
				{#if items.length === 0}
					<div class="flex items-center justify-center h-24 text-sm text-gray-400 dark:text-gray-500">
						{$i18n.t('No notifications')}
					</div>
				{:else}
					{#each items as item (item.id)}
						<div class="group flex items-start gap-2 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-850 border-b border-gray-50 dark:border-gray-800 last:border-b-0">
							<!-- Type indicator -->
							<span
								class="flex-shrink-0 flex items-center justify-center size-5 rounded-full text-[10px] font-bold mt-0.5
									{item.type === 'success' ? 'bg-green-100 text-green-600 dark:bg-green-900/30 dark:text-green-400' : ''}
									{item.type === 'error' ? 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400' : ''}
									{item.type === 'warning' ? 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400' : ''}
									{item.type === 'info' ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400' : ''}
									{item.type === 'running' ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400 animate-spin' : ''}"
							>
								{typeIcon(item.type)}
							</span>

							<!-- Content -->
							<button
								type="button"
								class="flex-1 min-w-0 text-left {item.linkTo ? 'cursor-pointer' : 'cursor-default'}"
								on:click={() => openLink(item.linkTo)}
								disabled={!item.linkTo}
							>
								<p class="text-xs text-gray-700 dark:text-gray-300 break-words line-clamp-3 whitespace-pre-line">
									{item.message}
								</p>
								{#if item.progress && (item.progress.current !== null || item.progress.total)}
									<div class="mt-1.5 h-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
										<div
											class="h-full bg-blue-500 dark:bg-blue-400 transition-all duration-300"
											style="width: {progressPercent(item.progress)}%"
										></div>
									</div>
									<!-- 1줄: 진행수(오류수)/전체수 -->
									{#if item.progress.total}
										<div class="mt-0.5 text-[10px] text-gray-400 dark:text-gray-500 tabular-nums">{item.progress.current ?? 0}{#if item.progress.failed}<span class="text-red-500 dark:text-red-400">({item.progress.failed})</span>{/if}/{item.progress.total}</div>
									{/if}
									<!-- 2줄: 진행 중 문서명 -->
									{#if item.progress.label}
										<div class="text-[10px] text-gray-400 dark:text-gray-500 truncate">{item.progress.label}</div>
									{/if}
								{/if}
								<span class="text-[10px] text-gray-400 dark:text-gray-500">{formatTime(item.timestamp)}</span>
							</button>

							<!-- Actions -->
							<div class="flex-shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition">
								<button
									class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
									title={$i18n.t('Copy')}
									on:click={() => copyMessage(item.message)}
								>
									<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9.75a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
									</svg>
								</button>
								<button
									class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
									title={$i18n.t('Dismiss')}
									on:click={() => toastHistory.remove(item.id)}
								>
									<svg xmlns="http://www.w3.org/2000/svg" class="size-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
									</svg>
								</button>
							</div>
						</div>
					{/each}
				{/if}
			</div>

			<!-- Resize handle (bottom-left) -->
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="absolute bottom-0 left-0 w-4 h-4 cursor-nesw-resize z-10"
				on:mousedown={onResizeStart}
			>
				<svg viewBox="0 0 16 16" class="size-3 m-0.5 text-gray-400 dark:text-gray-600 opacity-50 rotate-90">
					<path d="M2 14L14 2M6 14L14 6M10 14L14 10" stroke="currentColor" stroke-width="1.5" fill="none" />
				</svg>
			</div>
		</div>
	{/if}
</div>
