<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { getContext } from 'svelte';
	import { fade } from 'svelte/transition';

	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	import { guideChat } from '$lib/apis/guide';
	import { models } from '$lib/stores';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { formatBackendError } from '$lib/utils/error';

	function renderMarkdown(text: any): string {
		// Gemini/Vertex AI may return content as array instead of string
		if (Array.isArray(text)) {
			text = text
				.map((block: any) => (typeof block === 'object' ? block?.text ?? '' : String(block)))
				.join('');
		}
		if (typeof text !== 'string') {
			text = String(text ?? '');
		}
		return DOMPurify.sanitize(marked.parse(text) as string);
	}

	const i18n = getContext('i18n');

	export let show = false;

	let query = '';
	let loading = false;
	let selectedModelId = '';
	let showModelSelector = true;
	let messages: { role: string; content: string }[] = [];
	let messagesContainer: HTMLElement;

	$: modelItems = ($models ?? [])
		.filter((m: any) => {
			if (m.info?.meta?.hidden) return false;
			// 플로우 제외
			if (m.owned_by === 'flow' || m.owned_by === 'agent_flow') return false;
			// 에이전트 제외 (base_model_id가 있으면 에이전트)
			if (m.info?.base_model_id) return false;
			return true;
		})
		.map((m: any) => ({ value: m.id, label: m.name || m.id }));

	$: selectedModelLabel =
		modelItems.find((m: any) => m.value === selectedModelId)?.label ?? selectedModelId;

	async function handleSubmit() {
		if (!query.trim() || loading) return;
		if (!selectedModelId) {
			toast.error($i18n.t('Please select a model.'));
			return;
		}

		const userMessage = query.trim();
		query = '';
		messages = [...messages, { role: 'user', content: userMessage }];
		loading = true;
		scrollToBottom();

		try {
			const result = await guideChat(localStorage.token, messages, selectedModelId);
			if (result?.assistant_message) {
				messages = [...messages, { role: 'assistant', content: result.assistant_message }];
				scrollToBottom();
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to get answer'));
			messages = messages.slice(0, -1);
		} finally {
			loading = false;
		}
	}

	function scrollToBottom() {
		setTimeout(() => {
			if (messagesContainer) {
				messagesContainer.scrollTop = messagesContainer.scrollHeight;
			}
		}, 50);
	}

	function clearChat() {
		messages = [];
		query = '';
	}

	// Resize from bottom-left corner
	let panelEl: HTMLElement;
	let panelWidth = 520;
	let panelHeight = 600;
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
		// left drag: moving left increases width
		panelWidth = Math.max(320, Math.min(resizeStartW - (e.clientX - resizeStartX), window.innerWidth - 32));
		// down drag: increases height
		panelHeight = Math.max(400, Math.min(resizeStartH + (e.clientY - resizeStartY), window.innerHeight - 80));
	}

	function onResizeEnd() {
		resizing = false;
		window.removeEventListener('mousemove', onResizeMove);
		window.removeEventListener('mouseup', onResizeEnd);
	}
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 z-[9998]"
		transition:fade={{ duration: 100 }}
		on:click={() => (show = false)}
	/>

	<div
		bind:this={panelEl}
		class="fixed z-[9999] flex flex-col bg-[var(--cloo-bg-surface)] border border-[var(--cloo-border-default)] rounded-2xl shadow-2xl overflow-hidden
			right-2 top-14 sm:right-4 sm:top-16"
		style="width: min({panelWidth}px, calc(100vw - 1rem)); height: min({panelHeight}px, calc(100dvh - 4rem));"
		transition:fade={{ duration: 150 }}
	>
		<!-- Header -->
		<div class="flex items-center justify-between px-4 py-3 border-b border-[var(--cloo-border-subtle)]">
			<div class="flex items-center gap-2">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="size-5 text-[var(--cloo-color-primary)]"
				>
					<path
						fill-rule="evenodd"
						d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM8.94 6.94a.75.75 0 1 1-1.061-1.061 3 3 0 1 1 2.871 5.026v.345a.75.75 0 0 1-1.5 0v-.5c0-.72.57-1.172 1.081-1.287A1.5 1.5 0 1 0 8.94 6.94ZM10 15a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
						clip-rule="evenodd"
					/>
				</svg>
				<span class="font-semibold text-sm">{$i18n.t('Guide Q&A')}</span>
			</div>
			<div class="flex items-center gap-1">
				{#if messages.length > 0}
					<Tooltip content={$i18n.t('Clear')} placement="bottom">
						<Button kind="text" size="sm" on:click={clearChat}>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
								<path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.519.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5Z" clip-rule="evenodd" />
							</svg>
						</Button>
					</Tooltip>
				{/if}
				<Button kind="text" size="sm" on:click={() => (show = false)}>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
						<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
					</svg>
				</Button>
			</div>
		</div>

		<!-- Model Selector -->
		<div class="px-4 py-2 border-b border-[var(--cloo-border-subtle)]">
			<Selector
				value={selectedModelId}
				items={modelItems}
				placeholder={$i18n.t('Select Model')}
				size="sm"
				searchEnabled
				portal={null}
				on:change={(e) => {
					selectedModelId = e.detail.value;
				}}
			/>
		</div>

		<!-- Messages -->
		<div
			bind:this={messagesContainer}
			class="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-[160px]"
		>
			{#if messages.length === 0}
				<div class="text-center py-8">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="currentColor"
						class="size-10 mx-auto mb-3 text-[var(--cloo-text-muted)] opacity-40"
					>
						<path
							fill-rule="evenodd"
							d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.29 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.68-3.348 3.97a48.901 48.901 0 0 1-3.476.383.39.39 0 0 0-.297.17l-2.755 4.133a.75.75 0 0 1-1.248 0l-2.755-4.133a.39.39 0 0 0-.297-.17 48.9 48.9 0 0 1-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97ZM6.025 7.5a.75.75 0 0 1 .75-.75h10.5a.75.75 0 0 1 0 1.5H6.775a.75.75 0 0 1-.75-.75Zm.75 2.25a.75.75 0 0 0 0 1.5h7.5a.75.75 0 0 0 0-1.5h-7.5Z"
							clip-rule="evenodd"
						/>
					</svg>
					<p class="text-sm text-[var(--cloo-text-muted)]">
						{$i18n.t('Ask anything about Cloosphere features')}
					</p>
					<div class="mt-3 flex flex-wrap justify-center gap-1.5">
						{#each [$i18n.t('How to create an agent?'), $i18n.t('What is a guardrail?'), $i18n.t('How to set up Code Gateway?')] as suggestion}
							<Button
								kind="outlined"
								size="sm"
								on:click={() => {
									query = suggestion;
									handleSubmit();
								}}
							>
								{suggestion}
							</Button>
						{/each}
					</div>
				</div>
			{:else}
				{#each messages as msg}
					<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
						<div
							class="max-w-[85%] rounded-2xl px-3.5 py-2 text-sm {msg.role === 'user'
								? 'bg-[var(--cloo-color-primary)] text-[var(--cloo-color-on-primary)]'
								: 'bg-[var(--cloo-bg-neutral-hovered)]'}"
						>
							{#if msg.role === 'assistant'}
								<div class="prose prose-sm dark:prose-invert max-w-none">{@html renderMarkdown(msg.content)}</div>
							{:else}
								<div class="whitespace-pre-wrap">{msg.content}</div>
							{/if}
						</div>
					</div>
				{/each}
				{#if loading}
					<div class="flex justify-start">
						<div class="rounded-2xl px-3.5 py-2 bg-[var(--cloo-bg-neutral-hovered)]">
							<Spinner className="size-4" />
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Input -->
		<div class="px-4 py-3 border-t border-[var(--cloo-border-subtle)]">
			<div class="flex gap-2 items-end">
				<div class="flex-1">
					<Input
						bind:value={query}
						placeholder={$i18n.t('Ask a question...')}
						size="sm"
						disabled={loading}
						on:keydown={(e) => {
							const event = e.detail;
							if (event.key === 'Enter' && !event.shiftKey) {
								event.preventDefault();
								handleSubmit();
							}
						}}
					/>
				</div>
				<Button
					kind="filled"
					size="sm"
					disabled={!query.trim() || loading}
					on:click={handleSubmit}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
						<path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.154.75.75 0 0 0 0-1.115A28.897 28.897 0 0 0 3.105 2.288Z" />
					</svg>
				</Button>
			</div>

			<!-- Resize handle (bottom-left) -->
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="absolute bottom-0 left-0 w-4 h-4 cursor-nesw-resize z-10"
				on:mousedown={onResizeStart}
			>
				<svg viewBox="0 0 16 16" fill="currentColor" class="size-3 m-0.5 text-[var(--cloo-text-muted)] opacity-50 rotate-90">
					<path d="M2 14L14 2M6 14L14 6M10 14L14 10" stroke="currentColor" stroke-width="1.5" fill="none" />
				</svg>
			</div>
		</div>
	</div>
{/if}
