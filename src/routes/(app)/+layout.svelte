<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, tick, getContext } from 'svelte';
	import { openDB, deleteDB } from 'idb';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;
	import mermaid from 'mermaid';

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fade } from 'svelte/transition';

	import { getKnowledgeBases } from '$lib/apis/knowledge';
	import { getFunctions } from '$lib/apis/functions';
	import { getModels, getToolServersData, getVersionUpdates } from '$lib/apis';
	import { getAllTags } from '$lib/apis/chats';
	import { getPrompts } from '$lib/apis/prompts';
	import { getTools } from '$lib/apis/tools';
	import { getBanners } from '$lib/apis/configs';
	import { getUserSettings } from '$lib/apis/users';
	import { getActiveKnowledgeGraphJobs } from '$lib/apis/knowledge-graph';

	import { WEBUI_VERSION } from '$lib/constants';
	import { compareVersion } from '$lib/utils';

	import {
		config,
		user,
		settings,
		models,
		prompts,
		knowledge,
		tools,
		functions,
		tags,
		banners,
		showSettings,
		showChangelog,
		temporaryChatEnabled,
		toolServers,
		socket
	} from '$lib/stores';
	import { toastHistory } from '$lib/stores/toast-history';

	import Sidebar from '$lib/components/layout/Sidebar.svelte';
	import SettingsModal from '$lib/components/chat/SettingsModal.svelte';
	import ChangelogModal from '$lib/components/ChangelogModal.svelte';
	import AccountPending from '$lib/components/layout/Overlay/AccountPending.svelte';
	import UpdateInfoToast from '$lib/components/layout/UpdateInfoToast.svelte';
	import { get } from 'svelte/store';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let loaded = false;
	let loadError: string | null = null;
	let healthDetail: Record<string, any> | null = null;
	let DB = null;
	let localDBChats = [];

	let version;

	onMount(async () => {
		if ($user === undefined || $user === null) {
			await goto('/auth');
		} else if (['user', 'admin'].includes($user?.role)) {
			try {
				// Check if IndexedDB exists
				DB = await openDB('Chats', 1);

				if (DB) {
					const chats = await DB.getAllFromIndex('chats', 'timestamp');
					localDBChats = chats.map((item, idx) => chats[chats.length - 1 - idx]);

					if (localDBChats.length === 0) {
						await deleteDB('Chats');
					}
				}

				console.log(DB);
			} catch (error) {
				// IndexedDB Not Found
			}

			const userSettings = await getUserSettings(localStorage.token).catch((error) => {
				console.error(error);
				return null;
			});

			if (userSettings) {
				settings.set(userSettings.ui);
			} else {
				let localStorageSettings = {} as Parameters<(typeof settings)['set']>[0];

				try {
					localStorageSettings = JSON.parse(localStorage.getItem('settings') ?? '{}');
				} catch (e: unknown) {
					console.error('Failed to parse settings from localStorage', e);
				}

				settings.set(localStorageSettings);
			}

			const loadedModels = await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			).catch(async (error) => {
				console.error('Failed to load models:', error);
				loadError = $i18n.t('Service connection error. Please contact your administrator.');
				if ($user?.role === 'admin') {
					try {
						const res = await fetch('/health/full');
						healthDetail = await res.json();
					} catch (e) {
						console.error('Failed to fetch health status:', e);
					}
				}
				return [];
			});
			models.set(loadedModels);

			banners.set(await getBanners(localStorage.token).catch((error) => {
				console.error('Failed to load banners:', error);
				return [];
			}));
			if (!$page.url.pathname.startsWith('/workspace')) {
				tools.set(await getTools(localStorage.token).catch(() => []));
			}
			toolServers.set(await getToolServersData($i18n, $settings?.toolServers ?? []));

			document.addEventListener('keydown', async function (event) {
				const isCtrlPressed = event.ctrlKey || event.metaKey; // metaKey is for Cmd key on Mac
				// Check if the Shift key is pressed
				const isShiftPressed = event.shiftKey;

				// Check if Ctrl + Shift + O is pressed
				if (isCtrlPressed && isShiftPressed && event.key.toLowerCase() === 'o') {
					event.preventDefault();
					console.log('newChat');
					document.getElementById('sidebar-new-chat-button')?.click();
				}

				// Check if Shift + Esc is pressed
				if (isShiftPressed && event.key === 'Escape') {
					event.preventDefault();
					console.log('focusInput');
					document.getElementById('chat-input')?.focus();
				}

				// Check if Ctrl + Shift + ; is pressed
				if (isCtrlPressed && isShiftPressed && event.key === ';') {
					event.preventDefault();
					console.log('copyLastCodeBlock');
					const button = [...document.getElementsByClassName('copy-code-button')]?.at(-1);
					button?.click();
				}

				// Check if Ctrl + Shift + C is pressed
				if (isCtrlPressed && isShiftPressed && event.key.toLowerCase() === 'c') {
					event.preventDefault();
					console.log('copyLastResponse');
					const button = [...document.getElementsByClassName('copy-response-button')]?.at(-1);
					console.log(button);
					button?.click();
				}

				// Check if Ctrl + Shift + S is pressed
				if (isCtrlPressed && isShiftPressed && event.key.toLowerCase() === 's') {
					event.preventDefault();
					console.log('toggleSidebar');
					document.getElementById('sidebar-toggle-button')?.click();
				}

				// Check if Ctrl + Shift + Backspace is pressed
				if (
					isCtrlPressed &&
					isShiftPressed &&
					(event.key === 'Backspace' || event.key === 'Delete')
				) {
					event.preventDefault();
					console.log('deleteChat');
					document.getElementById('delete-chat-button')?.click();
				}

				// Check if Ctrl + . is pressed
				if (isCtrlPressed && event.key === '.') {
					event.preventDefault();
					console.log('openSettings');
					showSettings.set(!$showSettings);
				}

				// Check if Ctrl + / is pressed
				if (isCtrlPressed && event.key === '/') {
					event.preventDefault();
					console.log('showShortcuts');
					document.getElementById('show-shortcuts-button')?.click();
				}

				// Check if Ctrl + Shift + ' is pressed
				if (
					isCtrlPressed &&
					isShiftPressed &&
					(event.key.toLowerCase() === `'` || event.key.toLowerCase() === `"`)
				) {
					event.preventDefault();
					console.log('temporaryChat');
					temporaryChatEnabled.set(!$temporaryChatEnabled);
					await goto('/');
					const newChatButton = document.getElementById('new-chat-button');
					setTimeout(() => {
						newChatButton?.click();
					}, 0);
				}
			});

			if ($user?.role === 'admin' && ($settings?.showChangelog ?? true)) {
				showChangelog.set($settings?.version !== $config.version);
			}

			if ($user?.permissions?.chat?.temporary ?? true) {
				if ($page.url.searchParams.get('temporary-chat') === 'true') {
					temporaryChatEnabled.set(true);
				}

				if ($user?.permissions?.chat?.temporary_enforced) {
					temporaryChatEnabled.set(true);
				}
			}

			// Check for version updates
			if ($user?.role === 'admin') {
				// Check if the user has dismissed the update toast in the last 24 hours
				if (localStorage.dismissedUpdateToast) {
					const dismissedUpdateToast = new Date(Number(localStorage.dismissedUpdateToast));
					const now = new Date();

					if (now - dismissedUpdateToast > 24 * 60 * 60 * 1000) {
						checkForVersionUpdates();
					}
				} else {
					checkForVersionUpdates();
				}
			}
			// KG sync 글로벌 진행률 — 앱 로드 시 실행 중인 잡을 알림 센터에 복원
			try {
				const active = await getActiveKnowledgeGraphJobs(localStorage.token).catch(() => []);
				if (active && active.length > 0) {
					for (const j of active) {
						toastHistory.upsert(`kg-sync:${j.id}`, {
							type: 'running',
							message: buildKgSyncMessage(j.kg_name, j.kg_id, j.kind, j.status),
							progress: {
								current: j.progress_current,
								total: j.progress_total,
								label: j.progress_label ?? null
							},
							linkTo: `/workspace/knowledge-graph/${j.kg_id}`,
							persistent: true
						});
					}
				}
			} catch (e) {
				console.warn('[kg-sync] active-jobs restore failed', e);
			}

			const sock = $socket;
			if (sock) {
				sock.on('notification', handleGlobalNotification);
			}

			await tick();
		}

		loaded = true;
	});

	function phaseLabelKey(kind: string): string {
		switch (kind) {
			case 'glossary_sync': return 'Glossary sync';
			case 'kb_match': return 'KB match';
			case 'db_derivation': return 'DB derivation';
			case 'doc_extract': return 'Document extract';
			case 'kb_extract': return 'KB extract';
			default: return 'Knowledge Graph sync';
		}
	}

	function buildKgSyncMessage(
		kgName: string | null | undefined,
		kgId: string,
		kind: string,
		status: string
	): string {
		const label = kgName || kgId.slice(0, 8);
		const phase = $i18n.t(phaseLabelKey(kind));
		if (status === 'completed') return `${label} · ${phase} — ${$i18n.t('Completed')}`;
		if (status === 'failed') return `${label} · ${phase} — ${$i18n.t('Failed')}`;
		if (status === 'warning') return `${label} · ${phase}`;
		return `${label} · ${phase}`;
	}

	function inferKindFromLabel(label: string | undefined, fallback: string): string {
		if (!label) return fallback;
		const lo = label.toLowerCase();
		if (lo.includes('doc_entity_map') || lo.includes('match kb') || lo.includes('matching'))
			return 'kb_match';
		if (lo.includes('db derivation') || lo.includes('derivation')) return 'db_derivation';
		if (
			lo.includes('document-level') ||
			lo.includes('document extract') ||
			lo.includes('extraction')
		)
			return 'doc_extract';
		if (lo.includes('glossary') || lo.includes('entry')) return 'glossary_sync';
		return fallback;
	}

	function handleGlobalNotification(payload: any) {
		if (!payload || typeof payload !== 'object') return;
		const t: string = payload.type || '';
		const data = payload.data || {};

		if (t.startsWith('kg-')) {
			handleKgSyncNotification(t, data);
		} else if (t === 'extraction:file-complete') {
			handleKbFilterExtractEvent(data);
		} else if (t === 'extraction:complete') {
			handleKbFilterExtractBatchComplete(data);
		} else if (t === 'schema-extraction-completed' || t === 'schema-extraction-failed') {
			handleSchemaExtractionEvent(t, data);
		} else if (
			t === 'file-processing-completed' ||
			t === 'file-processing-failed'
		) {
			handleFileProcessingEvent(t, data);
		} else if (
			t === 'glossary-extract-progress' ||
			t === 'glossary-extract-completed' ||
			t === 'glossary-extract-failed'
		) {
			handleGlossaryExtractEvent(t, data);
		} else if (t === 'file-delete-batch:progress' || t === 'file-delete-batch:complete') {
			handleFileDeleteBatchEvent(t, data);
		}
	}

	function handleFileDeleteBatchEvent(eventType: string, data: any) {
		const kbId: string | undefined = data.kb_id;
		const jobId: string | undefined = data.job_id;
		if (!kbId || !jobId) return;
		const entryId = `kb-delete:${kbId}:${jobId}`;
		const linkTo = `/workspace/knowledge/${kbId}`;
		if (eventType === 'file-delete-batch:progress') {
			toastHistory.upsert(entryId, {
				type: 'running',
				message: `${$i18n.t('Deleting files')}`,
				progress: { current: data.done ?? 0, total: data.total ?? 0, label: null },
				linkTo,
				persistent: true
			});
		} else if (eventType === 'file-delete-batch:complete') {
			const failed = data.failed ?? 0;
			const success = data.success ?? 0;
			const total = data.total ?? 0;
			toastHistory.upsert(entryId, {
				type: failed > 0 ? 'warning' : 'success',
				message:
					failed > 0
						? $i18n.t('Deleted {{success}}/{{total}} files, {{failed}} failed', {
								success,
								total,
								failed
							})
						: $i18n.t('Deleted {{count}} files', { count: total }),
				progress: null,
				linkTo,
				persistent: false
			});
		}
	}

	function handleGlossaryExtractEvent(eventType: string, data: any) {
		const gid: string | undefined = data.glossary_id;
		if (!gid) return;
		const entryId = `glossary-extract:${gid}`;
		const gname: string = data.glossary_name || gid.slice(0, 8);
		const linkTo = `/workspace/glossary/${gid}`;

		if (eventType === 'glossary-extract-progress') {
			toastHistory.upsert(entryId, {
				type: 'running',
				message: `${gname} · ${$i18n.t('Glossary extraction')}`,
				progress: {
					current: data.current ?? null,
					total: data.total ?? null,
					label: null
				},
				linkTo,
				persistent: true
			});
		} else if (eventType === 'glossary-extract-completed') {
			const newCount = data.new_count ?? 0;
			const skipped = data.skipped ?? 0;
			toastHistory.upsert(entryId, {
				type: 'success',
				message: `${gname} · ${$i18n.t('Extracted {{new}} new, {{skipped}} skipped', { new: newCount, skipped })}`,
				progress: null,
				linkTo,
				persistent: false
			});
			// 완료 toast 는 root +layout 의 기존 로직이 담당 — 여기선 entry 만 갱신.
		} else if (eventType === 'glossary-extract-failed') {
			toastHistory.upsert(entryId, {
				type: 'error',
				message: data.error || `${gname} · ${$i18n.t('Glossary extraction failed.')}`,
				progress: null,
				linkTo,
				persistent: true
			});
		}
	}

	// kb_id+job_id 별로 이미 카운트한 file_id 추적 — 같은 이벤트가 두 번
	// 도착해도 ToastHistory 진행률을 부풀리지 않는다.
	const _kbExtractCountedFileIds = new Map<string, Set<string>>();

	function handleKbFilterExtractEvent(data: any) {
		const kbId: string | undefined = data.kb_id;
		if (!kbId) return;
		const entryId = `kb-filter-extract:${kbId}`;
		// 기존 엔트리가 없으면 Extract All 이 이 페이지에서 시작되지 않은
		// 경우(예: API 호출로 trigger). 단일 파일 추출도 포함되므로 무시하고
		// 개별 toast 만 보여주는 편이 맞다.
		const currentItems = get(toastHistory);
		const existing = currentItems.find((it) => it.id === entryId);
		if (!existing) return;

		// dedupe: 같은 file_id 가 이미 카운트됐으면 skip
		const dedupeKey = `${kbId}:${data.job_id ?? '-'}`;
		let counted = _kbExtractCountedFileIds.get(dedupeKey);
		if (!counted) {
			counted = new Set();
			_kbExtractCountedFileIds.set(dedupeKey, counted);
		}
		if (data.file_id && counted.has(data.file_id)) return;
		if (data.file_id) counted.add(data.file_id);

		const prevProgress = existing.progress ?? { current: 0, total: null, label: null };
		const nextCurrent = (prevProgress.current ?? 0) + 1;
		const total = prevProgress.total ?? null;
		// 완료는 서버의 extraction:complete 이벤트가 확정. 파일별 이벤트에서는
		// 카운터만 올리고 finalize 는 하지 않는다 (복제 finalize 방지).
		toastHistory.upsert(entryId, {
			type: 'running',
			progress: {
				current: nextCurrent,
				total,
				label: data.filename ?? null
			},
			persistent: true,
			message: existing.message
		});
	}

	function handleKbFilterExtractBatchComplete(data: any) {
		const kbId: string | undefined = data.kb_id;
		if (!kbId) return;
		const entryId = `kb-filter-extract:${kbId}`;
		const currentItems = get(toastHistory);
		const existing = currentItems.find((it) => it.id === entryId);
		const baseMessage = existing
			? existing.message.split(' · ')[0]
			: ($i18n.t('Filter extraction') as string);
		const failed = data.failed ?? 0;
		toastHistory.upsert(entryId, {
			type: failed > 0 ? 'warning' : 'success',
			progress: null,
			persistent: false,
			message:
				failed > 0
					? `${baseMessage} · ${$i18n.t('Completed with {{failed}} failed', { failed })}`
					: `${baseMessage} · ${$i18n.t('Filter extraction completed.')}`
		});
		// dedupe 맵 정리 (다음 추출에서 재사용 못 하게)
		_kbExtractCountedFileIds.delete(`${kbId}:${data.job_id ?? '-'}`);
	}

	function handleSchemaExtractionEvent(eventType: string, data: any) {
		const dsId: string | undefined = data.dbsphere_id;
		if (!dsId) return;
		const entryId = `dbsphere-schema:${dsId}`;
		const dsName: string = data.dbsphere_name || dsId.slice(0, 8);
		const linkTo = `/workspace/database/${dsId}`;

		if (eventType === 'schema-extraction-completed') {
			const savedParts: string[] = [];
			if (data.tables_saved !== undefined)
				savedParts.push(`${data.tables_saved} ${$i18n.t('tables')}`);
			if (data.qa_saved !== undefined)
				savedParts.push(`${data.qa_saved} Q&A`);
			const suffix = savedParts.length > 0 ? ` (${savedParts.join(', ')})` : '';
			toastHistory.upsert(entryId, {
				type: 'success',
				message: `${dsName} · ${$i18n.t('Schema extraction completed.')}${suffix}`,
				progress: null,
				linkTo,
				persistent: false
			});
			toast.success($i18n.t('Schema extraction completed.'));
		} else {
			toastHistory.upsert(entryId, {
				type: 'error',
				message:
					data.error ||
					data.message ||
					`${dsName} · ${$i18n.t('Schema extraction failed.')}`,
				progress: null,
				linkTo,
				persistent: true
			});
			toast.error(data.error || data.message || $i18n.t('Schema extraction failed.'));
		}
	}

	function handleFileProcessingEvent(eventType: string, data: any) {
		// KB 대량 업로드 진행률 — 업로드 시작 세션이 batchId 로 선점 생성한 알림센터(벨)
		// 엔트리를 파일별 이벤트마다 증분한다. 엔트리가 없는 세션(단건 업로드/타 세션)은 no-op.
		const entryKey: string | undefined =
			data.batch_id || data.knowledge_id || data.collection_name;
		if (!entryKey) return;
		const entryId = `kb-upload:${entryKey}`;
		const currentItems = get(toastHistory);
		const existing = currentItems.find((it) => it.id === entryId);
		// progress 가 null 이면 이미 종료(finalizeBatch / done)된 엔트리 → 늦게 도착한
		// 이벤트로 되살리지 않는다 (요약 메시지 아래 파일명/0% 바가 재출현하는 버그 방지).
		if (!existing || !existing.progress) return;

		const prevProgress = existing.progress;
		const total = prevProgress.total ?? null;
		// 중복/초과 이벤트로 total 을 넘기지 않도록 캡.
		const rawNext = (prevProgress.current ?? 0) + 1;
		const nextCurrent = total !== null ? Math.min(rawNext, total) : rawNext;
		// 실패 이벤트면 오류 카운트 누적 — 진행 카운트 옆 "(N)" 으로 노출.
		const nextFailed = (prevProgress.failed ?? 0) + (eventType === 'file-processing-failed' ? 1 : 0);
		const done = total !== null && nextCurrent >= total;

		toastHistory.upsert(entryId, {
			type: done ? (nextFailed > 0 ? 'warning' : 'success') : 'running',
			progress: done
				? null
				: {
						current: nextCurrent,
						total,
						label: data.filename ?? null,
						failed: nextFailed
					},
			persistent: !done,
			// 완료(done) 메시지는 발신 세션에선 finalizeBatch 가 상세 요약으로 덮어쓴다.
			// 여기 fallback 도 오류 개수를 반영해 둔다 (finalizeBatch 미실행 세션 대비).
			message: done
				? `${existing.message.split(' · ')[0]} · ${
						nextFailed > 0
							? $i18n.t('Completed with {{failed}} failed', { failed: nextFailed })
							: $i18n.t('Files uploaded.')
					}`
				: existing.message
		});
	}

	function handleKgSyncNotification(t: string, data: any) {
		const jobId: string | undefined = data.job_id || data.id;
		const kgId: string | undefined = data.kg_id;
		if (!jobId || !kgId) return;

		const entryId = `kg-sync:${jobId}`;
		const linkTo = `/workspace/knowledge-graph/${kgId}`;

		if (t === 'kg-job-progress') {
			const kind = inferKindFromLabel(data.progress_label, data.kind || 'sync');
			toastHistory.upsert(entryId, {
				type: 'running',
				message: buildKgSyncMessage(data.kg_name, kgId, kind, 'running'),
				progress: {
					current: data.progress_current ?? null,
					total: data.progress_total ?? null,
					label: data.progress_label ?? null
				},
				linkTo,
				persistent: true
			});
		} else if (t === 'kg-link-sync-completed' || t === 'kg-job-completed') {
			toastHistory.upsert(entryId, {
				type: 'success',
				message: buildKgSyncMessage(data.kg_name, kgId, data.kind || 'sync', 'completed'),
				progress: null,
				linkTo,
				persistent: false
			});
			toast.success($i18n.t('Knowledge graph sync completed.'));
		} else if (t === 'kg-link-sync-warning') {
			toastHistory.upsert(entryId, {
				type: 'warning',
				message:
					data.message ||
					buildKgSyncMessage(data.kg_name, kgId, data.kind || 'kb_match', 'warning'),
				progress: null,
				linkTo,
				persistent: true
			});
			toast.warning(data.message || $i18n.t('Knowledge graph sync finished with warnings.'));
		} else if (t === 'kg-link-sync-failed') {
			toastHistory.upsert(entryId, {
				type: 'error',
				message: data.error || buildKgSyncMessage(data.kg_name, kgId, data.kind || 'sync', 'failed'),
				progress: null,
				linkTo,
				persistent: true
			});
			toast.error(data.error || $i18n.t('Knowledge graph sync failed.'));
		}
	}

	const checkForVersionUpdates = async () => {
		version = await getVersionUpdates(localStorage.token).catch((error) => {
			return {
				current: WEBUI_VERSION,
				latest: WEBUI_VERSION
			};
		});
	};
</script>

<SettingsModal bind:show={$showSettings} />
<ChangelogModal bind:show={$showChangelog} />

{#if version && compareVersion(version.latest, version.current) && ($settings?.showUpdateToast ?? true)}
	<div class=" absolute bottom-8 right-8 z-50" in:fade={{ duration: 100 }}>
		<UpdateInfoToast
			{version}
			on:close={() => {
				localStorage.setItem('dismissedUpdateToast', Date.now().toString());
				version = null;
			}}
		/>
	</div>
{/if}

<div class="app relative">
	<div
		class=" text-gray-700 dark:text-gray-100 bg-white dark:bg-gray-900 h-screen max-h-[100dvh] overflow-auto flex flex-row"
	>
		{#if !['user', 'admin'].includes($user?.role)}
			<AccountPending />
		{:else if localDBChats.length > 0}
			<div class="fixed w-full h-full flex z-50">
				<div
					class="absolute w-full h-full backdrop-blur-md bg-white/20 dark:bg-gray-900/50 flex justify-center"
				>
					<div class="m-auto pb-44 flex flex-col justify-center">
						<div class="max-w-md">
							<div class="text-center dark:text-white text-2xl font-medium z-50">
								Important Update<br /> Action Required for Chat Log Storage
							</div>

							<div class=" mt-4 text-center text-sm dark:text-gray-200 w-full">
								{$i18n.t(
									"Saving chat logs directly to your browser's storage is no longer supported. Please take a moment to download and delete your chat logs by clicking the button below. Don't worry, you can easily re-import your chat logs to the backend through"
								)}
								<span class="font-semibold dark:text-white"
									>{$i18n.t('Settings')} > {$i18n.t('Chats')} > {$i18n.t('Import Chats')}</span
								>. {$i18n.t(
									'This ensures that your valuable conversations are securely saved to your backend database. Thank you!'
								)}
							</div>

							<div class=" mt-6 mx-auto relative group w-fit">
								<button
									class="relative z-20 flex px-5 py-2 rounded-full bg-white border border-gray-100 dark:border-none hover:bg-gray-100 transition font-medium text-sm"
									on:click={async () => {
										let blob = new Blob([JSON.stringify(localDBChats)], {
											type: 'application/json'
										});
										saveAs(blob, `chat-export-${Date.now()}.json`);

										const tx = DB.transaction('chats', 'readwrite');
										await Promise.all([tx.store.clear(), tx.done]);
										await deleteDB('Chats');

										localDBChats = [];
									}}
								>
									Download & Delete
								</button>

								<button
									class="text-xs text-center w-full mt-2 text-gray-400 underline"
									on:click={async () => {
										localDBChats = [];
									}}>{$i18n.t('Close')}</button
								>
							</div>
						</div>
					</div>
				</div>
			</div>
		{/if}

		<Sidebar />

		{#if loaded && !loadError}
			<slot />
		{:else if loadError}
			<div class="absolute w-full h-full backdrop-blur-sm flex justify-center z-50">
				<div class="m-auto pb-44 flex flex-col justify-center">
					<div class="max-w-md">
						<div class="text-center dark:text-white text-2xl font-medium">
							{$i18n.t('Service Connection Error')}
						</div>

						<div class="mt-4 text-center text-sm dark:text-gray-200 w-full">
							{loadError}
						</div>

						{#if $user?.role === 'admin' && healthDetail}
							<div class="mt-6 text-left bg-white dark:bg-gray-800 rounded-xl p-4 border border-gray-100 dark:border-gray-700 shadow-sm">
								<div class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-3">
									{$i18n.t('System Diagnostics')}
								</div>
								{#each Object.entries(healthDetail.components ?? {}) as [name, comp]}
									<div class="flex items-center justify-between py-1.5">
										<span class="text-sm font-mono text-gray-700 dark:text-gray-300">{name}</span>
										{#if comp.status}
											<span class="text-xs font-medium text-green-600 dark:text-green-400">OK</span>
										{:else}
											<span class="text-xs font-medium text-red-500 dark:text-red-400">ERROR</span>
										{/if}
									</div>
									{#if comp.error}
										<div class="text-xs font-mono text-red-500/80 dark:text-red-400/80 mb-2 break-all leading-relaxed">
											{comp.error}
										</div>
									{/if}
								{/each}
							</div>
						{/if}

						<div class="mt-6 mx-auto relative group w-fit">
							<button
								class="relative z-20 flex px-5 py-2 rounded-full bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 dark:text-white transition font-medium text-sm"
								on:click={() => location.reload()}
							>
								{$i18n.t('Check Again')}
							</button>
						</div>
					</div>
				</div>
			</div>
		{:else}
			<div class="w-full flex-1 h-full flex items-center justify-center">
				<Spinner />
			</div>
		{/if}
	</div>
</div>

<style>
	.loading {
		display: inline-block;
		clip-path: inset(0 1ch 0 0);
		animation: l 1s steps(3) infinite;
		letter-spacing: -0.5px;
	}

	@keyframes l {
		to {
			clip-path: inset(0 -1ch 0 0);
		}
	}

	pre[class*='language-'] {
		position: relative;
		overflow: auto;

		/* make space  */
		margin: 5px 0;
		padding: 1.75rem 0 1.75rem 1rem;
		border-radius: 10px;
	}

	pre[class*='language-'] button {
		position: absolute;
		top: 5px;
		right: 5px;

		font-size: 0.9rem;
		padding: 0.15rem;
		background-color: #828282;

		border: ridge 1px #7b7b7c;
		border-radius: 5px;
		text-shadow: #c4c4c4 0 0 2px;
	}

	pre[class*='language-'] button:hover {
		cursor: pointer;
		background-color: #bcbabb;
	}
</style>
