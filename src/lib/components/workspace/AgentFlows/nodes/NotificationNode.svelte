<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	// Node props from @xyflow/svelte
	export let id: string = '';
	export let data: any = {};
	export let selected: boolean = false;
	export let selectable: boolean = true;
	export let deletable: boolean = true;
	export let draggable: boolean = true;
	export let dragging: boolean = false;
	export let dragHandle: string | undefined = undefined;
	export let type: string = '';
	export let zIndex: number = 0;
	export let parentId: string | undefined = undefined;
	export let isConnectable: boolean = true;
	export let positionAbsoluteX: number = 0;
	export let positionAbsoluteY: number = 0;
	export let sourcePosition: string | undefined = undefined;
	export let targetPosition: string | undefined = undefined;
	export let width: number | undefined = undefined;
	export let height: number | undefined = undefined;

	// notification type: email, slack, teams, discord, google_chat
	$: notificationType = data?.config?.type || 'email';
</script>

<div
	class="flow-node px-4 py-3 rounded-xl border-2 min-w-[180px]
		{selected ? 'border-sky-500 shadow-lg' : 'border-sky-400'}
		bg-sky-50 dark:bg-sky-900/30"
>
	<Handle type="target" position={Position.Top} class="!w-3 !h-3 !bg-sky-500 !border-2 !border-white dark:!border-gray-800" />

	<div class="flex items-center gap-2">
		<div class="w-8 h-8 rounded-full bg-sky-500 flex items-center justify-center">
			{#if notificationType === 'email'}
				<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
				</svg>
			{:else if notificationType === 'slack'}
				<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
					<path d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zM6.313 15.165a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313zM8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zM8.834 6.313a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312zM18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zM17.688 8.834a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312zM15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zM15.165 17.688a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"/>
				</svg>
			{:else if notificationType === 'teams'}
				<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
					<path d="M20.625 8.073c.574 0 1.125.224 1.531.623.407.4.635.941.635 1.507v4.316c0 .566-.228 1.108-.635 1.507a2.179 2.179 0 0 1-1.531.623h-.938v2.277c0 .188-.075.368-.21.502a.72.72 0 0 1-.507.207.72.72 0 0 1-.508-.207.707.707 0 0 1-.21-.502V16.65h-3.127a2.179 2.179 0 0 1-1.531-.623 2.122 2.122 0 0 1-.635-1.507V10.2c0-.566.228-1.108.635-1.507a2.179 2.179 0 0 1 1.531-.623h5.5zm-6.188 2.127v4.32c0 .187.074.368.208.502.134.133.316.208.506.208h3.127v-5.03h-3.127a.72.72 0 0 0-.506.208.707.707 0 0 0-.208.502v-.71zm6.188-.71h-.938v5.03h.938a.72.72 0 0 0 .506-.208.707.707 0 0 0 .208-.502V10.2a.707.707 0 0 0-.208-.502.72.72 0 0 0-.506-.208zM11.438 5c.573 0 1.124.224 1.53.623.407.4.636.941.636 1.507v7.39c0 .566-.229 1.108-.635 1.507a2.179 2.179 0 0 1-1.531.623H3.96a2.179 2.179 0 0 1-1.531-.623A2.122 2.122 0 0 1 1.793 14.52V7.13c0-.566.228-1.108.635-1.507A2.179 2.179 0 0 1 3.96 5h7.477zm0 1.42H3.96a.72.72 0 0 0-.506.207.707.707 0 0 0-.208.502v7.39c0 .188.074.369.208.503a.72.72 0 0 0 .506.207h7.477a.72.72 0 0 0 .506-.207.707.707 0 0 0 .208-.502V7.13a.707.707 0 0 0-.208-.502.72.72 0 0 0-.506-.208z"/>
				</svg>
			{:else if notificationType === 'discord'}
				<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
					<path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
				</svg>
			{:else if notificationType === 'google_chat'}
				<svg class="w-4 h-4 text-white" viewBox="0 0 24 24" fill="currentColor">
					<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
					<path d="M22 4L12 14.01l-3-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
				</svg>
			{:else}
				<svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
				</svg>
			{/if}
		</div>
		<div class="flex-1 min-w-0">
			<div class="text-xs font-semibold text-sky-700 dark:text-sky-300">
				{$i18n?.t?.('Notification') || 'Notification'}
			</div>
			<div class="text-[10px] text-sky-600 dark:text-sky-400 truncate">
				{#if notificationType === 'email'}
					{data?.label || $i18n?.t?.('Send Email') || 'Send Email'}
				{:else if notificationType === 'slack'}
					{data?.label || $i18n?.t?.('Send to Slack') || 'Send to Slack'}
				{:else if notificationType === 'teams'}
					{data?.label || $i18n?.t?.('Send to Teams') || 'Send to Teams'}
				{:else if notificationType === 'discord'}
					{data?.label || $i18n?.t?.('Send to Discord') || 'Send to Discord'}
				{:else if notificationType === 'google_chat'}
					{data?.label || $i18n?.t?.('Send to Google Chat') || 'Send to Google Chat'}
				{:else}
					{data?.label || $i18n?.t?.('Send Notification') || 'Send Notification'}
				{/if}
			</div>
		</div>
	</div>

	{#if !data?.config?.type}
		<div class="mt-2 text-[10px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
			<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
			</svg>
			{$i18n?.t?.('Not configured') || 'Not configured'}
		</div>
	{/if}

	<Handle type="source" position={Position.Bottom} class="!w-3 !h-3 !bg-sky-500 !border-2 !border-white dark:!border-gray-800" />
</div>

<style>
	.flow-node { transition: all 0.2s ease; }
	.flow-node:hover { transform: translateY(-1px); }
</style>
