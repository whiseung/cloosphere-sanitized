<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import { onMount, onDestroy, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { goto, afterNavigate } from '$app/navigation';
	import { page } from '$app/stores';
	import { config, user, mobile, showSidebar, models, projectsLastUpdated } from '$lib/stores';

	import { uploadFile } from '$lib/apis/files';
	import {
		getProjectById,
		getProjectChatList,
		updateProjectById,
		deleteProjectById,
		addFileToProjectById,
		removeFileFromProjectById,
		removeChatFromProject,
		shareProject
	} from '$lib/apis/projects';
	import { deleteChatById } from '$lib/apis/chats';
	import { getKnowledgeById } from '$lib/apis/knowledge';

	import { createPicker } from '$lib/utils/google-drive-picker';
	import { pickAndDownloadFile } from '$lib/utils/onedrive-file-picker';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import ShareModal from '$lib/components/common/ShareModal.svelte';
	import SharePointBrowser from '$lib/components/common/SharePointBrowser.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import AddFilesPlaceholder from '$lib/components/AddFilesPlaceholder.svelte';

	let id: string | null = null;
	let project: any = null;
	let loading = true;

	let activeTab: 'chat' | 'settings' = 'chat';

	let showDeleteConfirmModal = false;
	let showSharePointBrowser = false;
	let showShareModal = false;

	let inputFiles: FileList | null = null;
	let dragged = false;

	let editingName = false;
	let instructionsDirty = false;

	$: isOwner = project?.user_id === $user?.id;

	// React to route param changes (same component reused across project navigations)
	$: if ($page.params.id && $page.params.id !== id) {
		id = $page.params.id;
		loading = true;
		project = null;
		activeTab = 'chat';
		loadProject()
			.then(() => loadProjectChats())
			.then(() => {
				loading = false;
			});
	}

	// Reset to chat tab on same-route navigation (e.g., clicking sidebar while on settings tab)
	afterNavigate(({ from, to }) => {
		if (from?.url?.pathname === to?.url?.pathname) {
			activeTab = 'chat';
		}
	});

	// Default model
	let defaultModelId = '';

	// Share
	let sharedUserIds: string[] = [];

	// Chat tab state
	let projectChats: {
		id: string;
		title: string;
		preview: string;
		updated_at: number;
		created_at: number;
	}[] = [];

	// Polling cleanup
	let activePollingIntervals: ReturnType<typeof setInterval>[] = [];
	const stopPolling = (interval: ReturnType<typeof setInterval>) => {
		clearInterval(interval);
		activePollingIntervals = activePollingIntervals.filter((i) => i !== interval);
	};
	onDestroy(() => {
		activePollingIntervals.forEach(clearInterval);
	});

	// File upload handler
	const DATA_ANALYSIS_EXTENSIONS = ['csv', 'xlsx', 'xls', 'tsv', 'parquet'];

	const uploadFileHandler = async (file: File) => {
		// Data analysis projects: require default model + restrict file types
		if (project.type === 'data_analysis') {
			if (!defaultModelId) {
				toast.error(
					$i18n.t('Please select a default model in Settings before uploading data files.')
				);
				return null;
			}

			const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
			if (!DATA_ANALYSIS_EXTENSIONS.includes(ext)) {
				toast.error(
					$i18n.t('Only data files are allowed: {{types}}', {
						types: DATA_ANALYSIS_EXTENSIONS.join(', ').toUpperCase()
					})
				);
				return null;
			}
		}

		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: '',
			name: file.name,
			size: file.size,
			status: 'uploading',
			error: '',
			itemId: tempItemId
		};

		if (fileItem.size == 0) {
			toast.error($i18n.t('You cannot upload an empty file.'));
			return null;
		}

		if (
			($config?.file?.max_size ?? null) !== null &&
			file.size > ($config?.file?.max_size ?? 0) * 1024 * 1024
		) {
			toast.error(
				$i18n.t(`File size should not exceed {{maxSize}} MB.`, {
					maxSize: $config?.file?.max_size
				})
			);
			return;
		}

		project.files = [...(project.files ?? []), fileItem];

		try {
			const uploadedFile = await uploadFile(
				localStorage.token,
				file,
				'local',
				false,
				'project'
			).catch((e) => {
				toast.error($i18n.t(`${e}`));
				return null;
			});

			if (uploadedFile) {
				project.files = project.files.map((item: any) => {
					if (item.itemId === tempItemId) {
						item.id = uploadedFile.id;
					}
					delete item.itemId;
					return item;
				});
				await addFileHandler(uploadedFile.id);
			} else {
				toast.error($i18n.t('Failed to upload file.'));
				project.files = project.files.filter((item: any) => item.itemId !== tempItemId);
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const addFileHandler = async (fileId: string) => {
		const result = await addFileToProjectById(localStorage.token, id!, fileId).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (result) {
			if (result.status === 'processing' || result.status === 'processing_started') {
				project.files = project.files.map((file: any) => {
					if (file.id === fileId) {
						return { ...file, status: 'processing' };
					}
					return file;
				});
				toast.info(
					result.message ||
						$i18n.t('File is being processed. It will be added automatically when ready.')
				);

				// 안전망 폴: 프로젝트의 내부 KB 를 직접 조회한다. getProjectById 는
				// (1) 백엔드 stale 복구(처리 timeout 초과 → failed)를 트리거하지 못하고
				// (2) 실패한 파일을 완료와 구분하지 못한다. KB 조회는 둘 다 해결한다.
				// 종료 판정은 pending_files 기준(KB UI 폴러와 동일) — stale-복구로 실패한
				// 고아 작업도 pending 에서 빠지므로 잡힌다.
				const pollInterval = setInterval(async () => {
					const kb = project.knowledge_id
						? await getKnowledgeById(localStorage.token, project.knowledge_id, true).catch(
								() => null
							)
						: null;
					if (!kb) return;

					// 아직 처리 중(pending)이면 계속 폴링
					if ((kb.pending_files ?? []).some((f: any) => f.id === fileId)) return;

					// pending 아님 → 종료. 완료 파일만 file_ids(kb.files)에 들어오고,
					// 실패(인프로세스/스테일)는 없거나 status='failed' 로 남는다.
					stopPolling(pollInterval);
					const kbFile = (kb.files ?? []).find((f: any) => f.id === fileId);
					const ok = !!kbFile && kbFile?.data?.processing_job?.status !== 'failed';
					await loadProject();
					if (ok) {
						toast.success($i18n.t('File processing completed.'));
					} else {
						toast.error($i18n.t('File processing failed.'));
					}
				}, 5000);
				activePollingIntervals.push(pollInterval);

				// Safety timeout: 30분 후 자동 중단 (대용량 DI 문서 대비)
				setTimeout(() => stopPolling(pollInterval), 1800000);
			} else {
				toast.success($i18n.t('File added successfully.'));
				await loadProject();
			}
		} else {
			toast.error($i18n.t('Failed to add file.'));
			project.files = project.files.filter((file: any) => file.id !== fileId);
		}
	};

	const deleteFileHandler = async (fileId: string) => {
		try {
			const result = await removeFileFromProjectById(localStorage.token, id!, fileId);
			if (result) {
				toast.success($i18n.t('File removed successfully.'));
				await loadProject();
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const saveSettings = async () => {
		if (!project) return;
		try {
			const res = await updateProjectById(localStorage.token, id!, {
				instructions: project.instructions,
				meta: { default_model_id: defaultModelId || null }
			});
			if (res) {
				instructionsDirty = false;
				toast.success($i18n.t('Project updated successfully.'));
			}
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const saveName = async () => {
		if (!project || !project.name.trim()) return;
		editingName = false;
		try {
			await updateProjectById(localStorage.token, id!, { name: project.name });
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const deleteProject = async () => {
		try {
			await deleteProjectById(localStorage.token, id!);
			$projectsLastUpdated = Date.now();
			toast.success($i18n.t('Project deleted successfully.'));
			goto('/');
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const startNewChat = () => {
		if (!project) return;
		sessionStorage.setItem(
			'projectContext',
			JSON.stringify({
				id: project.id,
				name: project.name,
				type: project.type || 'general',
				knowledge_id: project.type === 'data_analysis' ? null : project.knowledge_id,
				instructions: project.instructions,
				default_model_id: defaultModelId || null,
				file_metadata:
					project.type === 'data_analysis' ? project.data?.file_metadata ?? null : null
			})
		);
		goto('/');
	};

	const deleteChatFromProject = async (chatId: string) => {
		try {
			await deleteChatById(localStorage.token, chatId);
			await removeChatFromProject(localStorage.token, id!, chatId);
			projectChats = projectChats.filter((c) => c.id !== chatId);
			toast.success($i18n.t('Chat deleted successfully.'));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const saveSharedUsers = async () => {
		if (!project || sharedUserIds.length === 0) return;
		try {
			const res = await shareProject(localStorage.token, id!, sharedUserIds);
			showShareModal = false;
			sharedUserIds = [];
			toast.success($i18n.t('Project copied to {{count}} user(s)', { count: res.copied_count }));
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const loadProjectChats = async () => {
		if (!id) return;
		try {
			projectChats = (await getProjectChatList(localStorage.token, id)) ?? [];
		} catch (e) {
			console.error('Failed to load project chats:', e);
			projectChats = [];
		}
	};

	const formatChatDate = (timestamp: number) => {
		const date = new Date(timestamp * 1000);
		const now = new Date();
		const diff = now.getTime() - date.getTime();
		const days = Math.floor(diff / (1000 * 60 * 60 * 24));

		if (days === 0) {
			return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
		} else if (days === 1) {
			return $i18n.t('Yesterday');
		} else if (days < 7) {
			return $i18n.t('{{days}} days ago', { days });
		}
		return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
	};

	// Drag & drop handlers (only for settings tab, owner only)
	const onDragOver = (e: DragEvent) => {
		if (activeTab !== 'settings' || !isOwner) return;
		e.preventDefault();
		if (e.dataTransfer?.types?.includes('Files')) {
			dragged = true;
		}
	};

	const onDragLeave = () => {
		dragged = false;
	};

	const onDrop = async (e: DragEvent) => {
		if (activeTab !== 'settings' || !isOwner) return;
		e.preventDefault();
		dragged = false;
		if (e.dataTransfer?.files) {
			for (const file of e.dataTransfer.files) {
				await uploadFileHandler(file);
			}
		}
	};

	const loadProject = async () => {
		const res = await getProjectById(localStorage.token, id!).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});
		if (res) {
			project = res;
			defaultModelId = res.meta?.default_model_id || '';
			sharedUserIds = [];
		} else {
			goto('/');
		}
	};

	const formatFileSize = (bytes: number) => {
		if (!bytes) return '';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	};

	onMount(() => {
		const dropZone = document.querySelector('body');
		dropZone?.addEventListener('dragover', onDragOver);
		dropZone?.addEventListener('drop', onDrop);
		dropZone?.addEventListener('dragleave', onDragLeave);

		return () => {
			dropZone?.removeEventListener('dragover', onDragOver);
			dropZone?.removeEventListener('drop', onDrop);
			dropZone?.removeEventListener('dragleave', onDragLeave);
		};
	});
</script>

{#if dragged}
	<div
		class="fixed left-0 w-full h-full flex z-50 touch-none pointer-events-none"
		id="dropzone"
		role="region"
		aria-label="Drag and Drop Container"
	>
		<div class="absolute w-full h-full backdrop-blur-sm bg-gray-800/40 flex justify-center">
			<div class="m-auto pt-64 flex flex-col justify-center">
				<div class="max-w-md">
					<AddFilesPlaceholder>
						<div class="mt-2 text-center text-sm dark:text-gray-200 w-full">
							{$i18n.t('Drop any files here to add to the project')}
						</div>
					</AddFilesPlaceholder>
				</div>
			</div>
		</div>
	</div>
{/if}

<ConfirmDialog
	bind:show={showDeleteConfirmModal}
	message={$i18n.t('Are you sure you want to delete this project?')}
	on:confirm={deleteProject}
/>

<SharePointBrowser
	bind:show={showSharePointBrowser}
	on:select={async (e) => {
		const { files } = e.detail;
		for (const file of files) {
			await uploadFileHandler(file);
		}
	}}
	on:cancel={() => {
		showSharePointBrowser = false;
	}}
/>

<input
	id="project-files-input"
	bind:files={inputFiles}
	type="file"
	multiple
	hidden
	on:change={async () => {
		if (inputFiles && inputFiles.length > 0) {
			for (const file of inputFiles) {
				await uploadFileHandler(file);
			}
			inputFiles = null;
			const fileInputElement = document.getElementById('project-files-input');
			if (fileInputElement) {
				fileInputElement.value = '';
			}
		}
	}}
/>

{#if loading}
	<div class="flex justify-center items-center h-full">
		<Spinner />
	</div>
{:else if project}
	<!-- Share Modal -->
	<ShareModal
		bind:show={showShareModal}
		bind:selectedUserIds={sharedUserIds}
		description={$i18n.t('Selected users will receive an independent copy of this project.')}
		saveLabel="Copy to Users"
		on:save={saveSharedUsers}
	/>

	<div class="h-full w-full overflow-auto">
		<div class="flex flex-col w-full max-w-3xl mx-auto px-4 sm:px-6 py-8">
			<!-- Back Button -->
			<div class="mb-4">
				<button
					class="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
					on:click={() => goto('/')}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="w-4 h-4"
					>
						<path
							fill-rule="evenodd"
							d="M17 10a.75.75 0 01-.75.75H5.612l4.158 3.96a.75.75 0 11-1.04 1.08l-5.5-5.25a.75.75 0 010-1.08l5.5-5.25a.75.75 0 111.04 1.08L5.612 9.25H16.25A.75.75 0 0117 10z"
							clip-rule="evenodd"
						/>
					</svg>
					{$i18n.t('Back')}
				</button>
			</div>

			<!-- Project Name (large, like ChatGPT) -->
			<div class="mb-6">
				{#if editingName}
					<input
						class="text-2xl sm:text-3xl font-semibold font-primary w-full bg-transparent outline-hidden border-b border-gray-300 dark:border-gray-600 dark:text-white"
						bind:value={project.name}
						on:blur={saveName}
						on:keydown={(e) => {
							if (e.key === 'Enter') saveName();
						}}
						autofocus
					/>
				{:else}
					<div class="flex items-center gap-3">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-7 h-7 sm:w-8 sm:h-8 text-gray-500 dark:text-gray-400 shrink-0"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"
							/>
						</svg>
						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<h1
							class="text-2xl sm:text-3xl font-semibold font-primary dark:text-white {isOwner
								? 'cursor-pointer hover:opacity-70'
								: ''}"
							role={isOwner ? 'button' : undefined}
							tabindex={isOwner ? 0 : undefined}
							on:click={() => {
								if (isOwner) editingName = true;
							}}
						>
							{project.name}
							{#if project.meta?.copied_from}
								<span class="text-sm font-normal text-gray-400 dark:text-gray-500 ml-2"
									>({$i18n.t('from {{name}}', { name: project.meta.copied_from.user_name })})</span
								>
							{/if}
						</h1>
					</div>
				{/if}
			</div>

			<!-- New Chat Button (input-field style like ChatGPT) -->
			<button
				class="w-full flex items-center gap-3 px-4 py-3.5 rounded-full border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition mb-6 cursor-pointer"
				on:click={startNewChat}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="w-5 h-5 text-gray-400"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
				</svg>
				<span class="text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t('New chat in {{name}}', { name: project.name })}
				</span>
			</button>

			<!-- Tabs -->
			<div class="flex gap-1 mb-4">
				<button
					class="px-3 py-1.5 text-sm rounded-lg transition
						{activeTab === 'chat'
						? 'bg-gray-900 dark:bg-white text-white dark:text-black'
						: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'}"
					on:click={() => (activeTab = 'chat')}
				>
					{$i18n.t('Chat')}
				</button>
				<button
					class="px-3 py-1.5 text-sm rounded-lg transition
						{activeTab === 'settings'
						? 'bg-gray-900 dark:bg-white text-white dark:text-black'
						: 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'}"
					on:click={() => (activeTab = 'settings')}
				>
					{$i18n.t('Settings')}
				</button>
			</div>

			<!-- Chat Tab -->
			{#if activeTab === 'chat'}
				{#if projectChats.length === 0}
					<div class="flex flex-col items-center justify-center py-16 text-center">
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="w-12 h-12 text-gray-300 dark:text-gray-600 mb-3"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 0 1-.825-.242m9.345-8.334a2.126 2.126 0 0 0-.476-.095 48.64 48.64 0 0 0-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0 0 11.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155"
							/>
						</svg>
						<p class="text-sm text-gray-400 dark:text-gray-500">
							{$i18n.t('No chats yet')}
						</p>
						<p class="text-xs text-gray-300 dark:text-gray-600 mt-1">
							{$i18n.t('Start a new chat to begin')}
						</p>
					</div>
				{:else}
					<div class="divide-y divide-gray-100 dark:divide-gray-800">
						{#each projectChats as chat (chat.id)}
							<div
								class="w-full flex items-start justify-between px-2 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-850 rounded-lg transition text-left gap-4 group"
							>
								<button class="min-w-0 flex-1 text-left" on:click={() => goto(`/c/${chat.id}`)}>
									<div class="text-sm font-medium dark:text-white truncate">
										{chat.title || $i18n.t('New Chat')}
									</div>
									{#if chat.preview}
										<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 line-clamp-1">
											{chat.preview}
										</div>
									{/if}
								</button>
								<div class="flex items-center gap-1 shrink-0 pt-0.5">
									<div class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap">
										{formatChatDate(chat.updated_at)}
									</div>
									<Tooltip content={$i18n.t('Delete')}>
										<button
											class="opacity-0 group-hover:opacity-100 transition p-1 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg"
											on:click|stopPropagation={() => deleteChatFromProject(chat.id)}
										>
											<GarbageBin
												className="size-3.5 text-gray-400 hover:text-red-500 dark:text-gray-500 dark:hover:text-red-400"
												strokeWidth="1.5"
											/>
										</button>
									</Tooltip>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			{/if}

			<!-- Settings Tab -->
			{#if activeTab === 'settings'}
				<!-- Files Section -->
				<div class="mb-6">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-lg font-medium dark:text-white">
							{$i18n.t('Project Files')}
						</h2>
						{#if isOwner}
							<div class="flex items-center gap-2 flex-wrap">
								{#if $config?.features?.enable_sharepoint_integration}
									<Tooltip content={$i18n.t('Add from SharePoint')}>
										<button
											class="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
											on:click={() => (showSharePointBrowser = true)}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 32 32"
												class="w-4 h-4"
												fill="none"
											>
												<circle cx="16" cy="14" r="10" fill="#036C70" />
												<circle cx="10" cy="22" r="8" fill="#1A9BA1" />
												<circle cx="20" cy="24" r="6" fill="#37C6D0" />
											</svg>
											SharePoint
										</button>
									</Tooltip>
								{/if}

								{#if $config?.features?.enable_google_drive_integration}
									<Tooltip content={$i18n.t('Add from Google Drive')}>
										<button
											class="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
											on:click={async () => {
												try {
													const fileData = await createPicker();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													toast.error(
														$i18n.t('Error accessing Google Drive: {{error}}', {
															error: error.message
														})
													);
												}
											}}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87.3 78" class="w-4 h-4">
												<path
													d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z"
													fill="#0066da"
												/>
												<path
													d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z"
													fill="#00ac47"
												/>
												<path
													d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z"
													fill="#ea4335"
												/>
												<path
													d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z"
													fill="#00832d"
												/>
												<path
													d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z"
													fill="#2684fc"
												/>
												<path
													d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z"
													fill="#ffba00"
												/>
											</svg>
											Google Drive
										</button>
									</Tooltip>
								{/if}

								{#if $config?.features?.enable_onedrive_integration}
									<Tooltip content={$i18n.t('Add from OneDrive')}>
										<button
											class="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
											on:click={async () => {
												try {
													const fileData = await pickAndDownloadFile();
													if (fileData) {
														const file = new File([fileData.blob], fileData.name, {
															type: fileData.blob.type || 'application/octet-stream'
														});
														await uploadFileHandler(file);
													}
												} catch (error) {
													console.error('OneDrive Error:', error);
												}
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 32 32"
												class="w-4 h-4"
												fill="none"
											>
												<mask
													id="mask_od_proj"
													style="mask-type:alpha"
													maskUnits="userSpaceOnUse"
													x="0"
													y="6"
													width="32"
													height="20"
												>
													<path
														d="M7.82979 26C3.50549 26 0 22.5675 0 18.3333C0 14.1921 3.35322 10.8179 7.54613 10.6716C9.27535 7.87166 12.4144 6 16 6C20.6308 6 24.5169 9.12183 25.5829 13.3335C29.1316 13.3603 32 16.1855 32 19.6667C32 23.0527 29 26 25.8723 25.9914L7.82979 26Z"
														fill="#C4C4C4"
													/>
												</mask>
												<g mask="url(#mask_od_proj)">
													<path
														d="M7.83017 26.0001C5.37824 26.0001 3.18957 24.8966 1.75391 23.1691L18.0429 16.3335L30.7089 23.4647C29.5926 24.9211 27.9066 26.0001 26.0004 25.9915C23.1254 26.0001 12.0629 26.0001 7.83017 26.0001Z"
														fill="url(#paint0_od_proj)"
													/>
													<path
														d="M25.5785 13.3149L18.043 16.3334L30.709 23.4647C31.5199 22.4065 32.0004 21.0916 32.0004 19.6669C32.0004 16.1857 29.1321 13.3605 25.5833 13.3337C25.5817 13.3274 25.5801 13.3212 25.5785 13.3149Z"
														fill="url(#paint1_od_proj)"
													/>
													<path
														d="M7.06445 10.7028L18.0423 16.3333L25.5779 13.3148C24.5051 9.11261 20.6237 6 15.9997 6C12.4141 6 9.27508 7.87166 7.54586 10.6716C7.3841 10.6773 7.22358 10.6877 7.06445 10.7028Z"
														fill="url(#paint2_od_proj)"
													/>
													<path
														d="M1.7535 23.1687L18.0425 16.3331L7.06471 10.7026C3.09947 11.0792 0 14.3517 0 18.3331C0 20.1665 0.657197 21.8495 1.7535 23.1687Z"
														fill="url(#paint3_od_proj)"
													/>
												</g>
												<defs>
													<linearGradient
														id="paint0_od_proj"
														x1="4.42591"
														y1="24.6668"
														x2="27.2309"
														y2="23.2764"
														gradientUnits="userSpaceOnUse"
													>
														<stop stop-color="#2086B8" />
														<stop offset="1" stop-color="#46D3F6" />
													</linearGradient>
													<linearGradient
														id="paint1_od_proj"
														x1="23.8302"
														y1="19.6668"
														x2="30.2108"
														y2="15.2082"
														gradientUnits="userSpaceOnUse"
													>
														<stop stop-color="#1694DB" />
														<stop offset="1" stop-color="#62C3FE" />
													</linearGradient>
													<linearGradient
														id="paint2_od_proj"
														x1="8.51037"
														y1="7.33333"
														x2="23.3335"
														y2="15.9348"
														gradientUnits="userSpaceOnUse"
													>
														<stop stop-color="#0D3D78" />
														<stop offset="1" stop-color="#063B83" />
													</linearGradient>
													<linearGradient
														id="paint3_od_proj"
														x1="-0.340429"
														y1="19.9998"
														x2="14.5634"
														y2="14.4649"
														gradientUnits="userSpaceOnUse"
													>
														<stop stop-color="#16589B" />
														<stop offset="1" stop-color="#1464B7" />
													</linearGradient>
												</defs>
											</svg>
											OneDrive
										</button>
									</Tooltip>
								{/if}

								<button
									class="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
									on:click={() => {
										document.getElementById('project-files-input')?.click();
									}}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										fill="none"
										viewBox="0 0 24 24"
										stroke-width="2"
										stroke="currentColor"
										class="w-4 h-4"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M12 4.5v15m7.5-7.5h-15"
										/>
									</svg>
									{$i18n.t('Upload Files')}
								</button>
							</div>
						{/if}
					</div>

					{#if project.files && project.files.length > 0}
						<div
							class="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden divide-y divide-gray-200 dark:divide-gray-700"
						>
							{#each project.files as file (file.id || file.itemId)}
								<div
									class="flex items-center justify-between px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								>
									<div class="flex items-center gap-3 min-w-0 flex-1">
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="1.5"
											stroke="currentColor"
											class="w-5 h-5 shrink-0 text-gray-400"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
											/>
										</svg>
										<div class="min-w-0">
											<div class="text-sm truncate dark:text-white">
												{file.meta?.name || file.name || 'Untitled'}
											</div>
											<div class="text-xs text-gray-400">
												{#if file.status === 'uploading'}
													{$i18n.t('Uploading...')}
												{:else if file.status === 'processing'}
													{$i18n.t('Processing...')}
												{:else}
													{formatFileSize(file.meta?.size || file.size || 0)}
												{/if}
											</div>
										</div>
									</div>
									{#if isOwner && file.id && file.status !== 'uploading' && file.status !== 'processing'}
										<button
											class="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition text-gray-400 hover:text-red-500"
											on:click={() => deleteFileHandler(file.id)}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="2"
												stroke="currentColor"
												class="w-4 h-4"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M6 18 18 6M6 6l12 12"
												/>
											</svg>
										</button>
									{:else if file.status === 'uploading' || file.status === 'processing'}
										<div class="p-1.5">
											<svg
												class="w-4 h-4 animate-spin text-gray-400"
												viewBox="0 0 24 24"
												fill="currentColor"
												xmlns="http://www.w3.org/2000/svg"
											>
												<style>
													.spinner_proj {
														transform-origin: center;
														animation: spinner_proj_anim 0.75s infinite linear;
													}
													@keyframes spinner_proj_anim {
														100% {
															transform: rotate(360deg);
														}
													}
												</style>
												<path
													d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
													opacity=".25"
												/>
												<path
													d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
													class="spinner_proj"
												/>
											</svg>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{:else}
						<div
							class="border border-dashed border-gray-300 dark:border-gray-600 rounded-xl p-8 text-center"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="w-10 h-10 mx-auto text-gray-300 dark:text-gray-600 mb-2"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12H9.75m3 0v3.75m0-3.75V15m-3 3.75h.008v.008H9.75v-.008Zm0 0H6.75m3 0V15m3-7.875H8.25c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
								/>
							</svg>
							<p class="text-sm text-gray-400 dark:text-gray-500">
								{$i18n.t('Drop files here or click Upload to add documents')}
							</p>
						</div>
					{/if}
				</div>

				<!-- Default Model Section -->
				<div class="mb-6">
					<div class="flex w-full justify-between">
						<div class="self-center text-sm font-medium dark:text-white">
							{$i18n.t('Default Model')}
						</div>
						<div class="flex items-center relative">
							<select
								class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right cursor-pointer"
								bind:value={defaultModelId}
								disabled={!isOwner}
								on:change={() => saveSettings()}
							>
								<option value="">{$i18n.t('Select a model')}</option>
								{#each $models as model (model.id)}
									<option value={model.id}>{model.name}</option>
								{/each}
							</select>
						</div>
					</div>
					<p class="text-xs text-gray-400 dark:text-gray-500 mt-1.5">
						{$i18n.t('New chats in this project will use this model by default.')}
					</p>
				</div>

				<!-- Instructions Section -->
				<div class="mb-6">
					<div class="flex items-center justify-between mb-3">
						<h2 class="text-lg font-medium dark:text-white">
							{$i18n.t('Project Instructions')}
						</h2>
					</div>
					<textarea
						class="w-full rounded-xl py-3 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden resize-none border border-gray-200 dark:border-gray-700"
						rows="5"
						bind:value={project.instructions}
						on:input={() => (instructionsDirty = true)}
						placeholder={$i18n.t('Custom instructions for all chats in this project')}
						disabled={!isOwner}
					/>
				</div>

				<!-- Copy to Users (owner only) -->
				{#if isOwner}
					<div class="mb-6">
						<div class="flex items-center justify-between mb-3">
							<h2 class="text-lg font-medium dark:text-white">
								{$i18n.t('Copy to Users')}
							</h2>
						</div>
						<button
							class="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-gray-50 hover:bg-gray-100 dark:bg-gray-850 dark:hover:bg-gray-800 transition"
							on:click={() => (showShareModal = true)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="2"
								stroke="currentColor"
								class="w-4 h-4"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M7.217 10.907a2.25 2.25 0 1 0 0 2.186m0-2.186c.18.324.283.696.283 1.093s-.103.77-.283 1.093m0-2.186 9.566-5.314m-9.566 7.5 9.566 5.314m0 0a2.25 2.25 0 1 0 3.935 2.186 2.25 2.25 0 0 0-3.935-2.186Zm0-12.814a2.25 2.25 0 1 0 3.933-2.185 2.25 2.25 0 0 0-3.933 2.185Z"
								/>
							</svg>
							{$i18n.t('Copy to Users')}
						</button>
					</div>
				{/if}

				<!-- Save / Delete (owner only) -->
				{#if isOwner}
					<div
						class="flex items-center justify-between pt-4 border-t border-gray-200 dark:border-gray-700"
					>
						<button
							class="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition"
							on:click={() => (showDeleteConfirmModal = true)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="2"
								stroke="currentColor"
								class="w-4 h-4"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
								/>
							</svg>
							{$i18n.t('Delete Project')}
						</button>
						<button
							class="px-4 py-1.5 text-sm rounded-lg bg-gray-900 hover:bg-gray-800 dark:bg-white dark:hover:bg-gray-100 text-white dark:text-black transition"
							on:click={saveSettings}
						>
							{$i18n.t('Save')}
						</button>
					</div>
				{/if}
			{/if}
		</div>
	</div>
{/if}
