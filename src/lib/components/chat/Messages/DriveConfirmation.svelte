<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		confirmDriveCreate,
		type DriveConfirmResponse
	} from '$lib/apis/google-actions';

	import Document from '$lib/components/icons/Document.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	type Payload = {
		message_id: string;
		// 항상 'low' — 내 드라이브 생성은 외부 도달이 없음 (분기하지 않음, 표시용).
		risk_level: 'low';
		draft: {
			name: string;
			content: string;
			folder_id?: string | null;
		};
	};

	export let payload: Payload;
	export let conversationId: string | null = null;

	// ---------- Editable draft state ----------
	let draftName = payload.draft.name || '';
	let draftContent = payload.draft.content || '';
	let draftFolderId = payload.draft.folder_id || '';

	// Cooldown (Gmail/Calendar 패턴 — 동일 confirm 후 5초 동안 재생성 차단).
	let cooldownActive = false;

	// 생성 상태.
	let sending = false;
	let finalState: '' | 'created' | 'already_created' | 'previously_failed' | 'error' = '';
	let finalMessage = '';
	let resultLink = '';

	$: canSend =
		!sending &&
		!cooldownActive &&
		finalState === '' &&
		draftName.trim().length > 0;

	// ---------- Submit / Cancel ----------
	async function handleCreate() {
		if (!canSend) return;
		sending = true;
		cooldownActive = true;
		try {
			const result: DriveConfirmResponse = await confirmDriveCreate(
				localStorage.token,
				payload.message_id,
				{
					name: draftName,
					content: draftContent,
					folder_id: draftFolderId.trim() ? draftFolderId.trim() : null,
					conversation_id: conversationId
				}
			);
			finalState = result.status;
			resultLink = result.web_link || '';
			if (result.status === 'created') {
				finalMessage = $i18n.t('Document created successfully');
				toast.success(finalMessage);
			} else if (result.status === 'already_created') {
				finalMessage = $i18n.t('Document was already created earlier');
				toast.info(finalMessage);
			} else {
				finalMessage =
					result.error ||
					$i18n.t('Previous attempt failed; please start a new draft.');
				toast.warning(finalMessage);
			}
			dispatch('confirmed', result);
		} catch (e) {
			finalState = 'error';
			finalMessage =
				(e as { detail?: string; message?: string })?.detail ||
				(e as { message?: string })?.message ||
				$i18n.t('Failed to create document');
			toast.error(finalMessage);
		} finally {
			sending = false;
			setTimeout(() => {
				cooldownActive = false;
			}, 5000);
		}
	}

	function handleCancel() {
		finalState = 'previously_failed';
		finalMessage = $i18n.t('Document creation cancelled');
		toast.info(finalMessage);
		dispatch('cancelled');
	}
</script>

<div
	class="my-3 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm"
>
	<!-- Header -->
	<div class="flex items-center gap-2 mb-3">
		<div class="shrink-0 text-[var(--cloo-color-accent)]">
			<Document className="size-5" strokeWidth="2" />
		</div>
		<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
			{$i18n.t('Confirm Document')}
		</h3>
	</div>

	{#if finalState}
		<div
			class="text-sm py-3 text-center {finalState === 'created'
				? 'text-green-600 dark:text-green-400'
				: finalState === 'error'
					? 'text-red-600 dark:text-red-400'
					: 'text-gray-600 dark:text-gray-400'}"
		>
			{finalMessage}
			{#if resultLink}
				<div class="mt-1">
					<a
						href={resultLink}
						target="_blank"
						rel="noopener noreferrer"
						class="text-xs text-[var(--cloo-color-accent)] hover:underline"
					>
						{$i18n.t('Open in Google Drive')}
					</a>
				</div>
			{/if}
		</div>
	{:else}
		<div class="space-y-3">
			<!-- Name -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Title')}
				</div>
				<input
					type="text"
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)]"
					bind:value={draftName}
				/>
			</div>

			<!-- Content -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Content')}
				</div>
				<textarea
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)] resize-y min-h-[140px]"
					bind:value={draftContent}
				></textarea>
			</div>

			<!-- Folder ID (optional) -->
			<div>
				<div class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
					{$i18n.t('Folder ID (optional)')}
				</div>
				<input
					type="text"
					class="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 outline-hidden focus:border-[var(--cloo-color-accent)]"
					placeholder={$i18n.t('Leave empty to create in My Drive')}
					bind:value={draftFolderId}
				/>
			</div>

			<!-- Actions -->
			<div class="flex justify-end gap-2 pt-1">
				<button
					type="button"
					class="text-sm px-4 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 disabled:opacity-50"
					on:click={handleCancel}
					disabled={sending}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					type="button"
					class="text-sm px-4 py-1.5 rounded-lg bg-[var(--cloo-color-accent)] hover:bg-[var(--cloo-color-accent-hover)] text-white disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:text-gray-500 dark:disabled:text-gray-400 disabled:cursor-not-allowed"
					on:click={handleCreate}
					disabled={!canSend}
				>
					{#if sending}
						{$i18n.t('Creating...')}
					{:else if cooldownActive && finalState === ''}
						{$i18n.t('Please wait...')}
					{:else}
						{$i18n.t('Create Document')}
					{/if}
				</button>
			</div>
		</div>
	{/if}
</div>
