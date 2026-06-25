<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { EmbedAgentSummary } from '$lib/apis/embed-widgets';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let prompt = '';
	export let disabled = false;
	export let fileUploadEnabled = false;
	export let sendButtonColor = '';
	export let sendButtonIconColor = '';
	export let sendButtonIconUrl = '';
	export let agents: EmbedAgentSummary[] = [];
	export let activeAgentId: string = '';

	$: isSendActive = !!(prompt.trim() || files.length > 0);
	$: isSvgIcon = sendButtonIconUrl?.startsWith('data:image/svg+xml');
	$: inlineSvgHtml = isSvgIcon
		? decodeURIComponent(sendButtonIconUrl.replace('data:image/svg+xml;utf8,', ''))
		: '';

	$: activeAgent = agents.find((a) => a.id === activeAgentId);
	$: multipleAgentsAvailable = agents.length > 1;

	let textareaElement: HTMLTextAreaElement;
	let fileInputElement: HTMLInputElement;
	let files: File[] = [];

	// 슬래시 커맨드 상태: 입력의 마지막 토큰이 `/` 로 시작하면 에이전트 피커 표시
	let pickerSelectedIdx = 0;

	$: lastToken = prompt.split(/\s/).pop() ?? '';
	$: showAgentPicker =
		multipleAgentsAvailable && lastToken.startsWith('/');
	$: pickerQuery = showAgentPicker ? lastToken.slice(1).toLowerCase() : '';
	$: filteredAgents = pickerQuery
		? agents.filter(
				(a) =>
					a.name.toLowerCase().includes(pickerQuery) ||
					a.id.toLowerCase().includes(pickerQuery)
			)
		: agents;
	$: if (showAgentPicker) {
		pickerSelectedIdx = Math.min(pickerSelectedIdx, Math.max(filteredAgents.length - 1, 0));
	}

	const selectAgent = (agent: EmbedAgentSummary) => {
		activeAgentId = agent.id;
		// 입력에서 마지막 `/...` 토큰 제거
		const tokens = prompt.split(/\s/);
		tokens.pop();
		prompt = tokens.join(' ').trimEnd();
		pickerSelectedIdx = 0;
		textareaElement?.focus();
	};

	const submitHandler = () => {
		if (!prompt.trim() && files.length === 0) return;
		dispatch('submit', { prompt: prompt.trim(), files });
		prompt = '';
		files = [];
		if (textareaElement) {
			textareaElement.style.height = 'auto';
		}
	};

	const handleKeyDown = (e: KeyboardEvent) => {
		if (showAgentPicker && filteredAgents.length > 0) {
			if (e.key === 'ArrowDown') {
				e.preventDefault();
				pickerSelectedIdx = Math.min(pickerSelectedIdx + 1, filteredAgents.length - 1);
				return;
			}
			if (e.key === 'ArrowUp') {
				e.preventDefault();
				pickerSelectedIdx = Math.max(0, pickerSelectedIdx - 1);
				return;
			}
			if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
				e.preventDefault();
				selectAgent(filteredAgents[pickerSelectedIdx]);
				return;
			}
			if (e.key === 'Escape') {
				e.preventDefault();
				// `/` 토큰을 그냥 지워서 피커 닫기
				const tokens = prompt.split(/\s/);
				tokens.pop();
				prompt = tokens.join(' ').trimEnd();
				return;
			}
		}

		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submitHandler();
		}
	};

	const handleInput = () => {
		if (textareaElement) {
			textareaElement.style.height = 'auto';
			textareaElement.style.height = Math.min(textareaElement.scrollHeight, 150) + 'px';
		}
	};

	const handleFileSelect = (e: Event) => {
		const input = e.target as HTMLInputElement;
		if (input.files) {
			files = [...files, ...Array.from(input.files)];
		}
		input.value = '';
	};

	const removeFile = (index: number) => {
		files = files.filter((_, i) => i !== index);
	};
</script>

<div class="relative border-t border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] p-3">
	<!-- Agent picker popup (슬래시 커맨드 자동완성) -->
	{#if showAgentPicker && filteredAgents.length > 0}
		<div
			class="absolute bottom-full left-3 right-3 mb-2 z-20 rounded-xl border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] shadow-lg max-h-56 overflow-y-auto"
		>
			<div class="px-3 py-1.5 text-[10px] uppercase tracking-wider text-[var(--cloo-text-muted)] border-b border-[var(--cloo-border-subtle)]">
				{$i18n.t('Switch agent')}
			</div>
			{#each filteredAgents as agent, idx}
				<button
					type="button"
					class="w-full flex items-center gap-2 px-3 py-2 text-left text-sm text-[var(--cloo-text-default)] hover:bg-[var(--cloo-bg-neutral-hovered)] {idx === pickerSelectedIdx ? 'bg-[var(--cloo-bg-neutral-hovered)]' : ''}"
					on:click={() => selectAgent(agent)}
					on:mousemove={() => (pickerSelectedIdx = idx)}
				>
					{#if agent.profile_image_url}
						<img src={agent.profile_image_url} alt="" class="size-5 rounded-full shrink-0" />
					{:else}
						<div class="size-5 rounded-full bg-[var(--cloo-bg-neutral-hovered)] shrink-0" />
					{/if}
					<span class="truncate flex-1">{agent.name}</span>
					{#if agent.id === activeAgentId}
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5 text-[var(--cloo-color-primary)] shrink-0">
							<path fill-rule="evenodd" d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z" clip-rule="evenodd" />
						</svg>
					{/if}
				</button>
			{/each}
		</div>
	{/if}

	<!-- Active agent 인디케이터 (여러 에이전트 있고 피커 숨겨진 상태일 때) -->
	{#if multipleAgentsAvailable && !showAgentPicker && activeAgent}
		<div class="flex items-center gap-1 mb-1.5 text-[11px] text-[var(--cloo-text-muted)]">
			{#if activeAgent.profile_image_url}
				<img src={activeAgent.profile_image_url} alt="" class="size-3.5 rounded-full" />
			{/if}
			<span class="truncate">{activeAgent.name}</span>
			<span class="text-[10px] opacity-60">· {$i18n.t('type / to switch')}</span>
		</div>
	{/if}

	<!-- File previews -->
	{#if files.length > 0}
		<div class="flex flex-wrap gap-1.5 mb-2">
			{#each files as file, i}
				<div
					class="flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--cloo-bg-default)] text-xs"
				>
					<span class="truncate max-w-[120px]">{file.name}</span>
					<button
						class="text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]"
						on:click={() => removeFile(i)}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
							<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
						</svg>
					</button>
				</div>
			{/each}
		</div>
	{/if}

	<div class="flex items-center gap-2">
		{#if fileUploadEnabled}
			<button
				class="shrink-0 p-1.5 rounded-lg text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)] hover:bg-[var(--cloo-bg-neutral-hovered)] transition"
				{disabled}
				on:click={() => fileInputElement?.click()}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
					<path fill-rule="evenodd" d="M15.621 4.379a3 3 0 0 0-4.242 0l-7 7a3 3 0 0 0 4.241 4.243h.001l.497-.5a.75.75 0 0 1 1.064 1.057l-.498.501-.002.002a4.5 4.5 0 0 1-6.364-6.364l7-7a4.5 4.5 0 0 1 6.368 6.36l-3.455 3.553A2.625 2.625 0 1 1 9.52 9.52l3.45-3.451a.75.75 0 1 1 1.061 1.06l-3.45 3.451a1.125 1.125 0 0 0 1.587 1.595l3.454-3.553a3 3 0 0 0 0-4.242Z" clip-rule="evenodd" />
				</svg>
			</button>
			<input
				bind:this={fileInputElement}
				type="file"
				multiple
				class="hidden"
				on:change={handleFileSelect}
			/>
		{/if}

		<textarea
			bind:this={textareaElement}
			bind:value={prompt}
			{disabled}
			placeholder={$i18n.t('Send a message...')}
			class="flex-1 resize-none bg-transparent text-sm text-[var(--cloo-text-default)] placeholder-[var(--cloo-text-muted)] outline-none max-h-[150px] py-0.5 leading-[20px]"
			rows="1"
			on:keydown={handleKeyDown}
			on:input={handleInput}
		/>

		<button
			class="shrink-0 p-1.5 rounded-lg transition send-button flex items-center justify-center"
			style="background-color: {sendButtonColor || '#171717'}; color: {sendButtonIconColor || '#ffffff'}; opacity: {isSendActive ? 1 : 0.5};"
			disabled={disabled || (!prompt.trim() && files.length === 0)}
			on:click={submitHandler}
		>
			{#if isSvgIcon}
				<div class="size-5">{@html inlineSvgHtml}</div>
			{:else if sendButtonIconUrl}
				<img src={sendButtonIconUrl} alt="" class="size-5 object-contain" />
			{:else}
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
					<path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z" />
				</svg>
			{/if}
		</button>
	</div>
</div>
