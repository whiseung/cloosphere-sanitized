<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import { io, type Socket } from 'socket.io-client';
	import { onMount, onDestroy, tick, getContext, setContext } from 'svelte';
	import { writable, type Writable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { createMessagesList, convertMessagesToHistory } from '$lib/utils';
	import { chatCompletion, generateOpenAIChatCompletion } from '$lib/apis/openai';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import { createNewChat, updateChatById, resumeChatHITL } from '$lib/apis/chats';
	import { uploadFile } from '$lib/apis/files';
	import { getSessionUser } from '$lib/apis/auths';

	import Messages from '$lib/components/chat/Messages.svelte';
	import EmbedMessageInput from './EmbedMessageInput.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import type { EmbedWidgetConfig } from '$lib/apis/embed-widgets';

	const i18n = getContext('i18n');

	export let widgetConfig: EmbedWidgetConfig;
	export let token: string;
	export let baseUrl: string = '';
	export let headerColor: string = '';
	export let headerTextColor: string = '';
	export let messageTextColor: string = '';
	export let backgroundColor: string = '';
	export let sendButtonColor: string = '';
	export let sendButtonIconColor: string = '';
	export let sendButtonIconUrl: string = '';
	export let showHeader: boolean = true;
	export let showHeaderCloseButton: boolean = true;
	export let headerText: string = '';
	export let showAvatar: boolean = true;
	export let avatarUrl: string = '';
	export let botName: string = '';
	export let fileUploadOverride: boolean | null = null;

	let loaded = false;
	let processing = '';
	let autoScroll = true;
	let chatId = '';
	let prompt = '';

	// `/` 커맨드로 활성 에이전트 변경을 허용. 초기값은 위젯의 기본 model_id.
	let activeModelId = widgetConfig.model_id;
	$: allowedAgents = widgetConfig.agents || [];

	let embUser: { id: string; name: string; role: string; profile_image_url: string } | null = null;
	let embSocket: Socket | null = null;

	// Create isolated stores for embed context
	const embSocketStore: Writable<Socket | null> = writable(null);
	const embUserStore: Writable<typeof embUser> = writable(null);

	let history: {
		messages: Record<string, any>;
		currentId: string | null;
	} = {
		messages: {},
		currentId: null
	};

	let messages: any[] = [];
	$: messages = createMessagesList(history, history.currentId);

	// Smooth typing animation: server sends cumulative content in chunky updates.
	// We reveal chars gradually to remove the stutter.
	const typingTargets: Record<string, string> = {};
	const typingTimers: Record<string, number> = {};
	const TYPE_STEP_MS = 12;
	const TYPE_CHARS_PER_TICK = 2;

	const scheduleTyping = (msgId: string) => {
		if (typingTimers[msgId]) return;
		const tick = () => {
			const target = typingTargets[msgId] ?? '';
			const msg = history.messages[msgId];
			if (!msg) {
				delete typingTimers[msgId];
				return;
			}
			const current = msg.content || '';
			if (current.length >= target.length) {
				delete typingTimers[msgId];
				return;
			}
			const next = target.slice(0, current.length + TYPE_CHARS_PER_TICK);
			msg.content = next;
			history.messages[msgId] = { ...msg };
			history = history;
			typingTimers[msgId] = window.setTimeout(tick, TYPE_STEP_MS);
		};
		typingTimers[msgId] = window.setTimeout(tick, TYPE_STEP_MS);
	};

	const setTargetContent = (msgId: string, fullContent: string) => {
		typingTargets[msgId] = fullContent;
		scheduleTyping(msgId);
	};

	const flushTyping = (msgId: string) => {
		const target = typingTargets[msgId];
		if (target !== undefined && history.messages[msgId]) {
			history.messages[msgId].content = target;
			history.messages[msgId] = { ...history.messages[msgId] };
			history = history;
		}
		if (typingTimers[msgId]) {
			window.clearTimeout(typingTimers[msgId]);
			delete typingTimers[msgId];
		}
		delete typingTargets[msgId];
	};

	// Widget config helpers
	$: config = (widgetConfig.config || {}) as Record<string, any>;
	$: features = (config.features || {}) as Record<string, boolean>;
	$: welcomeMessage = (config.welcome_message as string) || '';
	$: maxMessages = (config.max_messages_per_session as number) || 0;
	$: userMessageCount = messages.filter((m) => m.role === 'user').length;
	$: inputDisabled = !!processing || (maxMessages > 0 && userMessageCount >= maxMessages);

	const initSocket = () => {
		const url = baseUrl || WEBUI_BASE_URL;
		embSocket = io(url, {
			path: '/ws/socket.io',
			auth: { token },
			reconnection: true,
			transports: ['websocket']
		});

		embSocket.on('connect', () => {
			console.log('[embed] socket connected, sid=', embSocket?.id);
		});

		embSocket.on('connect_error', (err) => {
			console.error('[embed] socket connect_error:', err);
		});

		embSocket.on('chat-events', chatEventHandler);
		embSocketStore.set(embSocket);
	};

	const chatEventHandler = async (event: any) => {
		if (!chatId || event.chat_id !== chatId) return;

		const type = event?.data?.type ?? null;
		const data = event?.data?.data ?? null;

		// UI command events don't require an existing message
		if (type === 'ui:command') {
			const requestId = data?.request_id || crypto.randomUUID();
			try {
				window.parent.postMessage(
					{
						type: 'cloosphere:ui-command',
						request_id: requestId,
						command: data?.command,
						args: data?.args || {}
					},
					'*'
				);
			} catch (err) {
				console.error('[embed] Failed to forward ui:command', err);
			}
			return;
		}

		await tick();
		const message = history.messages[event.message_id];
		if (!message) return;

		if (type === 'status') {
			if (message?.statusHistory) {
				message.statusHistory.push(data);
			} else {
				message.statusHistory = [data];
			}
		} else if (type === 'chat:completion') {
			// backend 는 누적 content 를 이벤트마다 replace 로 보낸다 — 타이핑 애니메이션으로 부드럽게
			if (data.content) {
				setTargetContent(event.message_id, data.content);
			}
			if (data.choices) {
				const delta = data.choices[0]?.delta?.content ?? data.choices[0]?.message?.content;
				if (delta) {
					const cur = typingTargets[event.message_id] ?? message.content ?? '';
					setTargetContent(event.message_id, cur + delta);
				}
			}
			if (data.sources && !data.done) {
				message.sources = data.sources;
			}
			if (data.error) {
				message.error = { content: data.error?.message || String(data.error) };
			}
			if (data.done) {
				flushTyping(event.message_id);
				processing = '';
				history.messages[event.message_id].done = true;
				if (data.sources) history.messages[event.message_id].sources = data.sources;
				if (data.usage) history.messages[event.message_id].usage = data.usage;
				history = history;
				await saveChatHistory();
			}
		} else if (type === 'chat:message:delta' || type === 'message') {
			message.content += data.content;
			history.messages[event.message_id] = { ...message };
		} else if (type === 'chat:message' || type === 'replace') {
			message.content = data.content;
			history.messages[event.message_id] = { ...message };
		} else if (type === 'source' || type === 'citation') {
			if (data?.type === 'code_execution') {
				if (!message.code_executions) message.code_executions = [];
				const idx = message.code_executions.findIndex((e: any) => e.id === data.id);
				if (idx !== -1) {
					message.code_executions[idx] = data;
				} else {
					message.code_executions.push(data);
				}
				message.code_executions = message.code_executions;
			} else {
				if (message?.sources) {
					message.sources.push(data);
				} else {
					message.sources = [data];
				}
			}
		} else if (type === 'notification') {
			const toastType = data?.type ?? 'info';
			const toastContent = data?.content ?? '';
			if (toastType === 'error') toast.error(toastContent);
			else if (toastType === 'success') toast.success(toastContent);
			else toast.info(toastContent);
		} else if (type === 'hitl_request') {
			// HITL: 에이전트가 도구 실행/되묻기 직전 멈춤. interrupts 안의
			// action_requests 를 메시지에 박아 ResponseMessage 가 카드로 렌더한다
			// (메인 챗 Chat.svelte 와 동일 구조 — AskUserCard/AskUserFormCard 공유).
			const interrupts = data?.interrupts ?? [];
			const actionRequests: any[] = [];
			for (const interrupt of interrupts) {
				for (const req of interrupt?.action_requests ?? []) {
					actionRequests.push(req);
				}
			}
			message.hitl_pending = {
				thread_id: data?.thread_id,
				message_id: event.message_id,
				actions: actionRequests,
				decisions: actionRequests.map(() => null),
				chain_run_id: data?.chain_run_id ?? null,
				trace_id: data?.trace_id ?? null
			};
			message.done = true;
			processing = '';
			history.messages[event.message_id] = { ...message };
		}

		history = history;
		messages = createMessagesList(history, history.currentId);
	};

	// HITL 카드의 결정 수집 → 모두 모이면 resume 호출 (메인 챗과 동일 흐름).
	const handleHITLDecision = async (messageId: string, actionIndex: number, decision: any) => {
		const message = history.messages[messageId];
		if (!message?.hitl_pending) return;

		message.hitl_pending.decisions[actionIndex] = decision;
		history.messages[messageId] = message;

		// 모든 결정이 모일 때까지 대기 (다중 action_request 케이스)
		const stillPending = message.hitl_pending.decisions.findIndex((d: any) => d === null);
		if (stillPending !== -1) {
			history = history;
			return;
		}

		const decisions = message.hitl_pending.decisions;
		const threadId = message.hitl_pending.thread_id;

		const resumeMessages = createMessagesList(history, message.parentId)
			.map((m) => ({ role: m.role, content: m.content }))
			.filter((m) => m.content);

		const payload = {
			stream: true,
			model: activeModelId,
			messages: resumeMessages,
			features: { web_search: features.web_search ?? false },
			chat_id: chatId,
			id: messageId,
			session_id: embSocket?.id ?? null,
			client_type: 'widget'
		};

		// 카드 잠금 — 결정은 이미 박혀있어 답변 요약으로 표시된다.
		message.hitl_pending = { ...message.hitl_pending, locked: true };
		message.done = false;
		history.messages[messageId] = message;
		history = history;

		try {
			const res = await resumeChatHITL(token, chatId, {
				thread_id: threadId,
				decisions,
				payload,
				chain_run_id: message.hitl_pending?.chain_run_id ?? null,
				trace_id: message.hitl_pending?.trace_id ?? null
			});

			// resume 는 SSE body 로 스트림 (worker queue 우회 — 메인 챗과 동일).
			if (res.body) {
				const stream = await createOpenAITextStream(res.body, true);
				for await (const update of stream) {
					const { value, done, error } = update;
					if (error) throw error;
					if (done) break;
					if (value) {
						history.messages[messageId].content =
							(history.messages[messageId].content || '') + value;
						history = history;
					}
				}
			}
			history.messages[messageId].done = true;
			history = history;
			await saveChatHistory();
		} catch (e: any) {
			toast.error(String(e?.detail ?? e));
			history.messages[messageId].done = true;
			history = history;
		}
		messages = createMessagesList(history, history.currentId);
	};

	const initChat = async (): Promise<string> => {
		const _messages = createMessagesList(history, history.currentId);
		const chat = await createNewChat(
			token,
			{
				title: `Embed: ${widgetConfig.name}`,
				models: [activeModelId],
				history: history,
				messages: _messages,
				tags: [],
				timestamp: Date.now()
			},
			{
				embed_widget_id: widgetConfig.id,
				embed_widget_name: widgetConfig.name
			}
		);
		chatId = chat.id;
		return chat.id;
	};

	const saveChatHistory = async () => {
		if (!chatId) return;
		const _messages = createMessagesList(history, history.currentId);
		await updateChatById(token, chatId, {
			models: [activeModelId],
			history: history,
			messages: _messages,
			tags: [],
			timestamp: Date.now()
		}).catch((err) => console.error('Failed to save chat:', err));
	};

	const submitMessage = async (e: CustomEvent<{ prompt: string; files: File[] }>) => {
		const { prompt: userPrompt, files: uploadedFiles } = e.detail;
		if (!userPrompt.trim() && uploadedFiles.length === 0) return;

		processing = 'sending';

		// Upload files if any
		let fileItems: any[] = [];
		if (uploadedFiles.length > 0 && features.file_upload) {
			for (const file of uploadedFiles) {
				try {
					const uploaded = await uploadFile(token, file);
					if (uploaded) {
						fileItems.push({
							type: 'file',
							id: uploaded.id,
							name: uploaded.meta?.name || file.name,
							collection_name: uploaded.id
						});
					}
				} catch (err) {
					toast.error(`Failed to upload ${file.name}`);
				}
			}
		}

		// Create user message
		const userMessageId = uuidv4();
		const parentId = history.currentId;

		history.messages[userMessageId] = {
			id: userMessageId,
			parentId,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			files: fileItems.length > 0 ? fileItems : undefined,
			timestamp: Math.floor(Date.now() / 1000)
		};

		if (parentId !== null && history.messages[parentId]) {
			history.messages[parentId].childrenIds = [
				...history.messages[parentId].childrenIds,
				userMessageId
			];
		}

		history.currentId = userMessageId;

		// Create response message placeholder
		const responseMessageId = uuidv4();
		history.messages[responseMessageId] = {
			id: responseMessageId,
			parentId: userMessageId,
			childrenIds: [],
			role: 'assistant',
			content: '',
			model: activeModelId,
			timestamp: Math.floor(Date.now() / 1000)
		};

		history.messages[userMessageId].childrenIds = [responseMessageId];
		history.currentId = responseMessageId;
		history = history;

		await tick();

		// Create chat on first message
		if (!chatId) {
			try {
				await initChat();
			} catch (err) {
				toast.error('Failed to create chat session');
				processing = '';
				return;
			}
		}

		// Build messages for API
		const systemPrompt = widgetConfig.config
			? undefined  // system_prompt is handled by backend via model config
			: undefined;

		const apiMessages = createMessagesList(history, responseMessageId)
			.map((m) => ({
				role: m.role,
				content: m.content,
				...(m.files?.length > 0
					? {
							content: [
								{ type: 'text', text: m.content },
								...m.files
									.filter((f: any) => f.type === 'image')
									.map((f: any) => ({
										type: 'image_url',
										image_url: { url: f.url }
									}))
							]
						}
					: {})
			}))
			.filter((m) => m.content);

		// session_id 가 있으면 backend 는 {status, task_id} 만 반환하고 실제 토큰은
		// Socket.IO 'chat-events' 로 흐른다 (chatEventHandler 에서 처리).
		// session_id 가 없으면 SSE body 로 직접 스트림 → 아래 루프가 소비한다.
		try {
			const [res] = await chatCompletion(
				token,
				{
					stream: true,
					model: activeModelId,
					messages: apiMessages,
					stream_options: { include_usage: true },
					session_id: embSocket?.id,
					chat_id: chatId,
					id: responseMessageId,
					client_type: 'widget',
					files: fileItems.length > 0 ? fileItems : undefined,
					features: {
						web_search: features.web_search ?? false
					},
					background_tasks: {
						title_generation: false,
						tags_generation: false
					}
				},
				`${baseUrl || WEBUI_BASE_URL}/api`
			);

			if (!res || !res.ok || !res.body) {
				const errText = res ? await res.text().catch(() => res.statusText) : 'no response';
				throw new Error(errText || 'chat completion failed');
			}

			const ct = res.headers?.get('content-type') || '';
			if (ct.includes('text/event-stream')) {
				const textStream = await createOpenAITextStream(res.body, true);
				for await (const update of textStream) {
					const { value, done, sources, error, usage } = update;
					if (error) {
						history.messages[responseMessageId].error = { content: String(error?.message ?? error) };
						break;
					}
					if (done) break;
					if (sources) history.messages[responseMessageId].sources = sources;
					if (usage) history.messages[responseMessageId].usage = usage;
					if (value) {
						history.messages[responseMessageId].content =
							(history.messages[responseMessageId].content || '') + value;
						history = history;
					}
				}
				history.messages[responseMessageId].done = true;
				processing = '';
				history = history;
				await saveChatHistory();
			}
			// worker queue path: chatEventHandler 가 done 처리까지 수행
		} catch (err) {
			history.messages[responseMessageId].content = '';
			history.messages[responseMessageId].error = { content: String(err) };
			history.messages[responseMessageId].done = true;
			processing = '';
			history = history;
			toast.error(String(err));
		}
	};

	// Override bot icon and name in rendered messages
	$: if (loaded && (avatarUrl || botName)) {
		tick().then(() => {
			const container = document.querySelector('.embed-messages');
			if (!container) return;

			if (avatarUrl) {
				container.querySelectorAll('.shrink-0.ltr\\:mr-3 img, .shrink-0.rtl\\:ml-3 img').forEach((img) => {
					if ((img as HTMLImageElement).src !== avatarUrl) {
						(img as HTMLImageElement).src = avatarUrl;
					}
				});
			}

			if (botName) {
				container.querySelectorAll('.line-clamp-1.text-black').forEach((el) => {
					if (el.textContent !== botName) {
						el.textContent = botName;
					}
				});
			}
		});
	}

	// Receive UI command results from parent window (embed.js)
	// and forward back to the backend via Socket.IO
	const handleParentMessage = (event: MessageEvent) => {
		const data = event.data;
		if (!data || typeof data !== 'object') return;
		if (data.type !== 'cloosphere:ui-result') return;
		if (embSocket && embSocket.connected) {
			embSocket.emit('ui:response', {
				request_id: data.request_id,
				result: data.result
			});
		} else {
			console.warn('[embed] socket not connected, ui:response dropped');
		}
	};

	onMount(async () => {
		try {
			embUser = await getSessionUser(token);
			embUserStore.set(embUser);
		} catch {
			toast.error('Authentication failed');
			return;
		}

		initSocket();
		window.addEventListener('message', handleParentMessage);

		// Add welcome message if configured
		if (welcomeMessage) {
			const welcomeId = uuidv4();
			history.messages[welcomeId] = {
				id: welcomeId,
				parentId: null,
				childrenIds: [],
				role: 'assistant',
				content: welcomeMessage,
				model: activeModelId,
				timestamp: Math.floor(Date.now() / 1000),
				done: true
			};
			history.currentId = welcomeId;
			history = history;
		}

		loaded = true;
	});

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('message', handleParentMessage);
		}
		if (embSocket) {
			embSocket.off('chat-events', chatEventHandler);
			embSocket.disconnect();
		}
	});
</script>

<div
	class="flex flex-col h-full embed-chat-root"
	style={[
		backgroundColor && `background-color: ${backgroundColor};`,
		messageTextColor && `--embed-message-text: ${messageTextColor};`,
		sendButtonColor && `--embed-send-color: ${sendButtonColor};`,
		sendButtonIconColor && `--embed-send-icon-color: ${sendButtonIconColor};`
	].filter(Boolean).join(' ')}
	class:has-bg={!!backgroundColor}
	class:bg-[var(--cloo-bg-default)]={!backgroundColor}
>
	{#if !loaded}
		<div class="flex-1 flex items-center justify-center">
			<Spinner />
		</div>
	{:else}
		<!-- Header -->
		{#if showHeader}
			<div
				class="px-4 py-3 border-b border-[var(--cloo-border-default)] flex items-center justify-between gap-2"
				style={[
					headerColor && `background-color: ${headerColor};`,
					headerTextColor ? `color: ${headerTextColor};` : (headerColor ? 'color: #fff;' : '')
				].filter(Boolean).join(' ')}
				class:bg-[var(--cloo-bg-surface)]={!headerColor}
			>
				<div class="font-medium text-sm truncate" class:text-[var(--cloo-text-default)]={!headerColor && !headerTextColor}>
					{headerText || widgetConfig.name}
				</div>
				{#if showHeaderCloseButton}
					<button
						type="button"
						class="shrink-0 p-1 -m-1 rounded hover:bg-black/10 dark:hover:bg-white/10 transition-colors"
						aria-label={$i18n.t('Close')}
						on:click={() => {
							try {
								window.parent.postMessage({ type: 'close-widget' }, '*');
							} catch (e) {
								// noop
							}
						}}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
							<path fill-rule="evenodd" d="M5.47 5.47a.75.75 0 0 1 1.06 0L12 10.94l5.47-5.47a.75.75 0 1 1 1.06 1.06L13.06 12l5.47 5.47a.75.75 0 1 1-1.06 1.06L12 13.06l-5.47 5.47a.75.75 0 0 1-1.06-1.06L10.94 12 5.47 6.53a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd"/>
						</svg>
					</button>
				{/if}
			</div>
		{/if}

		<!-- Messages -->
		<div
			class="flex-1 overflow-y-auto embed-messages"
			class:hide-bot-icon={!showAvatar}
			class:has-custom-icon={!!avatarUrl}
			class:has-bot-name={!!botName}
			style={avatarUrl ? `--embed-bot-icon: url(${avatarUrl});` : ''}
			data-bot-name={botName}
		>
			{#if messages.length === 0}
				<div class="flex items-center justify-center h-full text-[var(--cloo-text-muted)] text-sm">
					{$i18n.t('Start a conversation')}
				</div>
			{:else}
				<Messages
					className="h-full flex pt-2 pb-4"
					user={embUser}
					{chatId}
					{prompt}
					readOnly={false}
					selectedModels={[activeModelId]}
					{processing}
					bind:history
					bind:messages
					bind:autoScroll
					sendPrompt={() => {}}
					continueResponse={() => {}}
					regenerateResponse={() => {}}
					mergeResponses={() => {}}
					chatActionHandler={() => {}}
					{handleHITLDecision}
				/>
			{/if}
		</div>

		<!-- Max messages notice -->
		{#if maxMessages > 0 && userMessageCount >= maxMessages}
			<div class="px-4 py-2 text-xs text-center text-[var(--cloo-text-muted)] bg-[var(--cloo-bg-surface)] border-t border-[var(--cloo-border-default)]">
				{$i18n.t('Maximum messages reached for this session.')}
			</div>
		{/if}

		<!-- Input -->
		<EmbedMessageInput
			bind:prompt
			bind:activeAgentId={activeModelId}
			agents={allowedAgents}
			disabled={inputDisabled}
			fileUploadEnabled={fileUploadOverride !== null ? fileUploadOverride : (features.file_upload ?? false)}
			{sendButtonColor}
			{sendButtonIconColor}
			{sendButtonIconUrl}
			on:submit={submitMessage}
		/>
	{/if}
</div>

<style>
	/* Hide bot profile icon when disabled */
	.hide-bot-icon :global(.shrink-0.ltr\:mr-3),
	.hide-bot-icon :global(.shrink-0.rtl\:ml-3) {
		display: none !important;
	}

	/* User message: transparent background (follows main bg) */
	.embed-chat-root :global(.bg-gray-50.dark\:bg-gray-850.rounded-3xl) {
		background-color: transparent !important;
	}

	/* Unified message text color (user + assistant) */
	.embed-chat-root[style*="--embed-message-text"] :global(.bg-gray-50.dark\:bg-gray-850.rounded-3xl),
	.embed-chat-root[style*="--embed-message-text"] :global(.chat-assistant.markdown-prose),
	.embed-chat-root[style*="--embed-message-text"] :global(.markdown-prose *) {
		color: var(--embed-message-text) !important;
	}

	/* Send button: separate background and icon colors */
	.embed-chat-root :global(button.send-button.is-active) {
		background-color: var(--embed-send-color, #171717) !important;
		color: var(--embed-send-icon-color, #ffffff) !important;
	}
</style>

