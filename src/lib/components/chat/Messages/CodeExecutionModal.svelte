<script lang="ts">
	import { getContext } from 'svelte';
	import { saveAs } from 'file-saver';
	import CodeBlock from './CodeBlock.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	const i18n = getContext('i18n');

	export let show = false;
	export let codeExecution = null;

	const downloadOutput = () => {
		if (!codeExecution?.result?.output) return;
		const blob = new Blob([codeExecution.result.output], { type: 'text/plain;charset=utf-8' });
		saveAs(blob, `code-output-${codeExecution.id?.slice(0, 8) || 'result'}.txt`);
	};

	const copyOutput = () => {
		if (!codeExecution?.result?.output) return;
		navigator.clipboard.writeText(codeExecution.result.output);
	};
</script>

<Modal size="lg" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center flex flex-col gap-0.5 capitalize">
				{#if codeExecution?.result}
					<div>
						{#if codeExecution.result?.error}
							<Badge type="error" content="error" />
						{:else if codeExecution.result?.output}
							<Badge type="success" content="success" />
						{:else}
							<Badge type="warning" content="incomplete" />
						{/if}
					</div>
				{/if}

				<div class="flex gap-2 items-center">
					{#if !codeExecution?.result}
						<div>
							<Spinner className="size-4" />
						</div>
					{/if}

					<div>
						{#if codeExecution?.name}
							{$i18n.t('Code execution')}: {codeExecution?.name}
						{:else}
							{$i18n.t('Code execution')}
						{/if}
					</div>
				</div>
			</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
					codeExecution = null;
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

		<div class="flex flex-col md:flex-row w-full px-4 pb-5">
			<div
				class="flex flex-col w-full dark:text-gray-200 overflow-y-scroll max-h-[22rem] scrollbar-hidden"
			>
				<div class="flex flex-col w-full">
					<CodeBlock
						id="code-exec-{codeExecution?.id}-code"
						lang={codeExecution?.language ?? ''}
						code={codeExecution?.code ?? ''}
						className=""
						editorClassName={codeExecution?.result &&
						(codeExecution?.result?.error || codeExecution?.result?.output)
							? 'rounded-b-none'
							: ''}
						stickyButtonsClassName="top-0"
						run={false}
					/>
				</div>

				{#if codeExecution?.result && (codeExecution?.result?.error || codeExecution?.result?.output)}
					<div class="dark:bg-[#202123] dark:text-white px-4 py-4 rounded-b-lg flex flex-col gap-3">
						{#if codeExecution?.result?.error}
							<div>
								<div class=" text-gray-500 text-xs mb-1">{$i18n.t('ERROR')}</div>
								<div class="text-sm">{codeExecution?.result?.error}</div>
							</div>
						{/if}
						{#if codeExecution?.result?.output}
							<div>
								<div class="flex items-center justify-between mb-1">
									<div class="text-gray-500 text-xs">{$i18n.t('OUTPUT')}</div>
									<div class="flex gap-1">
										<Tooltip content={$i18n.t('Copy')}>
											<button
												class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition"
												on:click={copyOutput}
											>
												<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
													<path stroke-linecap="round" stroke-linejoin="round" d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9.75a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184" />
												</svg>
											</button>
										</Tooltip>
										<Tooltip content={$i18n.t('Download')}>
											<button
												class="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-700 transition"
												on:click={downloadOutput}
											>
												<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
													<path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3" />
												</svg>
											</button>
										</Tooltip>
									</div>
								</div>
								<div class="text-sm whitespace-pre-wrap font-mono bg-gray-100 dark:bg-gray-800 rounded p-2 max-h-60 overflow-y-auto">{codeExecution?.result?.output}</div>
							</div>
						{/if}
					</div>
				{/if}
				{#if codeExecution?.result?.files && codeExecution?.result?.files.length > 0}
					<div class="flex flex-col w-full">
						<hr class="border-gray-100 dark:border-gray-850 my-2" />
						<div class=" text-sm font-medium dark:text-gray-300">
							{$i18n.t('Files')}
						</div>
						<ul class="mt-1 list-disc pl-4 text-xs">
							{#each codeExecution?.result?.files as file}
								<li>
									<a href={file.url} target="_blank">{file.name}</a>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
			</div>
		</div>
	</div>
</Modal>
