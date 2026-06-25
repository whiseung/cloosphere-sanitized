<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import mermaid from 'mermaid';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { getContext, onDestroy, onMount, tick } from 'svelte';
	const i18n: Writable<i18nType> = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { get, type Unsubscriber, type Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { formatBackendError } from '$lib/utils/error';

	import {
		chatId,
		chats,
		config,
		type Model,
		models,
		tags as allTags,
		settings,
		showSidebar,
		WEBUI_NAME,
		banners,
		user,
		socket,
		showControls,
		showCallOverlay,
		currentChatPage,
		temporaryChatEnabled,
		mobile,
		showOverview,
		chatTitle,
		showArtifacts,
		tools,
		toolServers,
		failedFileIds
	} from '$lib/stores';
	import {
		convertMessagesToHistory,
		copyToClipboard,
		getMessageContentParts,
		createMessagesList,
		extractSentencesForAudio,
		promptTemplate,
		splitStream,
		sleep,
		removeDetails,
		getPromptVariables,
		processDetails
	} from '$lib/utils';

	import { generateChatCompletion } from '$lib/apis/ollama';
	import {
		addTagById,
		createNewChat,
		deleteTagById,
		deleteTagsById,
		getAllTags,
		getChatById,
		getChatList,
		getTagsById,
		updateChatById,
		resumeChatHITL,
		type HITLDecision
	} from '$lib/apis/chats';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import { processWeb, processWebSearch, processYoutubeVideo } from '$lib/apis/retrieval';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import { queryMemory } from '$lib/apis/memories';
	import { getAndUpdateUserLocation, getUserSettings } from '$lib/apis/users';
	import { addChatToProject } from '$lib/apis/projects';
	import { getScheduleById } from '$lib/apis/schedules';
	import {
		chatCompleted,
		chatAction,
		generateMoACompletion,
		stopTask,
		getTaskIdsByChatId
	} from '$lib/apis';
	import { getTools } from '$lib/apis/tools';
	import { getImageConnectionsList } from '$lib/apis/images';
	import { getMyEmailConnections } from '$lib/apis/email';

	import Banner from '../common/Banner.svelte';
	import MessageInput from '$lib/components/chat/MessageInput.svelte';
	import Messages from '$lib/components/chat/Messages.svelte';
	import Navbar from '$lib/components/chat/Navbar.svelte';
	import ChatControls from './ChatControls.svelte';
	import EventConfirmDialog from '../common/ConfirmDialog.svelte';
	import Placeholder from './Placeholder.svelte';
	import NotificationToast from '../NotificationToast.svelte';
	import Spinner from '../common/Spinner.svelte';

	export let chatIdProp = '';

	let loading = false;

	const eventTarget = new EventTarget();
	let controlPane;
	let controlPaneComponent;

	let autoScroll = true;
	let processing = '';
	let messagesContainerElement: HTMLDivElement;

	let navbarElement;

	let showEventConfirmation = false;
	let eventConfirmationTitle = '';
	let eventConfirmationMessage = '';
	let eventConfirmationInput = false;
	let eventConfirmationInputPlaceholder = '';
	let eventConfirmationInputValue = '';
	let eventCallback = null;

	let chatIdUnsubscriber: Unsubscriber | undefined;

	let selectedModels = [''];
	let atSelectedModel: Model | undefined;
	let selectedModelIds = [];
	$: selectedModelIds = atSelectedModel !== undefined ? [atSelectedModel.id] : selectedModels;

	let selectedToolIds = [];
	let imageGenerationEnabled = false;
	let selectedImageConnectionIdx: number | null = null;
	let allImageConnections: { idx: number; name: string; engine: string; model: string }[] = [];
	$: imageConnections = (() => {
		// Filter by agent's selected connections if applicable
		const model = atSelectedModel ?? $models.find((m) => m.id === selectedModels?.[0]);
		const imgConfig = model?.info?.meta?.capabilities?.image_generation_config;
		const connIds: number[] = imgConfig?.connection_ids ?? [];
		// Legacy single-select fallback
		if (connIds.length === 0 && imgConfig?.connection_idx != null) {
			connIds.push(imgConfig.connection_idx);
		}
		if (connIds.length > 0) {
			return allImageConnections.filter((c) => connIds.includes(c.idx));
		}
		return allImageConnections;
	})();
	let webSearchEnabled = false;
	let gmailEnabled = false;
	let calendarEnabled = false;
	let driveEnabled = false;

	// Google OAuth 연결 상태 (Gmail/Calendar/Drive 토글의 5축 게이트 중 OAuth 축).
	// onMount 에서 ``getMyEmailConnections`` 으로 fetch.
	// connected = google 토큰 row 존재, 기능별 플래그 = 해당 기능 필수 scope 보유
	// (GWS scope 도입 이전 SSO 토큰은 connected=true 여도 기능별 false).
	let googleScopes = { connected: false, gmail: false, calendar: false, drive: false };

	// 게이트(admin 토글 / 그룹 권한 / OAuth scope) 미통과 기능은 토글 상태를 강제
	// false 로 유지 — capability 'on' 기본값, 저장된 채팅 복원, 연결 상태 fetch 가
	// 늦게 도착하는 경우 모두 커버한다 (요청 payload 는 getFeaturesPayload 가 한 번 더 차단).
	$: if (
		gmailEnabled &&
		(!$config?.features?.enable_gmail ||
			($user?.role !== 'admin' && !$user?.permissions?.features?.gmail) ||
			!googleScopes.gmail)
	)
		gmailEnabled = false;
	$: if (
		calendarEnabled &&
		(!$config?.features?.enable_calendar ||
			($user?.role !== 'admin' && !$user?.permissions?.features?.calendar) ||
			!googleScopes.calendar)
	)
		calendarEnabled = false;
	$: if (
		driveEnabled &&
		(!$config?.features?.enable_drive ||
			($user?.role !== 'admin' && !$user?.permissions?.features?.drive) ||
			!googleScopes.drive)
	)
		driveEnabled = false;

	// Agent-level capability overrides (null = regular model, show all admin-enabled features; {} = hide all until loaded)
	let modelCapabilities: {
		web_search?: boolean;
		image_generation?: boolean;
		gmail?: boolean;
		calendar?: boolean;
		drive?: boolean;
	} | null = {};

	let chat = null;
	let tags = [];

	// Schedule 결과 chat은 소유자만 이어서 대화 가능.
	// 공유자(read/write 무관) 및 admin도 본인 소유가 아니면 read-only.
	// worker가 owner 컨텍스트로 누적한 히스토리 오염 방지.
	$: isScheduleReadOnly =
		chat?.meta?.schedule_id && chat?.user_id && chat.user_id !== $user?.id;

	let history = {
		messages: {},
		currentId: null
	};

	let taskIds = null;

	// chatId 변경 시 태스크 참조만 해제 (백엔드 중단하지 않음)
	let previousChatId = '';
	$: {
		if (previousChatId && previousChatId !== $chatId) {
			taskIds = null;
		}
		previousChatId = $chatId;
	}

	// Chat Input
	let prompt = '';
	let chatFiles = [];
	let files = [];
	let params = {};

	// 파일 가드레일 block 시 채팅 입력창에서 파일 제거
	$: if ($failedFileIds.length > 0) {
		const failedIds = $failedFileIds;
		files = files.filter((f) => !failedIds.includes(f.id));
		failedFileIds.set([]);
	}

	$: if (chatIdProp) {
		(async () => {
			loading = true;
			console.log(chatIdProp);

			prompt = '';
			files = [];
			selectedToolIds = [];
			webSearchEnabled = false;
			imageGenerationEnabled = false;
			selectedImageConnectionIdx = null;
			// Google Workspace 토글은 채팅별로 기억한다. 일단 off 로 리셋한 뒤,
			// loadChat 이후 chat.params.google_workspace → draft 순서로 복원한다.
			gmailEnabled = false;
			calendarEnabled = false;
			driveEnabled = false;

			if (chatIdProp && (await loadChat())) {
				await tick();
				loading = false;

				if (localStorage.getItem(`chat-input-${chatIdProp}`)) {
					try {
						const input = JSON.parse(localStorage.getItem(`chat-input-${chatIdProp}`));

						prompt = input.prompt;
						files = input.files;
						selectedToolIds = input.selectedToolIds;
						webSearchEnabled = input.webSearchEnabled;
						imageGenerationEnabled = input.imageGenerationEnabled;
						selectedImageConnectionIdx = input.selectedImageConnectionIdx ?? null;
						// 2) 미전송 draft 가 있으면 작성 중이던 토글 상태가 최우선
						if (input.gmailEnabled !== undefined) gmailEnabled = input.gmailEnabled;
						if (input.calendarEnabled !== undefined) calendarEnabled = input.calendarEnabled;
						if (input.driveEnabled !== undefined) driveEnabled = input.driveEnabled;
					} catch (e) {}
				}

				window.setTimeout(() => scrollToBottom(), 0);
				const chatInput = document.getElementById('chat-input');
				chatInput?.focus();
			} else {
				await goto('/');
			}
		})();
	}

	$: if (selectedModels && chatIdProp !== '') {
		saveSessionSelectedModels();
	}

	const saveSessionSelectedModels = () => {
		if (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {
			return;
		}
		sessionStorage.selectedModels = JSON.stringify(selectedModels);
		console.log('saveSessionSelectedModels', selectedModels, sessionStorage.selectedModels);
	};

	$: if (selectedModels) {
		setToolIds();
	}

	// googleScopes/$config 도 의존성에 포함 — 연결 상태·admin 통합 토글이 onMount
	// fetch 로 늦게 도착해도 updateModelCapabilities 가 재실행되어 google 토글 기본값을
	// 올바르게(게이트 통과 시에만 ON) 재계산한다.
	$: if (atSelectedModel || selectedModels || $models || googleScopes || $config) {
		setToolIds();
		updateModelCapabilities();
	}

	/** Normalize capability value: true→'on', false→'off', string as-is */
	const normCap = (v: any): string => {
		if (v === true) return 'on';
		if (v === false || v === undefined || v === null) return 'off';
		return String(v);
	};

	/**
	 * Google 기능이 실제로 사용 가능한지(=토글을 기본 활성화해도 되는지) 판정.
	 * 채팅 InputMenu 의 googleBlockReason 과 동일 기준: admin 통합 토글 + 그룹 권한
	 * + OAuth 연결·scope 를 모두 통과해야 한다. capability 'on' 이어도 이 게이트를
	 * 통과 못 하면 기본값은 OFF (fail-closed).
	 *
	 * 이 판정을 updateModelCapabilities 안에서 직접 적용한다 — 별도 reactive 게이트
	 * (gmailEnabled 을 읽고 쓰는 `$: if`)는 함수 내부 set 을 Svelte 가 위상정렬로
	 * 추적하지 못해 재실행이 누락될 수 있으므로(연결 안 했는데도 pill 노출), 소스에서
	 * 결정한다. googleScopes/$config 가 늦게 도착하는 경우는 트리거 의존성으로 커버.
	 */
	const googleFeatureUsable = (feature: 'gmail' | 'calendar' | 'drive'): boolean => {
		const enableKey = `enable_${feature}`;
		if (!$config?.features?.[enableKey]) return false;
		if ($user?.role !== 'admin' && !$user?.permissions?.features?.[feature]) return false;
		if (!googleScopes.connected || !googleScopes[feature]) return false;
		return true;
	};

	const updateModelCapabilities = () => {
		if (selectedModels.length !== 1 && !atSelectedModel) {
			modelCapabilities = null;
			return;
		}
		const model = atSelectedModel ?? $models.find((m) => m.id === selectedModels[0]);
		if (!model) {
			return;
		}

		const rawCaps = model.info?.meta?.capabilities;
		if (model.info?.base_model_id) {
			// Agent: use agent-defined capabilities (missing = off)
			modelCapabilities = rawCaps ?? {};
		} else {
			// Regular model: use capabilities if defined, otherwise null (show all admin-enabled)
			modelCapabilities = rawCaps ?? null;
		}

		// Set feature toggle defaults based on capability state:
		//   "on"  → enabled by default (user can disable)
		//   "user" → visible but disabled by default (user can enable)
		//   "off" → hidden, disabled
		if (modelCapabilities) {
			webSearchEnabled = normCap(modelCapabilities.web_search) === 'on';
			imageGenerationEnabled = normCap(modelCapabilities.image_generation) === 'on';
			// Google Workspace: capability 'on' 이어도 admin 통합 토글 / 그룹 권한 /
			// OAuth 연결·scope 를 모두 통과해야 기본 활성화. 미연결이거나 admin 이 끈
			// 기능은 fail-closed 로 OFF (연결 안 했는데 pill 노출되는 문제 방지).
			// 저장된 채팅 복원(loadChat)은 await tick() 이후 실행되어 이 기본값을 덮어쓴다.
			gmailEnabled = normCap(modelCapabilities.gmail) === 'on' && googleFeatureUsable('gmail');
			calendarEnabled =
				normCap(modelCapabilities.calendar) === 'on' && googleFeatureUsable('calendar');
			driveEnabled = normCap(modelCapabilities.drive) === 'on' && googleFeatureUsable('drive');
			// Auto-select first image connection when image generation is enabled
			if (imageGenerationEnabled && imageConnections.length > 0) {
				selectedImageConnectionIdx = imageConnections[0].idx;
			} else {
				selectedImageConnectionIdx = null;
			}
		} else {
			// Regular model without capabilities: reset to off (user opt-in)
			webSearchEnabled = false;
			imageGenerationEnabled = false;
			gmailEnabled = false;
			calendarEnabled = false;
			driveEnabled = false;
			selectedImageConnectionIdx = null;
		}
	};

	const setToolIds = async () => {
		if (!$tools) {
			tools.set(await getTools(localStorage.token));
		}

		if (selectedModels.length !== 1 && !atSelectedModel) {
			return;
		}

		const model = atSelectedModel ?? $models.find((m) => m.id === selectedModels[0]);
		if (model) {
			selectedToolIds = (model?.info?.meta?.toolIds ?? []).filter((id) =>
				$tools.find((t) => t.id === id)
			);
		}
	};

	const showMessage = async (message) => {
		const _chatId = JSON.parse(JSON.stringify($chatId));
		let _messageId = JSON.parse(JSON.stringify(message.id));

		let messageChildrenIds = [];
		if (_messageId === null) {
			messageChildrenIds = Object.keys(history.messages).filter(
				(id) => history.messages[id].parentId === null
			);
		} else {
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		while (messageChildrenIds.length !== 0) {
			_messageId = messageChildrenIds.at(-1);
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		history.currentId = _messageId;

		await tick();
		await tick();
		await tick();

		const messageElement = document.getElementById(`message-${message.id}`);
		if (messageElement) {
			messageElement.scrollIntoView({ behavior: 'smooth' });
		}

		await tick();
		saveChatHandler(_chatId, history);
	};

	const chatEventHandler = async (event, cb) => {
		console.log(event);

		// 현재 채팅이 없거나 다른 채팅의 이벤트면 무시
		if (!$chatId || event.chat_id !== $chatId) {
			return;
		}

		await tick();
		let message = history.messages[event.message_id];

		if (message) {
			const type = event?.data?.type ?? null;
			const data = event?.data?.data ?? null;

			if (type === 'status') {
				if (message?.statusHistory) {
					message.statusHistory.push(data);
				} else {
					message.statusHistory = [data];
				}
			} else if (type === 'agent_reasoning') {
				// show_reasoning=detailed 라이브 추론 — message.content 가 아닌 전용
				// 필드에 저장(우리 챗 UI 전용 side-channel). content 를 오염시키지 않아
				// OpenAI 호환 API/임베드 등 다른 소비자엔 답변 본문만 깨끗하게 나간다.
				message.reasoning = data;
			} else if (type === 'chat:completion') {
				chatCompletionEventHandler(data, message, event.chat_id);
			} else if (type === 'chat:message:delta' || type === 'message') {
				message.content += data.content;
			} else if (type === 'chat:message' || type === 'replace') {
				message.content = data.content;
			} else if (type === 'chat:message:files' || type === 'files') {
				message.files = data.files;
			} else if (type === 'chat:title') {
				chatTitle.set(data);
				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage, true));
			} else if (type === 'chat:tags') {
				chat = await getChatById(localStorage.token, $chatId);
				allTags.set(await getAllTags(localStorage.token));
			} else if (type === 'source' || type === 'citation') {
				if (data?.type === 'code_execution') {
					// Code execution; update existing code execution by ID, or add new one.
					if (!message?.code_executions) {
						message.code_executions = [];
					}

					const existingCodeExecutionIndex = message.code_executions.findIndex(
						(execution) => execution.id === data.id
					);

					if (existingCodeExecutionIndex !== -1) {
						message.code_executions[existingCodeExecutionIndex] = data;
					} else {
						message.code_executions.push(data);
					}

					message.code_executions = message.code_executions;
				} else if (data?.type === 'query_execution') {
					// SQL query execution (DbSphere)
					if (!message?.query_executions) {
						message.query_executions = [];
					}

					const existingIndex = message.query_executions.findIndex(
						(execution) => execution.id === data.id
					);

					if (existingIndex !== -1) {
						message.query_executions[existingIndex] = data;
					} else {
						message.query_executions.push(data);
					}

					message.query_executions = message.query_executions;
				} else {
					// Regular source.
					if (message?.sources) {
						message.sources.push(data);
					} else {
						message.sources = [data];
					}
				}
			} else if (type === 'notification') {
				const toastType = data?.type ?? 'info';
				const toastContent = data?.content ?? '';
				const toastId = data?.id ?? `notification-${event.chat_id}-${event.message_id}`;

				if (toastType === 'success') {
					toast.success(toastContent, { id: toastId });
				} else if (toastType === 'error') {
					toast.error(toastContent, { id: toastId });
				} else if (toastType === 'warning') {
					toast.warning(toastContent, { id: toastId });
				} else {
					toast.info(toastContent, { id: toastId });
				}
			} else if (type === 'confirmation') {
				eventCallback = cb;

				eventConfirmationInput = false;
				showEventConfirmation = true;

				eventConfirmationTitle = data.title;
				eventConfirmationMessage = data.message;
			} else if (type === 'execute') {
				eventCallback = cb;

				try {
					// Use Function constructor to evaluate code in a safer way
					const asyncFunction = new Function(`return (async () => { ${data.code} })()`);
					const result = await asyncFunction(); // Await the result of the async function

					if (cb) {
						cb(result);
					}
				} catch (error) {
					console.error('Error executing code:', error);
				}
			} else if (type === 'hitl_request') {
				// HITL: UnifiedAgent 가 도구 실행 직전에 멈춤. 사용자 결정 (Approve/Reject)
				// 후 resumeChatHITL 호출로 그래프를 깨움. interrupts 안의 action_requests 를
				// 메시지에 박아 ResponseMessage 가 ToolApprovalCard 로 렌더한다.
				const interrupts = data?.interrupts ?? [];
				const actionRequests: any[] = [];
				for (const interrupt of interrupts) {
					for (const req of interrupt?.action_requests ?? []) {
						actionRequests.push(req);
					}
				}
				message.hitl_pending = {
					thread_id: data?.thread_id,
					message_id: data?.message_id,
					actions: actionRequests,
					decisions: actionRequests.map(() => null),
					// resume 시 같은 chain 의 child 로 이어가도록 첫 invocation 의
					// chain_run_id / trace_id 를 보존. 없으면 백엔드가 새 chain 시작.
					chain_run_id: data?.chain_run_id ?? null,
					trace_id: data?.trace_id ?? null
				};
				message.done = true; // SSE 가 hitl_pending 으로 종료된 상태
			} else if (type === 'input') {
				eventCallback = cb;

				eventConfirmationInput = true;
				showEventConfirmation = true;

				eventConfirmationTitle = data.title;
				eventConfirmationMessage = data.message;
				eventConfirmationInputPlaceholder = data.placeholder;
				eventConfirmationInputValue = data?.value ?? '';
			} else {
				console.log('Unknown message type', data);
			}

			history.messages[event.message_id] = message;
		}
	};

	const onMessageHandler = async (event: {
		origin: string;
		data: { type: string; text: string };
	}) => {
		if (event.origin !== window.origin) {
			return;
		}

		// Replace with your iframe's origin
		if (event.data.type === 'input:prompt') {
			console.debug(event.data.text);

			const inputElement = document.getElementById('chat-input');

			if (inputElement) {
				prompt = event.data.text;
				inputElement.focus();
			}
		}

		if (event.data.type === 'action:submit') {
			console.debug(event.data.text);

			if (prompt !== '') {
				await tick();
				submitPrompt(prompt);
			}
		}

		if (event.data.type === 'input:prompt:submit') {
			console.debug(event.data.text);

			if (event.data.text !== '') {
				await tick();
				submitPrompt(event.data.text);
			}
		}
	};

	const handleSocketDisconnect = () => {
		// Socket disconnected during streaming — mark the last assistant message as done
		if (!history?.messages) return;

		const messages = createMessagesList(history, history.currentId);
		const lastMessage = messages.at(-1);

		if (lastMessage?.role === 'assistant' && !lastMessage.done) {
			lastMessage.done = true;
			lastMessage.error = {
				content: $i18n.t('Connection lost. Please check your network and try again.')
			};
			history.messages[lastMessage.id] = lastMessage;
			history = history;
		}
	};

	onMount(async () => {
		console.log('mounted');
		window.addEventListener('message', onMessageHandler);
		$socket?.on('chat-events', chatEventHandler);
		$socket?.on('disconnect', handleSocketDisconnect);

		// Load image connections for dropdown
		(async () => {
			try {
				allImageConnections = await getImageConnectionsList(localStorage.token);
			} catch (e) {
				// Image connections not available
			}
		})();

		// Gmail/Calendar 토글의 5축 게이트 중 OAuth 축 — Google 연결 + 기능별 scope.
		(async () => {
			try {
				const connections = await getMyEmailConnections(localStorage.token);
				const google = connections?.find((c) => c.provider === 'google' && c.connected);
				googleScopes = {
					connected: !!google,
					gmail: !!google?.features?.gmail,
					calendar: !!google?.features?.calendar,
					drive: !!google?.features?.drive
				};
			} catch (e) {
				googleScopes = { connected: false, gmail: false, calendar: false, drive: false };
			}
		})();

		// Reset chatId when mounting without chatIdProp (home page).
		// Without this, navigating from /c/{id} to / via logo click
		// leaves the old chatId in the store, skipping initNewChat.
		if (!chatIdProp && $chatId) {
			await chatId.set('');
		}

		if (!$chatId) {
			chatIdUnsubscriber = chatId.subscribe(async (value) => {
				if (!value) {
					await tick(); // Wait for DOM updates
					await initNewChat();
				}
			});
		} else {
			if ($temporaryChatEnabled) {
				await goto('/');
			}
		}

		if (localStorage.getItem(`chat-input-${chatIdProp}`)) {
			try {
				const input = JSON.parse(localStorage.getItem(`chat-input-${chatIdProp}`));
				prompt = input.prompt;
				files = input.files;
				selectedToolIds = input.selectedToolIds;
				webSearchEnabled = input.webSearchEnabled;
				imageGenerationEnabled = input.imageGenerationEnabled;
				selectedImageConnectionIdx = input.selectedImageConnectionIdx ?? null;
			} catch (e) {
				prompt = '';
				files = [];
				selectedToolIds = [];
				webSearchEnabled = false;
				imageGenerationEnabled = false;
				selectedImageConnectionIdx = null;
			}
		}

		showControls.subscribe(async (value) => {
			if (controlPane && !$mobile) {
				try {
					if (value) {
						controlPaneComponent.openPane();
					} else {
						controlPane.collapse();
					}
				} catch (e) {
					// ignore
				}
			}

			if (!value) {
				showCallOverlay.set(false);
				showOverview.set(false);
				showArtifacts.set(false);
			}
		});

		const chatInput = document.getElementById('chat-input');
		chatInput?.focus();

		chats.subscribe(() => {});
	});

	onDestroy(() => {
		taskIds = null;
		chatIdUnsubscriber?.();
		window.removeEventListener('message', onMessageHandler);
		$socket?.off('chat-events', chatEventHandler);
		$socket?.off('disconnect', handleSocketDisconnect);
	});

	// File upload functions

	const uploadGoogleDriveFile = async (fileData) => {
		console.log('Starting uploadGoogleDriveFile with:', {
			id: fileData.id,
			name: fileData.name,
			url: fileData.url,
			headers: {
				Authorization: `Bearer ${token}`
			}
		});

		// Validate input
		if (!fileData?.id || !fileData?.name || !fileData?.url || !fileData?.headers?.Authorization) {
			throw new Error('Invalid file data provided');
		}

		const tempItemId = uuidv4();
		const fileItem = {
			type: 'file',
			file: '',
			id: null,
			url: fileData.url,
			name: fileData.name,
			collection_name: '',
			status: 'uploading',
			error: '',
			itemId: tempItemId,
			size: 0
		};

		try {
			files = [...files, fileItem];
			console.log('Processing web file with URL:', fileData.url);

			// Configure fetch options with proper headers
			const fetchOptions = {
				headers: {
					Authorization: fileData.headers.Authorization,
					Accept: '*/*'
				},
				method: 'GET'
			};

			// Attempt to fetch the file
			console.log('Fetching file content from Google Drive...');
			const fileResponse = await fetch(fileData.url, fetchOptions);

			if (!fileResponse.ok) {
				const errorText = await fileResponse.text();
				throw new Error(`Failed to fetch file (${fileResponse.status}): ${errorText}`);
			}

			// Get content type from response
			const contentType = fileResponse.headers.get('content-type') || 'application/octet-stream';
			console.log('Response received with content-type:', contentType);

			// Convert response to blob
			console.log('Converting response to blob...');
			const fileBlob = await fileResponse.blob();

			if (fileBlob.size === 0) {
				throw new Error('Retrieved file is empty');
			}

			console.log('Blob created:', {
				size: fileBlob.size,
				type: fileBlob.type || contentType
			});

			// Create File object with proper MIME type
			const file = new File([fileBlob], fileData.name, {
				type: fileBlob.type || contentType
			});

			console.log('File object created:', {
				name: file.name,
				size: file.size,
				type: file.type
			});

			if (file.size === 0) {
				throw new Error('Created file is empty');
			}

			// Upload file to server
			console.log('Uploading file to server...');
			const uploadedFile = await uploadFile(localStorage.token, file, 'local', true, 'chat');

			if (!uploadedFile) {
				throw new Error('Server returned null response for file upload');
			}

			console.log('File uploaded successfully:', uploadedFile);

			// Update file item with upload results
			fileItem.status = 'uploaded';
			fileItem.file = uploadedFile;
			fileItem.id = uploadedFile.id;
			fileItem.size = file.size;
			fileItem.collection_name = uploadedFile?.meta?.collection_name;
			fileItem.url = `${WEBUI_API_BASE_URL}/files/${uploadedFile.id}`;

			files = files;
			toast.success($i18n.t('File uploaded successfully'));
		} catch (e) {
			console.error('Error uploading file:', e);
			files = files.filter((f) => f.itemId !== tempItemId);
			toast.error(
				$i18n.t('Error uploading file: {{error}}', {
					error: e.message || 'Unknown error'
				})
			);
		}
	};

	const uploadWeb = async (url) => {
		console.log(url);

		const fileItem = {
			type: 'doc',
			name: url,
			collection_name: '',
			status: 'uploading',
			url: url,
			error: ''
		};

		try {
			files = [...files, fileItem];
			const res = await processWeb(localStorage.token, '', url);

			if (res) {
				fileItem.status = 'uploaded';
				fileItem.collection_name = res.collection_name;
				fileItem.file = {
					...res.file,
					...fileItem.file
				};

				files = files;
			}
		} catch (e) {
			// Remove the failed doc from the files array
			files = files.filter((f) => f.name !== url);
			toast.error(JSON.stringify(e));
		}
	};

	const uploadYoutubeTranscription = async (url) => {
		console.log(url);

		const fileItem = {
			type: 'doc',
			name: url,
			collection_name: '',
			status: 'uploading',
			context: 'full',
			url: url,
			error: ''
		};

		try {
			files = [...files, fileItem];
			const res = await processYoutubeVideo(localStorage.token, url);

			if (res) {
				fileItem.status = 'uploaded';
				fileItem.collection_name = res.collection_name;
				fileItem.file = {
					...res.file,
					...fileItem.file
				};
				files = files;
			}
		} catch (e) {
			// Remove the failed doc from the files array
			files = files.filter((f) => f.name !== url);
			toast.error($i18n.t(`${e}`));
		}
	};

	//////////////////////////
	// Web functions
	//////////////////////////

	const initNewChat = async () => {
		taskIds = null;

		if ($page.url.searchParams.get('models')) {
			selectedModels = $page.url.searchParams.get('models')?.split(',');
		} else if ($page.url.searchParams.get('model')) {
			const urlModels = $page.url.searchParams.get('model')?.split(',');

			if (urlModels.length === 1) {
				const m = $models.find((m) => m.id === urlModels[0]);
				if (!m) {
					const modelSelectorButton = document.getElementById('model-selector-0-button');
					if (modelSelectorButton) {
						modelSelectorButton.click();
						await tick();

						const modelSelectorInput = document.getElementById('model-search-input');
						if (modelSelectorInput) {
							modelSelectorInput.focus();
							modelSelectorInput.value = urlModels[0];
							modelSelectorInput.dispatchEvent(new Event('input'));
						}
					}
				} else {
					selectedModels = urlModels;
				}
			} else {
				selectedModels = urlModels;
			}
		} else {
			// 새 채팅(로고 클릭 등)에서는 사용자 기본 모델 우선: 설정 > 전역 기본값 > 세션(이전 채팅방 모델)
			const fromSettings = $settings?.models?.length
				? $settings.models
				: null;
			const fromConfig = $config?.default_models
				? $config.default_models.split(',').filter((id: string) => id?.trim())
				: null;
			const fromSession = sessionStorage.selectedModels
				? JSON.parse(sessionStorage.selectedModels)
				: null;

			if (fromSettings?.length) {
				selectedModels = fromSettings;
			} else if (fromConfig?.length) {
				selectedModels = fromConfig;
			} else if (fromSession?.length) {
				selectedModels = fromSession;
				sessionStorage.removeItem('selectedModels');
			} else {
				selectedModels = [];
			}
		}

		selectedModels = selectedModels.filter((modelId) => $models.map((m) => m.id).includes(modelId));
		if (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {
			// 필터 후 비었으면 사용자 기본/전역 기본으로 보정 후, 없으면 첫 번째 모델
			const fallbackSettings = $settings?.models?.length ? $settings.models : null;
			const fallbackConfig = $config?.default_models
				? $config.default_models.split(',').filter((id: string) => id?.trim())
				: null;
			const validFallback = (ids: string[]) =>
				ids.filter((id) => $models.map((m) => m.id).includes(id));

			const fromSettingsValid = validFallback(fallbackSettings ?? []);
			const fromConfigValid = validFallback(fallbackConfig ?? []);
			if (fromSettingsValid.length > 0) {
				selectedModels = fromSettingsValid;
			} else if (fromConfigValid.length > 0) {
				selectedModels = fromConfigValid;
			} else if ($models.length > 0) {
				selectedModels = [$models[0].id];
			} else {
				selectedModels = [''];
			}
		}

		await showControls.set(false);
		await showCallOverlay.set(false);
		await showOverview.set(false);
		await showArtifacts.set(false);

		selectedImageConnectionIdx = null;
		selectedToolIds = [];
		// 새 채팅은 항상 off 에서 시작 (직전 채팅의 Google Workspace 토글 누수 방지)
		gmailEnabled = false;
		calendarEnabled = false;
		driveEnabled = false;

		// Auto-enable features based on model/agent capabilities
		updateModelCapabilities();

		if ($page.url.pathname.includes('/c/')) {
			window.history.replaceState(history.state, '', `/`);
		}

		autoScroll = true;

		await chatId.set('');
		await chatTitle.set('');

		history = {
			messages: {},
			currentId: null
		};

		chatFiles = [];
		params = {};

		// Project context injection
		let projectDefaultModelId: string | null = null;
		const projectContextStr = sessionStorage.getItem('projectContext');
		if (projectContextStr) {
			try {
				const projectContext = JSON.parse(projectContextStr);
				sessionStorage.removeItem('projectContext');

				if (projectContext.type === 'data_analysis') {
					// Data analysis project: skip RAG, pass project context for code interpreter
					params = {
						...params,
						_projectId: projectContext.id,
						_projectType: 'data_analysis',
						_projectFileMetadata: projectContext.file_metadata
					};
				} else {
					// General project: use RAG collection
					if (projectContext.knowledge_id) {
						const knowledgeFile = {
							type: 'collection',
							name: projectContext.name,
							collection_name: projectContext.knowledge_id
						};
						chatFiles = [knowledgeFile];
						files = [knowledgeFile];
					}
				}

				if (projectContext.instructions) {
					params = { ...params, _projectInstructions: projectContext.instructions };
				}
				if (projectContext.id) {
					params = { ...params, _projectId: projectContext.id };
				}
				if (projectContext.default_model_id) {
					projectDefaultModelId = projectContext.default_model_id;
				}
			} catch (e) {
				console.error('Failed to parse project context:', e);
			}
		}

		if ($page.url.searchParams.get('youtube')) {
			uploadYoutubeTranscription(
				`https://www.youtube.com/watch?v=${$page.url.searchParams.get('youtube')}`
			);
		}
		if ($page.url.searchParams.get('web-search') === 'true') {
			webSearchEnabled = true;
		}

		if ($page.url.searchParams.get('image-generation') === 'true') {
			imageGenerationEnabled = true;
		}

		if ($page.url.searchParams.get('tools')) {
			selectedToolIds = $page.url.searchParams
				.get('tools')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		} else if ($page.url.searchParams.get('tool-ids')) {
			selectedToolIds = $page.url.searchParams
				.get('tool-ids')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		}

		if ($page.url.searchParams.get('call') === 'true') {
			showCallOverlay.set(true);
			showControls.set(true);
		}

		if ($page.url.searchParams.get('q')) {
			prompt = $page.url.searchParams.get('q') ?? '';

			if (prompt) {
				await tick();
				submitPrompt(prompt);
			}
		}

		selectedModels = selectedModels.map((modelId) =>
			$models.map((m) => m.id).includes(modelId) ? modelId : ''
		);

		// Project default model takes precedence over all other model selection logic
		if (projectDefaultModelId) {
			selectedModels = [projectDefaultModelId];
		}

		const userSettings = await getUserSettings(localStorage.token);

		if (userSettings) {
			settings.set(userSettings.ui);
		} else {
			settings.set(JSON.parse(localStorage.getItem('settings') ?? '{}'));
		}

		const chatInput = document.getElementById('chat-input');
		setTimeout(() => chatInput?.focus(), 0);
	};

	const loadChat = async () => {
		chatId.set(chatIdProp);
		chat = await getChatById(localStorage.token, $chatId).catch(async (error) => {
			await goto('/');
			return null;
		});

		if (chat) {
			tags = await getTagsById(localStorage.token, $chatId).catch(async (error) => {
				return [];
			});

			const chatContent = chat.chat;

			if (chatContent) {
				console.log(chatContent);

				selectedModels =
					(chatContent?.models ?? undefined) !== undefined
						? chatContent.models
						: [chatContent.models ?? ''];

				// Fallback: if models empty and chat belongs to a schedule, use schedule's target_model_id
				const scheduleId = chat?.meta?.schedule_id;
				if (
					scheduleId &&
					(selectedModels.length === 0 ||
						(selectedModels.length === 1 && selectedModels[0] === ''))
				) {
					try {
						const schedule = await getScheduleById(localStorage.token, scheduleId);
						if (schedule?.target_model_id) {
							selectedModels = [schedule.target_model_id];
						}
					} catch {
						// Schedule may have been deleted
					}
				}

				history =
					(chatContent?.history ?? undefined) !== undefined
						? chatContent.history
						: convertMessagesToHistory(chatContent.messages);

				chatTitle.set(chatContent.title);

				const userSettings = await getUserSettings(localStorage.token);

				if (userSettings) {
					await settings.set(userSettings.ui);
				} else {
					await settings.set(JSON.parse(localStorage.getItem('settings') ?? '{}'));
				}

				params = chatContent?.params ?? {};
				chatFiles = chatContent?.files ?? [];

				autoScroll = true;
				await tick();

				// 저장된 채팅의 마지막 Google Workspace 토글 상태 복원.
				// await tick() 이후에 둔다 — selectedModels 재할당이 트리거한
				// updateModelCapabilities()가 tick 에서 flush 되며 capability 기본값으로
				// 토글을 덮어쓰므로, 저장된 값이 항상 이기도록 그 다음에 복원한다.
				// (reactive 블록이 아닌 loadChat 함수 안에서 수행 — params 재할당 무한루프 회피)
				const googleWorkspace = params?.google_workspace;
				if (googleWorkspace) {
					gmailEnabled = !!googleWorkspace.gmail;
					calendarEnabled = !!googleWorkspace.calendar;
					driveEnabled = !!googleWorkspace.drive;
				}

				if (history.currentId) {
					for (const message of Object.values(history.messages)) {
						if (message.role === 'assistant') {
							message.done = true;
						}
					}
				}

				const taskRes = await getTaskIdsByChatId(localStorage.token, $chatId).catch((error) => {
					return null;
				});

				if (taskRes) {
					taskIds = taskRes.task_ids;
				}

				await tick();

				return true;
			} else {
				return null;
			}
		}
	};

	const scrollToBottom = async () => {
		await tick();
		if (messagesContainerElement) {
			messagesContainerElement.scrollTop = messagesContainerElement.scrollHeight;
		}
	};
	const chatCompletedHandler = async (chatId, modelId, responseMessageId, messages) => {
		const res = await chatCompleted(localStorage.token, {
			model: modelId,
			messages: messages.map((m) => ({
				id: m.id,
				role: m.role,
				content: m.content,
				info: m.info ? m.info : undefined,
				timestamp: m.timestamp,
				...(m.usage ? { usage: m.usage } : {}),
				...(m.sources ? { sources: m.sources } : {})
			})),
			model_item: $models.find((m) => m.id === modelId),
			chat_id: chatId,
			session_id: $socket?.id,
			id: responseMessageId
		}).catch((error) => {
			toast.error($i18n.t(`${error}`));
			messages.at(-1).error = { content: error };

			return null;
		});

		if (res !== null && res.messages) {
			// Update chat history with the new messages
			for (const message of res.messages) {
				if (message?.id) {
					// Add null check for message and message.id
					history.messages[message.id] = {
						...history.messages[message.id],
						...(history.messages[message.id].content !== message.content
							? { originalContent: history.messages[message.id].content }
							: {}),
						...message
					};
				}
			}
		}

		await tick();

		if ($chatId == chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, chatId, {
					models: selectedModels,
					messages: messages,
					history: history,
					params: params,
					files: chatFiles
				});

				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage, true));
			}
		}

		taskIds = null;
	};

	const chatActionHandler = async (chatId, actionId, modelId, responseMessageId, event = null) => {
		const messages = createMessagesList(history, responseMessageId);

		const res = await chatAction(localStorage.token, actionId, {
			model: modelId,
			messages: messages.map((m) => ({
				id: m.id,
				role: m.role,
				content: m.content,
				info: m.info ? m.info : undefined,
				timestamp: m.timestamp,
				...(m.sources ? { sources: m.sources } : {})
			})),
			...(event ? { event: event } : {}),
			model_item: $models.find((m) => m.id === modelId),
			chat_id: chatId,
			session_id: $socket?.id,
			id: responseMessageId
		}).catch((error) => {
			toast.error($i18n.t(`${error}`));
			messages.at(-1).error = { content: error };
			return null;
		});

		if (res !== null && res.messages) {
			// Update chat history with the new messages
			for (const message of res.messages) {
				history.messages[message.id] = {
					...history.messages[message.id],
					...(history.messages[message.id].content !== message.content
						? { originalContent: history.messages[message.id].content }
						: {}),
					...message
				};
			}
		}

		if ($chatId == chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, chatId, {
					models: selectedModels,
					messages: messages,
					history: history,
					params: params,
					files: chatFiles
				});

				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage, true));
			}
		}
	};

	const getChatEventEmitter = async (modelId: string, chatId: string = '') => {
		return setInterval(() => {
			$socket?.emit('usage', {
				action: 'chat',
				model: modelId,
				chat_id: chatId
			});
		}, 1000);
	};

	const createMessagePair = async (userPrompt) => {
		prompt = '';
		if (selectedModels.length === 0) {
			toast.error($i18n.t('Model not selected'));
		} else {
			const modelId = selectedModels[0];
			const model = $models.filter((m) => m.id === modelId).at(0);

			const messages = createMessagesList(history, history.currentId);
			const parentMessage = messages.length !== 0 ? messages.at(-1) : null;

			const userMessageId = uuidv4();
			const responseMessageId = uuidv4();

			const userMessage = {
				id: userMessageId,
				parentId: parentMessage ? parentMessage.id : null,
				childrenIds: [responseMessageId],
				role: 'user',
				content: userPrompt ? userPrompt : `[PROMPT] ${userMessageId}`,
				timestamp: Math.floor(Date.now() / 1000)
			};

			const responseMessage = {
				id: responseMessageId,
				parentId: userMessageId,
				childrenIds: [],
				role: 'assistant',
				content: `[RESPONSE] ${responseMessageId}`,
				done: true,

				model: modelId,
				modelName: model.name ?? model.id,
				modelIdx: 0,
				timestamp: Math.floor(Date.now() / 1000)
			};

			if (parentMessage) {
				parentMessage.childrenIds.push(userMessageId);
				history.messages[parentMessage.id] = parentMessage;
			}
			history.messages[userMessageId] = userMessage;
			history.messages[responseMessageId] = responseMessage;

			history.currentId = responseMessageId;

			await tick();

			if (autoScroll) {
				scrollToBottom();
			}

			if (messages.length === 0) {
				await initChatHandler(history);
			} else {
				await saveChatHandler($chatId, history);
			}
		}
	};

	const addMessages = async ({ modelId, parentId, messages }) => {
		const model = $models.filter((m) => m.id === modelId).at(0);

		let parentMessage = history.messages[parentId];
		let currentParentId = parentMessage ? parentMessage.id : null;
		for (const message of messages) {
			let messageId = uuidv4();

			if (message.role === 'user') {
				const userMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = userMessage;
				parentMessage = userMessage;
				currentParentId = messageId;
			} else {
				const responseMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					done: true,
					model: model.id,
					modelName: model.name ?? model.id,
					modelIdx: 0,
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = responseMessage;
				parentMessage = responseMessage;
				currentParentId = messageId;
			}
		}

		history.currentId = currentParentId;
		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		if (messages.length === 0) {
			await initChatHandler(history);
		} else {
			await saveChatHandler($chatId, history);
		}
	};

	const chatCompletionEventHandler = async (data, message, chatId) => {
		const { id, done, choices, content, sources, selected_model_id, error, usage } = data;

		if (error) {
			await handleOpenAIError(error, message);
		}

		if (sources) {
			message.sources = sources;
		}

		if (choices) {
			if (choices[0]?.message?.content) {
				// Non-stream response
				message.content += choices[0]?.message?.content;
			} else {
				// Stream response
				let value = choices[0]?.delta?.content ?? '';
				if (message.content == '' && value == '\n') {
					console.log('Empty response');
				} else {
					message.content += value;

					if (navigator.vibrate && ($settings?.hapticFeedback ?? false)) {
						navigator.vibrate(5);
					}

					// Emit chat event for TTS
					const messageContentParts = getMessageContentParts(
						message.content,
						$config?.audio?.tts?.split_on ?? 'punctuation'
					);
					messageContentParts.pop();

					// dispatch only last sentence and make sure it hasn't been dispatched before
					if (
						messageContentParts.length > 0 &&
						messageContentParts[messageContentParts.length - 1] !== message.lastSentence
					) {
						message.lastSentence = messageContentParts[messageContentParts.length - 1];
						eventTarget.dispatchEvent(
							new CustomEvent('chat', {
								detail: {
									id: message.id,
									content: messageContentParts[messageContentParts.length - 1]
								}
							})
						);
					}
				}
			}
		}

		if (content) {
			// REALTIME_CHAT_SAVE is disabled
			message.content = content;

			if (navigator.vibrate && ($settings?.hapticFeedback ?? false)) {
				navigator.vibrate(5);
			}

			// Emit chat event for TTS
			const messageContentParts = getMessageContentParts(
				message.content,
				$config?.audio?.tts?.split_on ?? 'punctuation'
			);
			messageContentParts.pop();

			// dispatch only last sentence and make sure it hasn't been dispatched before
			if (
				messageContentParts.length > 0 &&
				messageContentParts[messageContentParts.length - 1] !== message.lastSentence
			) {
				message.lastSentence = messageContentParts[messageContentParts.length - 1];
				eventTarget.dispatchEvent(
					new CustomEvent('chat', {
						detail: {
							id: message.id,
							content: messageContentParts[messageContentParts.length - 1]
						}
					})
				);
			}
		}

		if (selected_model_id) {
			message.selectedModelId = selected_model_id;
			message.arena = true;
		}

		if (usage) {
			message.usage = usage;
		}

		history.messages[message.id] = message;

		if (done) {
			message.done = true;

			if ($settings.responseAutoCopy) {
				copyToClipboard(message.content);
			}

			if ($settings.responseAutoPlayback && !$showCallOverlay) {
				await tick();
				document.getElementById(`speak-button-${message.id}`)?.click();
			}

			// Emit chat event for TTS
			let lastMessageContentPart =
				getMessageContentParts(message.content, $config?.audio?.tts?.split_on ?? 'punctuation')?.at(
					-1
				) ?? '';
			if (lastMessageContentPart) {
				eventTarget.dispatchEvent(
					new CustomEvent('chat', {
						detail: { id: message.id, content: lastMessageContentPart }
					})
				);
			}
			eventTarget.dispatchEvent(
				new CustomEvent('chat:finish', {
					detail: {
						id: message.id,
						content: message.content
					}
				})
			);

			history.messages[message.id] = message;
			await chatCompletedHandler(
				chatId,
				message.model,
				message.id,
				createMessagesList(history, message.id)
			);
		}

		console.log(data);
		if (autoScroll) {
			scrollToBottom();
		}
	};

	//////////////////////////
	// Chat functions
	//////////////////////////

	const submitPrompt = async (userPrompt, { _raw = false } = {}) => {
		console.log('submitPrompt', userPrompt, $chatId);

		const messages = createMessagesList(history, history.currentId);
		const _selectedModels = selectedModels.map((modelId) =>
			$models.map((m) => m.id).includes(modelId) ? modelId : ''
		);
		if (JSON.stringify(selectedModels) !== JSON.stringify(_selectedModels)) {
			selectedModels = _selectedModels;
		}

		if (userPrompt === '' && files.length === 0) {
			toast.error($i18n.t('Please enter a prompt'));
			return;
		}
		if (selectedModels.includes('')) {
			toast.error($i18n.t('Model not selected'));
			return;
		}

		if (messages.length != 0 && messages.at(-1).done != true) {
			// Response not done
			return;
		}
		if (messages.length != 0 && messages.at(-1).error && !messages.at(-1).content) {
			// Error in response
			toast.error($i18n.t(`Oops! There was an error in the previous response.`));
			return;
		}
		if (
			files.length > 0 &&
			files.filter((file) => file.type !== 'image' && file.status === 'uploading').length > 0
		) {
			toast.error(
				$i18n.t(`Oops! There are files still uploading. Please wait for the upload to complete.`)
			);
			return;
		}
		if (
			($config?.file?.max_count ?? null) !== null &&
			files.length + chatFiles.length > $config?.file?.max_count
		) {
			toast.error(
				$i18n.t(`You can only chat with a maximum of {{maxCount}} file(s) at a time.`, {
					maxCount: $config?.file?.max_count
				})
			);
			return;
		}

		// Google Workspace 토글 상태를 채팅에 기억시킨다 (전송 시점의 사용자 의도값).
		// admin/permission/OAuth 게이트는 features 페이로드 생성부에서 재검증되므로 여기선 raw 값만 저장.
		params = {
			...params,
			google_workspace: {
				gmail: gmailEnabled,
				calendar: calendarEnabled,
				drive: driveEnabled
			}
		};

		prompt = '';

		// Reset chat input textarea
		if (!($settings?.richTextInput ?? true)) {
			const chatInputElement = document.getElementById('chat-input');

			if (chatInputElement) {
				await tick();
				chatInputElement.style.height = '';
			}
		}

		const _files = JSON.parse(JSON.stringify(files));
		chatFiles.push(..._files.filter((item) => ['doc', 'file', 'collection'].includes(item.type)));
		chatFiles = chatFiles.filter(
			// Remove duplicates
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		files = [];
		prompt = '';

		// Create user message
		let userMessageId = uuidv4();
		let userMessage = {
			id: userMessageId,
			parentId: messages.length !== 0 ? messages.at(-1).id : null,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			files: _files.length > 0 ? _files : undefined,
			timestamp: Math.floor(Date.now() / 1000), // Unix epoch
			models: selectedModels
		};

		// Add message to history and Set currentId to messageId
		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		// Append messageId to childrenIds of parent message
		if (messages.length !== 0) {
			history.messages[messages.at(-1).id].childrenIds.push(userMessageId);
		}

		// focus on chat input
		const chatInput = document.getElementById('chat-input');
		chatInput?.focus();

		saveSessionSelectedModels();

		// Usage limit check (admin 제외) — 선택된 모델별 per-model 한도 검사
		if ($config?.features?.enable_usage_limit && $user?.role !== 'admin') {
			try {
				const { checkUserUsageLimit } = await import('$lib/apis/users');
				const targetModelIds =
					atSelectedModel !== undefined ? [atSelectedModel.id] : selectedModels;

				let blockedCheck: {
					model_id: string;
					daily_used: number;
					daily_limit: number;
					pct: number;
					source: string;
				} | null = null;
				let warnExplicit = false; // backend exceed_action === 'warn' (이미 100%+)
				let worstPct = 0;

				for (const modelId of targetModelIds) {
					if (!modelId) continue;
					const usageCheck = await checkUserUsageLimit(localStorage.token, modelId);
					if (!usageCheck || !usageCheck.daily_limit || usageCheck.daily_limit <= 0) continue;
					const pct = Math.round((usageCheck.daily_used / usageCheck.daily_limit) * 100);

					if (usageCheck.action === 'block') {
						blockedCheck = {
							model_id: usageCheck.model_id ?? modelId,
							daily_used: usageCheck.daily_used,
							daily_limit: usageCheck.daily_limit,
							pct,
							source: usageCheck.source ?? ''
						};
						break;
					}
					if (usageCheck.action === 'warn') warnExplicit = true;
					if (pct > worstPct) worstPct = pct;
				}

				if (blockedCheck) {
					toast.error(
						$i18n.t(
							"Daily token usage limit exceeded for model '{{model}}' ({{used}}/{{limit}} tokens, {{pct}}%). Source: {{source}}",
							{
								model: blockedCheck.model_id,
								used: blockedCheck.daily_used.toLocaleString(),
								limit: blockedCheck.daily_limit.toLocaleString(),
								pct: blockedCheck.pct,
								source: blockedCheck.source
							}
						)
					);
					// 사용자 메시지 롤백
					if (messages.length !== 0 && history.messages[messages.at(-1).id]) {
						history.messages[messages.at(-1).id].childrenIds = history.messages[
							messages.at(-1).id
						].childrenIds.filter((id) => id !== userMessageId);
					}
					delete history.messages[userMessageId];
					history.currentId = messages.length > 0 ? messages.at(-1).id : null;
					return;
				} else if (warnExplicit) {
					toast.error(
						$i18n.t('Daily usage limit exceeded ({{pct}}%). Usage is being monitored.', {
							pct: worstPct
						})
					);
				} else if (worstPct >= 95) {
					toast.error(
						$i18n.t('You have used {{pct}}% of your daily limit. Limit will be reached soon.', {
							pct: worstPct
						})
					);
				} else if (worstPct >= 80) {
					toast.warning($i18n.t('You have used {{pct}}% of your daily limit.', { pct: worstPct }));
				}
			} catch (e) {
				console.error('Usage limit check failed:', e);
			}
		}

		await sendPrompt(history, userPrompt, userMessageId, { newChat: true });
	};

	// HITL: 사용자가 ToolApprovalCard 의 Approve/Reject 클릭 시 호출.
	// pending 카드 모두 결정되면 resumeChatHITL 로 백엔드 호출 → SSE 응답을
	// 같은 message 에 이어 붙임. 도중에 또 interrupt 가 걸리면 socket
	// hitl_request 이벤트로 message.hitl_pending 이 다시 채워진다.
	// GWS/feature 토글 페이로드 — 최초 제출과 HITL resume 둘 다 동일하게 써야
	// resume 턴에서 Gmail/Drive 5축 게이트가 동일하게 통과한다. resume payload 가
	// 이 features 를 빠뜨리면 user_enabled_drive=false → GWS 도구 미등록 → "기능 미활성".
	function getFeaturesPayload() {
		return {
			image_generation:
				$config?.features?.enable_image_generation &&
				($user?.role === 'admin' || $user?.permissions?.features?.image_generation)
					? imageGenerationEnabled
					: false,
			image_connection_idx: selectedImageConnectionIdx,
			web_search:
				$config?.features?.enable_web_search &&
				($user?.role === 'admin' || $user?.permissions?.features?.web_search)
					? webSearchEnabled || ($settings?.webSearch ?? false) === 'always'
					: false,
			gmail:
				$config?.features?.enable_gmail &&
				($user?.role === 'admin' || $user?.permissions?.features?.gmail) &&
				googleScopes.gmail
					? gmailEnabled
					: false,
			calendar:
				$config?.features?.enable_calendar &&
				($user?.role === 'admin' || $user?.permissions?.features?.calendar) &&
				googleScopes.calendar
					? calendarEnabled
					: false,
			drive:
				$config?.features?.enable_drive &&
				($user?.role === 'admin' || $user?.permissions?.features?.drive) &&
				googleScopes.drive
					? driveEnabled
					: false
		};
	}

	const handleHITLDecision = async (
		messageId: string,
		actionIndex: number,
		decision: HITLDecision
	) => {
		const message = history.messages[messageId];
		if (!message?.hitl_pending) return;

		message.hitl_pending.decisions[actionIndex] = decision;
		history.messages[messageId] = message;

		// 모든 결정이 모일 때까지 대기 (다중 action_request 케이스)
		const pending = message.hitl_pending.decisions.findIndex((d: any) => d === null);
		if (pending !== -1) return;

		const decisions = message.hitl_pending.decisions as HITLDecision[];
		const threadId = message.hitl_pending.thread_id;

		// 첫 invocation 의 payload 를 보존해 둔 게 있으면 그걸로, 아니면 현재
		// 메시지 트리에서 재구성. 단순화를 위해 현재 모델 + 메시지 리스트 사용.
		const model = $models.filter((m) => m.id === message.model).at(0);
		if (!model) {
			toast.error($i18n.t('Model not available for resume'));
			return;
		}

		const payload = {
			stream: true,
			model: model.id,
			// GWS 5축 게이트 재통과를 위해 features 보존 (resume 가 누락하면 Drive/Gmail 비활성).
			features: getFeaturesPayload(),
			messages: createMessagesList(history, message.parentId).map((m) => ({
				role: m.role,
				content: m.content
			})),
			// main.py 의 chat_completion 핸들러는 form_data top-level 의 chat_id/id/
			// session_id 를 pop 해 새 metadata 를 만든다 (form_data["metadata"] 안의
			// 같은 키는 무시). 빠지면 metadata.message_id=None → resume 흐름의
			// event_emitter 가 message_id 없이 발행 → 클라이언트가
			// history.messages[null] lookup 실패 → "Awaiting user approval" status
			// 가 영구히 남는다.
			chat_id: $chatId,
			id: messageId,
			session_id: $socket?.id ?? null
		};

		// 카드를 잠그기 위해 pending 플래그 false 토글 — 결정은 이미 박혀있음.
		message.hitl_pending = {
			...message.hitl_pending,
			locked: true
		};
		message.done = false;
		history.messages[messageId] = message;

		try {
			const res = await resumeChatHITL(localStorage.token, $chatId, {
				thread_id: threadId,
				decisions,
				payload,
				chain_run_id: message.hitl_pending?.chain_run_id ?? null,
				trace_id: message.hitl_pending?.trace_id ?? null
			});

			if (!res.body) {
				throw 'empty response body';
			}

			const stream = await createOpenAITextStream(res.body, $settings.splitLargeChunks);
			for await (const update of stream) {
				const { value, done, error } = update;
				if (error) throw error;
				if (done) break;
				if (value) {
					message.content += value;
					history.messages[messageId] = message;
					if (autoScroll) scrollToBottom();
				}
			}
			// hitl_pending 은 socket hitl_request 가 또 와서 덮어쓰지 않는 한 유지
			// (사용자가 어떤 결정을 했는지 카드에 남기기 위함)
			message.done = true;
			history.messages[messageId] = message;
			await saveChatHandler($chatId, history);
		} catch (e) {
			console.error('[HITL] resume failed:', e);
			toast.error($i18n.t('Resume failed: {{error}}', { error: String(e) }));
			message.done = true;
			history.messages[messageId] = message;
		}
	};

	const sendPrompt = async (
		_history,
		prompt: string,
		parentId: string,
		{ modelId = null, modelIdx = null, newChat = false } = {}
	) => {
		if (autoScroll) {
			scrollToBottom();
		}

		let _chatId = JSON.parse(JSON.stringify($chatId));
		_history = JSON.parse(JSON.stringify(_history));

		const responseMessageIds: Record<PropertyKey, string> = {};
		// If modelId is provided, use it, else use selected model
		let selectedModelIds = modelId
			? [modelId]
			: atSelectedModel !== undefined
				? [atSelectedModel.id]
				: selectedModels;

		// Create response messages for each selected model
		for (const [_modelIdx, modelId] of selectedModelIds.entries()) {
			const model = $models.filter((m) => m.id === modelId).at(0);

			if (model) {
				let responseMessageId = uuidv4();
				let responseMessage = {
					parentId: parentId,
					id: responseMessageId,
					childrenIds: [],
					role: 'assistant',
					content: '',
					model: model.id,
					modelName: model.name ?? model.id,
					modelIdx: modelIdx ? modelIdx : _modelIdx,
					userContext: null,
					timestamp: Math.floor(Date.now() / 1000) // Unix epoch
				};

				// Add message to history and Set currentId to messageId
				history.messages[responseMessageId] = responseMessage;
				history.currentId = responseMessageId;

				// Append messageId to childrenIds of parent message
				if (parentId !== null && history.messages[parentId]) {
					// Add null check before accessing childrenIds
					history.messages[parentId].childrenIds = [
						...history.messages[parentId].childrenIds,
						responseMessageId
					];
				}

				responseMessageIds[`${modelId}-${modelIdx ? modelIdx : _modelIdx}`] = responseMessageId;
			}
		}
		history = history;

		// Create new chat if newChat is true and first user message
		if (newChat && _history.messages[_history.currentId].parentId === null) {
			_chatId = await initChatHandler(_history);
		}

		await tick();

		_history = JSON.parse(JSON.stringify(history));
		// Save chat after all messages have been created
		await saveChatHandler(_chatId, _history);

		await Promise.all(
			selectedModelIds.map(async (modelId, _modelIdx) => {
				console.log('modelId', modelId);
				const model = $models.filter((m) => m.id === modelId).at(0);

				if (model) {
					const messages = createMessagesList(_history, parentId);

					let responseMessageId =
						responseMessageIds[`${modelId}-${modelIdx ? modelIdx : _modelIdx}`];
					let responseMessage = _history.messages[responseMessageId];

					let userContext = null;
					if ($settings?.memory ?? false) {
						if (userContext === null) {
							const res = await queryMemory(localStorage.token, prompt).catch((error) => {
								toast.error($i18n.t(`${error}`));
								return null;
							});
							if (res) {
								if (res.documents[0].length > 0) {
									userContext = res.documents[0].reduce((acc, doc, index) => {
										const createdAtTimestamp = res.metadatas[0][index].created_at;
										const createdAtDate = new Date(createdAtTimestamp * 1000)
											.toISOString()
											.split('T')[0];
										return `${acc}${index + 1}. [${createdAtDate}]. ${doc}\n`;
									}, '');
								}

								console.log(userContext);
							}
						}
					}
					responseMessage.userContext = userContext;

					const chatEventEmitter = await getChatEventEmitter(model.id, _chatId);

					scrollToBottom();
					await sendPromptSocket(_history, model, responseMessageId, _chatId);

					if (chatEventEmitter) clearInterval(chatEventEmitter);
				} else {
					toast.error($i18n.t(`Model {{modelId}} not found`, { modelId }));
				}
			})
		);

		currentChatPage.set(1);
		chats.set(await getChatList(localStorage.token, $currentChatPage, true));
	};

	const sendPromptSocket = async (_history, model, responseMessageId, _chatId) => {
		const responseMessage = _history.messages[responseMessageId];
		const userMessage = _history.messages[responseMessage.parentId];

		let files = JSON.parse(JSON.stringify(chatFiles));
		files.push(
			...(userMessage?.files ?? []).filter((item) =>
				['doc', 'file', 'collection'].includes(item.type)
			),
			...(responseMessage?.files ?? []).filter((item) => ['web_search_results'].includes(item.type))
		);
		// Remove duplicates
		files = files.filter(
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		scrollToBottom();
		eventTarget.dispatchEvent(
			new CustomEvent('chat:start', {
				detail: {
					id: responseMessageId
				}
			})
		);
		await tick();

		const stream =
			model?.info?.params?.stream_response ??
			$settings?.params?.stream_response ??
			params?.stream_response ??
			true;

		const _projectInstructions = params?._projectInstructions ?? '';

		let messages = [
			params?.system ||
			$settings.system ||
			(responseMessage?.userContext ?? null) ||
			_projectInstructions
				? {
						role: 'system',
						content: `${_projectInstructions ? `${_projectInstructions}\n\n` : ''}${promptTemplate(
							params?.system ?? $settings?.system ?? '',
							$user?.name,
							$settings?.userLocation
								? await getAndUpdateUserLocation(localStorage.token).catch((err) => {
										console.error(err);
										return undefined;
									})
								: undefined
						)}${
							(responseMessage?.userContext ?? null)
								? `\n\nUser Context:\n${responseMessage?.userContext ?? ''}`
								: ''
						}`
					}
				: undefined,
			...createMessagesList(_history, responseMessageId).map((message) => ({
				...message,
				content: processDetails(message.content)
			}))
		].filter((message) => message);

		messages = messages
			.map((message, idx, arr) => ({
				role: message.role,
				...((message.files?.filter((file) => file.type === 'image').length > 0 ?? false) &&
				message.role === 'user'
					? {
							content: [
								{
									type: 'text',
									text: message?.merged?.content ?? message.content
								},
								...message.files
									.filter((file) => file.type === 'image')
									.map((file) => ({
										type: 'image_url',
										image_url: {
											url: file.url
										}
									}))
							]
						}
					: {
							content: message?.merged?.content ?? message.content
						})
			}))
			.filter((message) => message?.role === 'user' || message?.content?.trim());

		const res = await generateOpenAIChatCompletion(
			localStorage.token,
			{
				stream: stream,
				model: model.id,
				messages: messages,
				params: {
					...$settings?.params,
					...params,

					format: $settings.requestFormat ?? undefined,
					keep_alive: $settings.keepAlive ?? undefined,
					stop:
						(params?.stop ?? $settings?.params?.stop ?? undefined)
							? (params?.stop.split(',').map((token) => token.trim()) ?? $settings.params.stop).map(
									(str) => decodeURIComponent(JSON.parse('"' + str.replace(/\"/g, '\\"') + '"'))
								)
							: undefined
				},

				files: (files?.length ?? 0) > 0 ? files : undefined,
				tool_ids: selectedToolIds.length > 0 ? selectedToolIds : undefined,
				tool_servers: $toolServers,

				features: getFeaturesPayload(),
				variables: {
					...getPromptVariables(
						$user?.name,
						$settings?.userLocation
							? await getAndUpdateUserLocation(localStorage.token).catch((err) => {
									console.error(err);
									return undefined;
								})
							: undefined
					)
				},
				model_item: $models.find((m) => m.id === model.id),

				session_id: $socket?.id,
				chat_id: $chatId,
				id: responseMessageId,

				...(!$temporaryChatEnabled &&
				(messages.length == 1 ||
					(messages.length == 2 &&
						messages.at(0)?.role === 'system' &&
						messages.at(1)?.role === 'user')) &&
				(selectedModels[0] === model.id || atSelectedModel !== undefined)
					? {
							background_tasks: {
								title_generation: $settings?.title?.auto ?? true,
								tags_generation: $settings?.autoTags ?? true
							}
						}
					: {}),

				...(stream
					? {
							stream_options: {
								include_usage: true
							}
						}
					: {})
			},
			`${WEBUI_BASE_URL}/api`
		).catch(async (error) => {
			const message = formatBackendError(error, $i18n);
			toast.error(message);

			responseMessage.error = {
				content: message
			};
			responseMessage.done = true;

			history.messages[responseMessageId] = responseMessage;
			history.currentId = responseMessageId;
			await saveChatHandler(_chatId, history);
			return null;
		});

		if (res) {
			if (res.error) {
				await handleOpenAIError(res.error, responseMessage);
				await saveChatHandler(_chatId, history);
			} else {
				if (taskIds) {
					taskIds.push(res.task_id);
				} else {
					taskIds = [res.task_id];
				}
			}
		}

		await tick();
		scrollToBottom();
	};

	const handleOpenAIError = async (error, responseMessage) => {
		let errorMessage = '';
		let innerError;

		if (error) {
			innerError = error;
		}

		console.error(innerError);
		if ('detail' in innerError) {
			// FastAPI error — 구조화 detail 이면 i18n 처리.
			errorMessage = formatBackendError(innerError, $i18n);
			toast.error(errorMessage);
		} else if ('error' in innerError) {
			// OpenAI error
			if ('message' in innerError.error) {
				toast.error(innerError.error.message);
				errorMessage = innerError.error.message;
			} else {
				toast.error(innerError.error);
				errorMessage = innerError.error;
			}
		} else if ('message' in innerError) {
			// OpenAI error
			toast.error(innerError.message);
			errorMessage = innerError.message;
		}

		responseMessage.error = {
			content: $i18n.t(`Uh-oh! There was an issue with the response.`) + '\n' + errorMessage
		};
		responseMessage.done = true;

		if (responseMessage.statusHistory) {
			responseMessage.statusHistory = responseMessage.statusHistory.filter(
				(status) => status.action !== 'knowledge_search'
			);
		}

		history.messages[responseMessage.id] = responseMessage;
	};

	const stopResponse = async () => {
		if (taskIds) {
			for (const taskId of taskIds) {
				const res = await stopTask(localStorage.token, taskId).catch((error) => {
					toast.error($i18n.t(`${error}`));
					return null;
				});
			}

			taskIds = null;

			const responseMessage = history.messages[history.currentId];
			// Set all response messages to done
			for (const messageId of history.messages[responseMessage.parentId].childrenIds) {
				history.messages[messageId].done = true;
			}

			history.messages[history.currentId] = responseMessage;

			if (autoScroll) {
				scrollToBottom();
			}
		}
	};

	const submitMessage = async (parentId, prompt) => {
		let userPrompt = prompt;
		let userMessageId = uuidv4();

		let userMessage = {
			id: userMessageId,
			parentId: parentId,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			models: selectedModels
		};

		if (parentId !== null) {
			history.messages[parentId].childrenIds = [
				...history.messages[parentId].childrenIds,
				userMessageId
			];
		}

		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		await sendPrompt(history, userPrompt, userMessageId);
	};

	const regenerateResponse = async (message) => {
		console.log('regenerateResponse');

		if (history.currentId) {
			let userMessage = history.messages[message.parentId];
			let userPrompt = userMessage.content;

			if (autoScroll) {
				scrollToBottom();
			}

			if ((userMessage?.models ?? [...selectedModels]).length == 1) {
				// If user message has only one model selected, sendPrompt automatically selects it for regeneration
				await sendPrompt(history, userPrompt, userMessage.id);
			} else {
				// If there are multiple models selected, use the model of the response message for regeneration
				// e.g. many model chat
				await sendPrompt(history, userPrompt, userMessage.id, {
					modelId: message.model,
					modelIdx: message.modelIdx
				});
			}
		}
	};

	const continueResponse = async () => {
		console.log('continueResponse');
		const _chatId = JSON.parse(JSON.stringify($chatId));

		if (history.currentId && history.messages[history.currentId].done == true) {
			const responseMessage = history.messages[history.currentId];

			// Add separator before continued response
			if (responseMessage.content && !responseMessage.content.endsWith('\n\n')) {
				responseMessage.content = responseMessage.content.trimEnd() + '\n\n';
			}

			responseMessage.done = false;
			await tick();

			const model = $models
				.filter((m) => m.id === (responseMessage?.selectedModelId ?? responseMessage.model))
				.at(0);

			if (model) {
				await sendPromptSocket(history, model, responseMessage.id, _chatId);
			}
		}
	};

	const mergeResponses = async (messageId, responses, _chatId) => {
		console.log('mergeResponses', messageId, responses);
		const message = history.messages[messageId];
		const mergedResponse = {
			status: true,
			content: ''
		};
		message.merged = mergedResponse;
		history.messages[messageId] = message;

		try {
			const [res, controller] = await generateMoACompletion(
				localStorage.token,
				message.model,
				history.messages[message.parentId].content,
				responses
			);

			if (res && res.ok && res.body) {
				const textStream = await createOpenAITextStream(res.body, $settings.splitLargeChunks);
				for await (const update of textStream) {
					const { value, done, sources, error, usage } = update;
					if (error || done) {
						break;
					}

					if (mergedResponse.content == '' && value == '\n') {
						continue;
					} else {
						mergedResponse.content += value;
						history.messages[messageId] = message;
					}

					if (autoScroll) {
						scrollToBottom();
					}
				}

				await saveChatHandler(_chatId, history);
			} else {
				console.error(res);
			}
		} catch (e) {
			console.error(e);
		}
	};

	const initChatHandler = async (history) => {
		let _chatId = $chatId;

		if (!$temporaryChatEnabled) {
			chat = await createNewChat(localStorage.token, {
				id: _chatId,
				title: $i18n.t('New Chat'),
				models: selectedModels,
				system: $settings.system ?? undefined,
				params: params,
				history: history,
				messages: createMessagesList(history, history.currentId),
				tags: [],
				timestamp: Date.now()
			});

			_chatId = chat.id;
			await chatId.set(_chatId);

			// Link chat to project if initiated from a project
			if (params?._projectId) {
				try {
					await addChatToProject(localStorage.token, params._projectId, _chatId);
				} catch (e) {
					console.error('Failed to add chat to project:', e);
				}
			}

			await chats.set(await getChatList(localStorage.token, $currentChatPage, true));
			currentChatPage.set(1);

			window.history.replaceState(history.state, '', `/c/${_chatId}`);
		} else {
			_chatId = 'local';
			await chatId.set('local');
		}
		await tick();

		return _chatId;
	};

	const saveChatHandler = async (_chatId, history) => {
		if ($chatId == _chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, _chatId, {
					models: selectedModels,
					history: history,
					messages: createMessagesList(history, history.currentId),
					params: params,
					files: chatFiles
				});
				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage, true));
			}
		}
	};
</script>

<svelte:head>
	<title>
		{$chatTitle
			? `${$chatTitle.length > 30 ? `${$chatTitle.slice(0, 30)}...` : $chatTitle} | ${$WEBUI_NAME}`
			: `${$WEBUI_NAME}`}
	</title>
</svelte:head>

<audio id="audioElement" src="" style="display: none;" />

<EventConfirmDialog
	bind:show={showEventConfirmation}
	title={eventConfirmationTitle}
	message={eventConfirmationMessage}
	input={eventConfirmationInput}
	inputPlaceholder={eventConfirmationInputPlaceholder}
	inputValue={eventConfirmationInputValue}
	on:confirm={(e) => {
		if (e.detail) {
			eventCallback(e.detail);
		} else {
			eventCallback(true);
		}
	}}
	on:cancel={() => {
		eventCallback(false);
	}}
/>

<div
	class="h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
		? '  md:max-w-[calc(100%-260px)]'
		: ' '} w-full max-w-full flex flex-col"
	id="chat-container"
>
	{#if !loading}
		{#if $settings?.backgroundImageUrl ?? null}
			<div
				class="absolute {$showSidebar
					? 'md:max-w-[calc(100%-260px)] md:translate-x-[260px]'
					: ''} top-0 left-0 w-full h-full bg-cover bg-center bg-no-repeat"
				style="background-image: url({$settings.backgroundImageUrl})  "
			/>

			<div
				class="absolute top-0 left-0 w-full h-full bg-linear-to-t from-white to-white/85 dark:from-gray-900 dark:to-gray-900/90 z-0"
			/>
		{/if}

		<PaneGroup direction="horizontal" class="w-full h-full">
			<Pane defaultSize={50} class="h-full flex relative max-w-full flex-col">
				<Navbar
					bind:this={navbarElement}
					chat={{
						id: $chatId,
						chat: {
							title: $chatTitle,
							models: selectedModels,
							system: $settings.system ?? undefined,
							params: params,
							history: history,
							timestamp: Date.now()
						}
					}}
					{history}
					title={$chatTitle}
					bind:selectedModels
					shareEnabled={!!history.currentId}
					{initNewChat}
					projectId={params?._projectId}
				/>

				<div class="flex flex-col flex-auto z-10 w-full @container">
					{#if createMessagesList(history, history.currentId).length > 0}
						<div
							class=" pb-2.5 flex flex-col justify-between w-full flex-auto overflow-auto h-0 max-w-full z-10 scrollbar-hidden"
							id="messages-container"
							bind:this={messagesContainerElement}
							on:scroll={(e) => {
								autoScroll =
									messagesContainerElement.scrollHeight - messagesContainerElement.scrollTop <=
									messagesContainerElement.clientHeight + 5;
							}}
						>
							<div class=" h-full w-full flex flex-col">
								<Messages
									chatId={$chatId}
									bind:history
									bind:autoScroll
									bind:prompt
									{selectedModels}
									{atSelectedModel}
									{sendPrompt}
									{showMessage}
									{submitMessage}
									{continueResponse}
									{regenerateResponse}
									{mergeResponses}
									{chatActionHandler}
									{addMessages}
									{handleHITLDecision}
									bottomPadding={files.length > 0}
								/>
							</div>
						</div>

						<div class=" pb-[1rem]">
							{#if isScheduleReadOnly}
								<div
									class="flex items-center justify-center gap-2 px-4 py-3 text-xs text-gray-500 dark:text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-2xl"
								>
									{$i18n.t(
										'This chat is a scheduled task log shared with read-only access. Messaging is disabled.'
									)}
								</div>
							{:else}
								<MessageInput
									{history}
									{taskIds}
									{selectedModels}
									{modelCapabilities}
									bind:files
									bind:prompt
									bind:autoScroll
									bind:selectedToolIds
									bind:imageGenerationEnabled
									bind:selectedImageConnectionIdx
									{imageConnections}
									bind:webSearchEnabled
									bind:gmailEnabled
									bind:calendarEnabled
									bind:driveEnabled
									{googleScopes}
									bind:atSelectedModel
									toolServers={$toolServers}
									transparentBackground={$settings?.backgroundImageUrl ?? false}
									{stopResponse}
									{createMessagePair}
								onChange={(input) => {
									if (input.prompt) {
										localStorage.setItem(`chat-input-${$chatId}`, JSON.stringify(input));
									} else {
										localStorage.removeItem(`chat-input-${$chatId}`);
									}
								}}
								on:upload={async (e) => {
									const { type, data } = e.detail;

									if (type === 'web') {
										await uploadWeb(data);
									} else if (type === 'youtube') {
										await uploadYoutubeTranscription(data);
									} else if (type === 'google-drive') {
										await uploadGoogleDriveFile(data);
									}
								}}
								on:submit={async (e) => {
									if (e.detail || files.length > 0) {
										await tick();
										submitPrompt(
											($settings?.richTextInput ?? true)
												? e.detail.replaceAll('\n\n', '\n')
												: e.detail
										);
									}
								}}
							/>
							{/if}

							<div
								class="absolute bottom-1 text-xs text-gray-500 text-center line-clamp-1 right-0 left-0"
							>
								<!-- {$i18n.t('LLMs can make mistakes. Verify important information.')} -->
							</div>
						</div>
					{:else}
						<div class="overflow-auto w-full h-full flex items-center">
							<Placeholder
								{history}
								{selectedModels}
								{modelCapabilities}
								bind:files
								bind:prompt
								bind:autoScroll
								bind:selectedToolIds
								bind:imageGenerationEnabled
								bind:selectedImageConnectionIdx
								{imageConnections}
								bind:webSearchEnabled
								bind:gmailEnabled
								bind:calendarEnabled
								bind:driveEnabled
								{googleScopes}
								bind:atSelectedModel
								transparentBackground={$settings?.backgroundImageUrl ?? false}
								toolServers={$toolServers}
								{stopResponse}
								{createMessagePair}
								on:upload={async (e) => {
									const { type, data } = e.detail;

									if (type === 'web') {
										await uploadWeb(data);
									} else if (type === 'youtube') {
										await uploadYoutubeTranscription(data);
									}
								}}
								on:submit={async (e) => {
									if (e.detail || files.length > 0) {
										await tick();
										submitPrompt(
											($settings?.richTextInput ?? true)
												? e.detail.replaceAll('\n\n', '\n')
												: e.detail
										);
									}
								}}
							/>
						</div>
					{/if}
				</div>
			</Pane>

			<ChatControls
				bind:this={controlPaneComponent}
				bind:history
				bind:chatFiles
				bind:params
				bind:files
				bind:pane={controlPane}
				chatId={$chatId}
				modelId={selectedModelIds?.at(0) ?? null}
				models={selectedModelIds.reduce((a, e, i, arr) => {
					const model = $models.find((m) => m.id === e);
					if (model) {
						return [...a, model];
					}
					return a;
				}, [])}
				{submitPrompt}
				{stopResponse}
				{showMessage}
				{eventTarget}
			/>
		</PaneGroup>
	{:else if loading}
		<div class=" flex items-center justify-center h-full w-full">
			<div class="m-auto">
				<Spinner />
			</div>
		</div>
	{/if}
</div>
