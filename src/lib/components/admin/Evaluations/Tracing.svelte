<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { onMount, getContext, tick } from 'svelte';

	const i18n = getContext('i18n');

	// URL에서 전달받은 초기 chat_id
	export let initialChatId = '';
	export let initialMessageId = '';

	import {
		getTraces,
		getTraceById,
		type TraceRun,
		type TraceTree
	} from '$lib/apis/traces';
	import {
		createTraceAnalysis,
		getTraceAnalysis,
		getAnalysesByTrace,
		type TraceAnalysisResponse
	} from '$lib/apis/trace-analysis';

	import { models } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import RunTreeItem from './RunTreeItem.svelte';
	import JsonTreeView from '$lib/components/common/JsonTreeView.svelte';
	import TraceAnalysisReport from './TraceAnalysisReport.svelte';

	let loaded = false;
	let traces: TraceRun[] = [];
	let total = 0;
	let page = 1;
	let limit = 20;
	let totalPages = 1;

	// Search
	let searchQuery = '';
	let searchType: 'chat_id' | 'message_id' | 'trace_id' = 'chat_id';

	// Filters
	let statusFilter = '';
	let runTypeFilter = '';

	// Date range
	let dateRange = '7d';
	let fromDate: number | null = null;
	let toDate: number | null = null;

	// Detail modal
	let showDetail = false;
	let selectedTrace: TraceTree | null = null;
	let selectedRun: TraceRun | null = null;
	let loadingTrace = false;

	// trace_id로 그룹화된 트레이스 인터페이스
	interface TraceGroup {
		traceId: string;
		messageId: string | null;
		userMessage: string;
		traces: TraceRun[];
		totalLatency: number;
		hasError: boolean;
		latestTime: number;
	}

	// 선택된 그룹
	let selectedGroup: TraceGroup | null = null;

	// Trace Analysis
	let showAnalysisForm = false;
	let showAnalysisReport = false;
	let analysisLoading = false;
	let analysisResult: TraceAnalysisResponse | null = null;
	let analysisModelId = '';
	let userDescription = '';
	let existingAnalyses: TraceAnalysisResponse[] = [];
	let pollingInterval: ReturnType<typeof setInterval> | null = null;

	// View mode for inputs/outputs
	type ViewMode = 'json' | 'tree' | 'text';
	let inputsViewMode: ViewMode = 'tree';
	let outputsViewMode: ViewMode = 'tree';

	// 출력 검색
	let outputSearchQuery = '';
	let currentMatchIndex = 0;
	let totalMatches = 0;
	let outputContentEl: HTMLElement;

	// 매치 개수 계산
	const countMatches = (text: string, query: string): number => {
		if (!query.trim()) return 0;
		const regex = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
		const matches = text.match(regex);
		return matches ? matches.length : 0;
	};

	// 다음 매치로 이동
	const goToNextMatch = async () => {
		if (totalMatches === 0) return;
		currentMatchIndex = (currentMatchIndex + 1) % totalMatches;
		await tick();
		scrollToMatch(currentMatchIndex);
	};

	// 이전 매치로 이동
	const goToPrevMatch = async () => {
		if (totalMatches === 0) return;
		currentMatchIndex = (currentMatchIndex - 1 + totalMatches) % totalMatches;
		await tick();
		scrollToMatch(currentMatchIndex);
	};

	// 특정 매치로 스크롤
	const scrollToMatch = (index: number) => {
		if (!outputContentEl) return;
		const marks = outputContentEl.querySelectorAll('mark');
		if (marks.length === 0) return;

		// 모든 mark에서 current 클래스 제거
		marks.forEach(m => m.classList.remove('ring-2', 'ring-blue-500'));

		// 현재 매치에 current 클래스 추가 및 스크롤
		const currentMark = marks[index];
		if (currentMark) {
			currentMark.classList.add('ring-2', 'ring-blue-500');
			currentMark.scrollIntoView({ behavior: 'smooth', block: 'center' });
		}
	};

	// 검색어 변경 시 매치 개수 업데이트
	$: if (selectedRun && outputSearchQuery) {
		const content = outputsViewMode === 'json'
			? JSON.stringify(selectedRun.outputs, null, 2)
			: renderText(selectedRun.outputs);
		totalMatches = countMatches(content, outputSearchQuery);
		currentMatchIndex = 0;
	} else {
		totalMatches = 0;
		currentMatchIndex = 0;
	}

	const handleSearchKeydown = (event: CustomEvent<KeyboardEvent>) => {
		if (event.detail?.key === 'Enter') handleSearch();
	};

	$: searchTypeOptions = [
		{ value: 'chat_id', label: $i18n.t('Chat ID') },
		{ value: 'message_id', label: $i18n.t('Message ID') }
	];

	$: analysisModelOptions = [
		{ value: '', label: $i18n.t('Select Model') },
		...$models
			.filter((m: any) => !m.base_model_id && !m.preset && !(m.arena ?? false))
			.map((m: any) => ({ value: m.id, label: m.name }))
	];

	$: viewModeOptions = [
		{ id: 'tree' as ViewMode, label: $i18n.t('Tree') },
		{ id: 'json' as ViewMode, label: $i18n.t('JSON') },
		{ id: 'text' as ViewMode, label: $i18n.t('Text') }
	];

	$: runTypeOptions = [
		{ id: 'chain', name: $i18n.t('Chain'), color: 'bg-purple-500' },
		{ id: 'llm', name: $i18n.t('LLM'), color: 'bg-blue-500' },
		{ id: 'tool', name: $i18n.t('Tool'), color: 'bg-green-500' },
		{ id: 'retrieval', name: $i18n.t('Retrieval'), color: 'bg-orange-500' },
		{ id: 'web_search', name: $i18n.t('Web Search'), color: 'bg-cyan-500' },
		{ id: 'guardrail', name: $i18n.t('Guardrail'), color: 'bg-red-500' },
		{ id: 'embedding', name: $i18n.t('Embedding'), color: 'bg-yellow-500' }
	];

	$: statusOptions = [
		{ id: 'success', name: $i18n.t('Success') },
		{ id: 'error', name: $i18n.t('Error') },
		{ id: 'running', name: $i18n.t('Running') },
		{ id: 'pending', name: $i18n.t('Pending') }
	];

	const setDateRange = (range: string) => {
		dateRange = range;
		const now = Date.now();
		toDate = now;

		switch (range) {
			case '1d':
				fromDate = now - 86400 * 1000;
				break;
			case '7d':
				fromDate = now - 86400 * 7 * 1000;
				break;
			case '30d':
				fromDate = now - 86400 * 30 * 1000;
				break;
			case 'all':
				fromDate = null;
				toDate = null;
				break;
			default:
				fromDate = now - 86400 * 7 * 1000;
		}
	};

	let hasSearched = false;

	const loadTraces = async () => {
		// 검색어가 없으면 로드하지 않음
		if (!searchQuery.trim()) {
			traces = [];
			total = 0;
			totalPages = 1;
			hasSearched = false;
			return;
		}

		hasSearched = true;

		try {
			const params: Record<string, any> = {
				page,
				limit
			};

			if (statusFilter) params.status = statusFilter;
			if (runTypeFilter) params.run_type = runTypeFilter;

			// Search by specific field
			if (searchType === 'chat_id') {
				params.chat_id = searchQuery.trim();
			} else if (searchType === 'message_id') {
				params.message_id = searchQuery.trim();
			}

			// 특정 ID 검색이 아닌 경우에만 날짜 필터 적용
			if (!params.chat_id && !params.message_id) {
				if (fromDate) params.from_date = fromDate;
				if (toDate) params.to_date = toDate;
			}

			const result = await getTraces(localStorage.token, params);
			traces = result.traces;
			total = result.total;
			totalPages = result.total_pages;
		} catch (err) {
			toast.error($i18n.t('Failed to load traces'));
		}
	};

	// 그룹의 트레이스 상세 로드 (단일 trace_id)
	const openGroupTraces = async (group: TraceGroup) => {
		loadingTrace = true;
		selectedGroup = group;

		try {
			const trace = await getTraceById(localStorage.token, group.traceId);

			if (trace) {
				selectedTrace = trace;
			} else {
				selectedTrace = {
					trace_id: group.traceId,
					chat_id: group.traces[0]?.chat_id || null,
					message_id: group.messageId,
					user_id: group.traces[0]?.user_id || '',
					total_latency_ms: group.totalLatency,
					total_tokens: 0,
					status: group.hasError ? 'error' : 'success',
					runs: []
				};
			}

			selectedRun = null;
			inputsViewMode = 'tree';
			outputSearchQuery = '';
			totalMatches = 0;
			currentMatchIndex = 0;
			outputsViewMode = 'tree';
			showDetail = true;

			// 기존 분석 결과 로드
			loadExistingAnalyses(group.traceId);
		} catch (err) {
			toast.error($i18n.t('Failed to load trace details'));
		} finally {
			loadingTrace = false;
		}
	};

	// ── Trace Analysis Functions ──

	const loadExistingAnalyses = async (traceId: string) => {
		try {
			existingAnalyses = await getAnalysesByTrace(localStorage.token, traceId);
		} catch {
			existingAnalyses = [];
		}
	};

	const startAnalysis = async () => {
		if (!selectedTrace || !analysisModelId) return;

		analysisLoading = true;
		try {
			const result = await createTraceAnalysis(localStorage.token, {
				trace_id: selectedTrace.trace_id,
				model_id: analysisModelId,
				user_description: userDescription
			});
			analysisResult = result;
			showAnalysisForm = false;
			startPolling(result.id);
		} catch (err) {
			toast.error($i18n.t('Failed to start analysis'));
			analysisLoading = false;
		}
	};

	const startPolling = (analysisId: string) => {
		stopPolling();
		pollingInterval = setInterval(async () => {
			try {
				const result = await getTraceAnalysis(localStorage.token, analysisId);
				if (result) {
					analysisResult = result;
					if (result.status === 'completed' || result.status === 'failed') {
						stopPolling();
						analysisLoading = false;
						if (result.status === 'completed') {
							showAnalysisReport = true;
						}
						// 기존 분석 목록 갱신
						if (selectedTrace) {
							loadExistingAnalyses(selectedTrace.trace_id);
						}
					}
				}
			} catch {
				stopPolling();
				analysisLoading = false;
			}
		}, 3000);
	};

	const stopPolling = () => {
		if (pollingInterval) {
			clearInterval(pollingInterval);
			pollingInterval = null;
		}
	};

	const extractTraceToClipboard = async () => {
		if (!selectedTrace) return;

		const lines: string[] = [];
		const divider = '─'.repeat(60);

		// Header
		lines.push('📋 Trace Report');
		lines.push(divider);
		lines.push(`Trace ID: ${selectedTrace.trace_id}`);
		if (selectedTrace.chat_id) lines.push(`Chat ID: ${selectedTrace.chat_id}`);
		lines.push(`Status: ${selectedTrace.status}`);
		lines.push(`Total Latency: ${formatDuration(selectedTrace.total_latency_ms)}`);
		lines.push(`Total Tokens: ${selectedTrace.total_tokens?.toLocaleString() ?? 0}`);
		lines.push('');

		// Runs
		const flattenRuns = (runs: TraceRun[], depth: number = 0): void => {
			for (const run of runs) {
				const indent = '  '.repeat(depth);
				const statusIcon = run.status === 'error' ? '❌' : run.status === 'success' ? '✅' : '⏳';

				lines.push(`${indent}${statusIcon} [${run.run_type.toUpperCase()}] ${run.name} — ${formatDuration(run.latency_ms)}`);

				if (run.error) {
					lines.push(`${indent}   Error: ${run.error}`);
				}

				if (run.token_usage && (run.token_usage.input_tokens || run.token_usage.output_tokens || run.token_usage.prompt_tokens || run.token_usage.completion_tokens)) {
					lines.push(`${indent}   Tokens: ${run.token_usage.input_tokens ?? run.token_usage.prompt_tokens ?? 0} input + ${run.token_usage.output_tokens ?? run.token_usage.completion_tokens ?? 0} output`);
				}

				if (run.model_id) {
					lines.push(`${indent}   Model: ${run.model_id}`);
				}

				// Input summary
				if (run.inputs) {
					const inputStr = JSON.stringify(run.inputs);
					if (inputStr.length > 2) {
						const preview = inputStr.length > 300 ? inputStr.slice(0, 300) + '...' : inputStr;
						lines.push(`${indent}   Input: ${preview}`);
					}
				}

				// Output summary
				if (run.outputs) {
					const outputStr = JSON.stringify(run.outputs);
					if (outputStr.length > 2) {
						const preview = outputStr.length > 300 ? outputStr.slice(0, 300) + '...' : outputStr;
						lines.push(`${indent}   Output: ${preview}`);
					}
				}

				lines.push('');

				if (run.children && run.children.length > 0) {
					flattenRuns(run.children, depth + 1);
				}
			}
		};

		lines.push('📊 Run Tree');
		lines.push(divider);
		flattenRuns(selectedTrace.runs);

		const text = lines.join('\n');
		await navigator.clipboard.writeText(text);
		toast.success($i18n.t('Trace copied to clipboard'));
	};

	const closeDetailModal = () => {
		showDetail = false;
		stopPolling();
		analysisResult = null;
		showAnalysisReport = false;
		showAnalysisForm = false;
		analysisLoading = false;
		existingAnalyses = [];
		userDescription = '';
	};

	const handleSearch = () => {
		page = 1;
		loadTraces();
	};

	const formatDuration = (ms: number | null) => {
		if (ms === null) return '-';
		if (ms < 1000) return `${ms}ms`;
		if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
		return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
	};

	const formatTime = (timestamp: number) => {
		return dayjs(timestamp).format('MM/DD HH:mm:ss');
	};

	const getStatusBadgeType = (status: string): 'success' | 'warning' | 'error' | 'info' | 'muted' => {
		switch (status) {
			case 'success':
				return 'success';
			case 'running':
				return 'warning';
			case 'error':
				return 'error';
			default:
				return 'muted';
		}
	};

	const getRunTypeColor = (runType: string): string => {
		const type = runTypeOptions.find((t) => t.id === runType);
		return type?.color || 'bg-gray-500';
	};

	// inputs에서 사용자 메시지 추출
	const getLastUserMessage = (inputs: Record<string, any> | null): string => {
		if (!inputs) return '';

		// user_message 키로 저장된 경우 (백엔드 트레이싱)
		if (inputs.user_message) {
			return inputs.user_message;
		}

		// messages 배열에서 추출하는 경우
		const messages = inputs.messages;
		if (!Array.isArray(messages) || messages.length === 0) return '';

		// 마지막 사용자 메시지 찾기
		for (let i = messages.length - 1; i >= 0; i--) {
			const msg = messages[i];
			if (msg.role === 'user') {
				const content = msg.content;
				if (typeof content === 'string') {
					return content;
				} else if (Array.isArray(content)) {
					// multimodal content
					const textPart = content.find((p: any) => p.type === 'text');
					return textPart?.text || '';
				}
			}
		}
		return '';
	};

	// 메시지 ID 짧게 표시
	const shortId = (id: string | null): string => {
		if (!id) return '-';
		return id.length > 8 ? id.slice(0, 8) + '...' : id;
	};

	// Text format renderer - 평문 텍스트로 표시
	const renderText = (data: any): string => {
		if (data === null || data === undefined) return '';
		if (typeof data === 'string') return data;
		if (typeof data === 'number' || typeof data === 'boolean') return String(data);
		if (Array.isArray(data)) {
			return data.map((item, i) => {
				if (typeof item === 'string') return item;
				if (typeof item === 'object') return JSON.stringify(item);
				return String(item);
			}).join('\n\n');
		}
		if (typeof data === 'object') {
			// result 키가 있으면 그것만 표시 (가장 흔한 케이스)
			if ('result' in data && typeof data.result === 'string') {
				return data.result;
			}
			// user_message 키가 있으면 그것만 표시
			if ('user_message' in data && typeof data.user_message === 'string') {
				return data.user_message;
			}
			// 그 외에는 키별로 표시
			return Object.entries(data)
				.map(([key, value]) => {
					const valueStr = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
					return `[${key}]\n${valueStr}`;
				})
				.join('\n\n');
		}
		return String(data);
	};

	// 검색어 하이라이트 (HTML 반환)
	const highlightText = (text: string, query: string): string => {
		if (!query.trim()) return escapeHtml(text);
		const escaped = escapeHtml(text);
		const escapedQuery = escapeHtml(query);
		const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
		return escaped.replace(regex, '<mark class="bg-yellow-300 dark:bg-yellow-600 text-black dark:text-white rounded px-0.5">$1</mark>');
	};

	const escapeHtml = (text: string): string => {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#039;');
	};

	// Task 타입 라벨, 색상 및 스타일
	const getTaskLabel = (trace: TraceRun): { label: string; color: string; isBackground: boolean } => {
		const task = trace.meta?.task;
		const runType = trace.run_type;

		// 백그라운드 작업들 (메타 태스크 기반)
		if (task === 'title_generation') {
			return { label: $i18n.t('Title'), color: 'bg-violet-500', isBackground: true };
		} else if (task === 'tag_generation') {
			return { label: $i18n.t('Tag'), color: 'bg-pink-500', isBackground: true };
		} else if (task === 'query_generation') {
			return { label: $i18n.t('Query'), color: 'bg-amber-500', isBackground: true };
		} else if (task === 'autocomplete_generation') {
			return { label: $i18n.t('Autocomplete'), color: 'bg-teal-500', isBackground: true };
		} else if (task === 'emoji_generation') {
			return { label: $i18n.t('Emoji'), color: 'bg-rose-500', isBackground: true };
		} else if (task === 'function_calling') {
			return { label: $i18n.t('Function'), color: 'bg-indigo-500', isBackground: true };
		} else if (task) {
			// 기타 태스크
			return { label: task, color: 'bg-gray-500', isBackground: true };
		}

		// run_type 기반 분류 (메인 응답 관련)
		if (runType === 'chain') {
			// HITL/UnifiedAgent 가 background tasks (title/tags/post_processing) 를
			// 묶어 만든 outer chain — 메인 에이전트 chain 과 구분.
			if (trace.name === 'background_tasks') {
				return {
					label: $i18n.t('Background tasks'),
					color: 'bg-gray-500',
					isBackground: true
				};
			}
			return { label: $i18n.t('Agent'), color: 'bg-purple-500', isBackground: false };
		} else if (runType === 'llm') {
			return { label: $i18n.t('LLM'), color: 'bg-blue-500', isBackground: false };
		} else if (runType === 'tool') {
			return { label: $i18n.t('Tool'), color: 'bg-green-500', isBackground: false };
		} else if (runType === 'retrieval') {
			return { label: $i18n.t('RAG'), color: 'bg-orange-500', isBackground: false };
		} else if (runType === 'web_search') {
			return { label: $i18n.t('Search'), color: 'bg-cyan-500', isBackground: false };
		} else if (runType === 'guardrail') {
			return { label: $i18n.t('Guard'), color: 'bg-red-500', isBackground: false };
		} else if (runType === 'embedding') {
			return { label: $i18n.t('Embed'), color: 'bg-yellow-500', isBackground: false };
		}

		// 기본값
		return { label: $i18n.t('Response'), color: 'bg-blue-500', isBackground: false };
	};

	// traces를 trace_id로 그룹화 (각 trace_id가 별도 카드)
	$: groupedTraces = (() => {
		const groups = new Map<string, TraceGroup>();

		// 1차: trace_id별 그룹 생성
		for (const trace of traces) {
			const key = trace.trace_id;

			if (!groups.has(key)) {
				groups.set(key, {
					traceId: trace.trace_id,
					messageId: trace.message_id,
					userMessage: '',
					traces: [],
					totalLatency: 0,
					hasError: false,
					latestTime: trace.start_time
				});
			}

			const group = groups.get(key)!;
			group.traces.push(trace);
			group.totalLatency += trace.latency_ms || 0;
			if (trace.status === 'error') group.hasError = true;
			if (trace.start_time > group.latestTime) group.latestTime = trace.start_time;

			// 메인 응답(비백그라운드) 트레이스에서만 사용자 메시지 추출
			const taskInfo = getTaskLabel(trace);
			if (!taskInfo.isBackground && !group.userMessage) {
				const msg = getLastUserMessage(trace.inputs);
				if (msg) {
					group.userMessage = msg;
				}
			}
		}

		// 2차: message_id별 사용자 메시지 맵 생성 (메인 응답에서 추출된 것)
		const msgIdToUserMessage = new Map<string, string>();
		for (const group of groups.values()) {
			if (group.userMessage && group.messageId) {
				msgIdToUserMessage.set(group.messageId, group.userMessage);
			}
		}

		// 3차: 백그라운드 작업 카드에 사용자 메시지 전파
		for (const group of groups.values()) {
			if (!group.userMessage && group.messageId) {
				group.userMessage = msgIdToUserMessage.get(group.messageId) || '';
			}
		}

		// 최신 시간 순으로 정렬
		return Array.from(groups.values()).sort((a, b) => b.latestTime - a.latestTime);
	})();

	$: if (page && hasSearched) {
		loadTraces();
	}

	onMount(() => {
		setDateRange('7d');
		loaded = true;

		// URL에서 전달받은 message_id 또는 chat_id가 있으면 자동 검색
		if (initialMessageId) {
			searchQuery = initialMessageId;
			searchType = 'message_id';
			setTimeout(() => {
				loadTraces();
			}, 100);
		} else if (initialChatId) {
			searchQuery = initialChatId;
			searchType = 'chat_id';
			setTimeout(() => {
				loadTraces();
			}, 100);
		}
	});
</script>

<!-- Detail Modal -->
<Modal size="full" bind:show={showDetail} className="bg-white dark:bg-gray-900 rounded-2xl max-w-6xl">
	<div class="px-6 py-5">
		<div class="flex justify-between items-center mb-4 text-gray-900 dark:text-gray-100">
			<div class="flex items-center gap-2">
				<span class="text-xl font-semibold">{$i18n.t('Trace Detail')}</span>
				{#if selectedTrace && selectedTrace.runs.length > 0}
					<span class="px-2 py-0.5 text-sm font-medium bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 rounded-lg">{selectedTrace.runs[0].name}</span>
				{/if}
			</div>
			<div class="flex items-center gap-1.5">
				<!-- 기존 분석 보고서 보기 -->
				{#if existingAnalyses.length > 0 && !analysisLoading}
					<Button
						kind="outlined"
						size="sm"
						type="button"
						on:click={() => {
							analysisResult = existingAnalyses[0];
							showAnalysisReport = true;
						}}
					>
						{$i18n.t('View Report')}
					</Button>
				{/if}
				<!-- 추출 버튼 -->
				<Button kind="outlined" size="sm" type="button" on:click={extractTraceToClipboard}>
					{$i18n.t('Copy Trace')}
				</Button>
				<!-- 분석 버튼 -->
				{#if analysisLoading}
					<Button kind="outlined" size="sm" type="button" disabled loading={true}>
						{$i18n.t('Analyzing...')}
					</Button>
				{:else}
					<Button
						kind="outlined"
						size="sm"
						type="button"
						on:click={() => (showAnalysisForm = !showAnalysisForm)}
					>
						{$i18n.t('Analyze Trace')}
					</Button>
				{/if}
				<!-- 닫기 -->
				<Button kind="text" size="sm" type="button" on:click={closeDetailModal}>
					<XMark className="size-5" />
				</Button>
			</div>
		</div>

		<!-- 분석 입력 폼 -->
		{#if showAnalysisForm}
			<div class="mb-4 p-3 border border-gray-200 dark:border-gray-700 rounded-xl bg-gray-50 dark:bg-gray-850">
				<div class="flex gap-2">
					<!-- 왼쪽: 모델 선택 -->
					<div class="shrink-0 w-48">
						<div class="text-[10px] font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide">{$i18n.t('Analysis Model')}</div>
						<Selector
							value={analysisModelId}
							items={analysisModelOptions}
							size="sm"
							on:change={(e) => {
								analysisModelId = e.detail.value;
							}}
						/>
					</div>
					<!-- 오른쪽: 설명 + 버튼 -->
					<div class="flex-1 min-w-0">
						<div class="text-[10px] font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide">{$i18n.t('Description')}</div>
						<Textarea
							bind:value={userDescription}
							placeholder={$i18n.t("Describe the problem you observed. For example: 'The answer was X but should have been Y. Why did this happen?'")}
							size="sm"
							rows={2}
						/>
						<div class="flex justify-end gap-1.5 mt-1.5">
							<Button
								kind="text"
								size="sm"
								type="button"
								on:click={() => (showAnalysisForm = false)}
							>
								{$i18n.t('Cancel')}
							</Button>
							<Button
								kind="filled"
								size="sm"
								type="button"
								disabled={!analysisModelId}
								on:click={startAnalysis}
							>
								{$i18n.t('Start Analysis')}
							</Button>
						</div>
					</div>
				</div>
			</div>
		{/if}

		{#if selectedTrace}
			<div class="flex flex-col lg:flex-row gap-3" style="height: calc(100vh - 120px);">
				<!-- Run Tree (Left Panel) -->
				<div class="w-full lg:w-[560px] shrink-0 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden flex flex-col bg-white dark:bg-gray-900 max-h-[35vh] lg:max-h-none">
					<!-- Header with Stats -->
					<div class="px-4 py-2.5 bg-gray-50 dark:bg-gray-850 border-b border-gray-200 dark:border-gray-700">
						<div class="flex items-center justify-between">
							<span class="text-sm font-semibold text-gray-600 dark:text-gray-300">{$i18n.t('Runs')}</span>
							<div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
								<span class="font-mono">{formatDuration(selectedTrace.total_latency_ms)}</span>
								<span class="text-gray-300 dark:text-gray-600">|</span>
								<span>{selectedTrace.total_tokens?.toLocaleString() ?? 0} {$i18n.t('tokens')}</span>
							</div>
						</div>
					</div>
					<!-- Tree Content -->
					<div class="p-3 overflow-y-auto flex-1">
						{#each selectedTrace.runs as run}
							<RunTreeItem
								{run}
								depth={0}
								selectedRunId={selectedRun?.id ?? null}
								on:select={(e) => (selectedRun = e.detail)}
							/>
						{/each}
					</div>
				</div>

				<!-- Run Detail (Right Panel) -->
				<div class="flex-1 min-h-[35vh] lg:min-h-0 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden flex flex-col bg-white dark:bg-gray-900">
					<div class="px-4 py-2.5 bg-gray-50 dark:bg-gray-850 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
						{#if selectedRun}
							<span class="px-1.5 py-0.5 text-[10px] font-bold rounded text-white {getRunTypeColor(selectedRun.run_type)}">{selectedRun.run_type.toUpperCase()}</span>
							<span class="text-sm font-semibold text-gray-600 dark:text-gray-300 truncate">{selectedRun.name}</span>
						{:else}
							<span class="text-sm text-gray-400">{$i18n.t('Select a run to view details')}</span>
						{/if}
					</div>
					<div class="p-3 overflow-hidden flex-1 flex flex-col">
						{#if selectedRun}
							<div class="flex flex-col gap-3 h-full min-h-0">
								<!-- Status Bar -->
								<div class="flex flex-wrap items-center gap-2 text-xs pb-2 border-b border-gray-100 dark:border-gray-800 shrink-0">
									<Badge type={getStatusBadgeType(selectedRun.status)} content={selectedRun.status} />
									<span class="text-gray-400 hidden sm:inline">|</span>
									<span class="font-mono text-gray-600 dark:text-gray-400">{formatDuration(selectedRun.latency_ms)}</span>
									{#if selectedRun.model_id}
										<span class="text-gray-400 hidden sm:inline">|</span>
										<code class="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-[10px] text-gray-600 dark:text-gray-400 truncate max-w-[150px] sm:max-w-none">{selectedRun.model_id}</code>
									{/if}
								</div>

								{#if selectedRun.inputs}
									<div class="shrink-0">
										<div class="flex items-center justify-between mb-1.5">
											<div class="text-xs text-gray-500 dark:text-gray-400 font-medium uppercase tracking-wide">{$i18n.t('Inputs')}</div>
											<div class="flex items-center gap-0.5 bg-gray-100 dark:bg-gray-800 rounded p-0.5">
												{#each viewModeOptions as mode}
													<button
														class="px-2 py-0.5 text-[10px] font-medium rounded transition {inputsViewMode === mode.id ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
														on:click={() => inputsViewMode = mode.id}
													>
														{$i18n.t(mode.label)}
													</button>
												{/each}
											</div>
										</div>
										<div class="text-xs bg-gray-50 dark:bg-gray-900 p-2.5 rounded-lg overflow-auto max-h-[20vh] border border-gray-100 dark:border-gray-800">
											{#if inputsViewMode === 'tree'}
												<JsonTreeView data={selectedRun.inputs} maxDepthExpanded={2} />
											{:else if inputsViewMode === 'json'}
												<pre class="whitespace-pre-wrap break-all font-mono text-gray-900 dark:text-gray-200">{JSON.stringify(selectedRun.inputs, null, 2)}</pre>
											{:else}
												<pre class="whitespace-pre-wrap break-all text-gray-900 dark:text-gray-200">{renderText(selectedRun.inputs)}</pre>
											{/if}
										</div>
									</div>
								{/if}

								{#if selectedRun.outputs}
									<div class="flex-1 flex flex-col min-h-0">
										<div class="flex items-center justify-between gap-2 mb-1.5 shrink-0">
											<div class="text-xs text-gray-500 dark:text-gray-400 font-medium uppercase tracking-wide">{$i18n.t('Outputs')}</div>
											<div class="flex items-center gap-1.5">
												<!-- 검색 입력 -->
												<div class="relative flex items-center">
													<input
														type="text"
														bind:value={outputSearchQuery}
														placeholder={$i18n.t('Search...')}
														class="w-24 h-5 px-2 pr-5 text-[10px] bg-gray-100 dark:bg-gray-800 rounded-l border-none outline-none focus:ring-1 focus:ring-blue-500"
														on:keydown={(e) => {
															if (e.key === 'Enter') {
																e.preventDefault();
																if (e.shiftKey) goToPrevMatch();
																else goToNextMatch();
															}
														}}
													/>
													{#if outputSearchQuery}
														<button
															class="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
															on:click={() => { outputSearchQuery = ''; totalMatches = 0; currentMatchIndex = 0; }}
														>
															<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-2.5">
																<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
															</svg>
														</button>
													{:else}
														<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-2.5 absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
															<path fill-rule="evenodd" d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06l-2.755-2.754ZM10.5 7a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z" clip-rule="evenodd" />
														</svg>
													{/if}
												</div>
												<!-- 매치 개수 및 이동 버튼 -->
												{#if outputSearchQuery && totalMatches > 0}
													<div class="flex items-center h-5 bg-gray-100 dark:bg-gray-800 rounded">
														<span class="px-1.5 text-[10px] text-gray-500 dark:text-gray-400 font-mono">
															{currentMatchIndex + 1}/{totalMatches}
														</span>
														<button
															class="px-1 h-full hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
															on:click={goToPrevMatch}
															title={$i18n.t('Previous (Shift+Enter)')}
														>
															<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
																<path fill-rule="evenodd" d="M11.78 9.78a.75.75 0 0 1-1.06 0L8 7.06 5.28 9.78a.75.75 0 0 1-1.06-1.06l3.25-3.25a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06Z" clip-rule="evenodd" />
															</svg>
														</button>
														<button
															class="px-1 h-full hover:bg-gray-200 dark:hover:bg-gray-700 rounded-r text-gray-500 dark:text-gray-400"
															on:click={goToNextMatch}
															title={$i18n.t('Next (Enter)')}
														>
															<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
																<path fill-rule="evenodd" d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
															</svg>
														</button>
													</div>
												{:else if outputSearchQuery && totalMatches === 0}
													<span class="text-[10px] text-gray-400">{$i18n.t('No results')}</span>
												{/if}
												<div class="flex items-center gap-0.5 bg-gray-100 dark:bg-gray-800 rounded p-0.5 h-5">
													{#each viewModeOptions as mode}
														<button
															class="px-2 py-0.5 text-[10px] font-medium rounded transition {outputsViewMode === mode.id ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'}"
															on:click={() => outputsViewMode = mode.id}
														>
															{$i18n.t(mode.label)}
														</button>
													{/each}
												</div>
											</div>
										</div>
										<div
											bind:this={outputContentEl}
											class="text-xs bg-gray-50 dark:bg-gray-900 p-2.5 rounded-lg overflow-auto flex-1 border border-gray-100 dark:border-gray-800"
										>
											{#if outputsViewMode === 'tree'}
												<JsonTreeView data={selectedRun.outputs} maxDepthExpanded={2} searchQuery={outputSearchQuery} />
											{:else if outputsViewMode === 'json'}
												<pre class="whitespace-pre-wrap break-all font-mono text-gray-900 dark:text-gray-200">{@html highlightText(JSON.stringify(selectedRun.outputs, null, 2), outputSearchQuery)}</pre>
											{:else}
												<pre class="whitespace-pre-wrap break-all text-gray-900 dark:text-gray-200">{@html highlightText(renderText(selectedRun.outputs), outputSearchQuery)}</pre>
											{/if}
										</div>
									</div>
								{/if}

								{#if selectedRun.error}
									<div class="shrink-0">
										<div class="text-xs text-red-500 mb-1.5 font-medium uppercase tracking-wide">{$i18n.t('Error')}</div>
										<pre class="text-xs bg-red-50 dark:bg-red-900/20 p-2.5 rounded-lg text-red-600 dark:text-red-400 whitespace-pre-wrap break-all max-h-32 overflow-auto">{selectedRun.error}</pre>
									</div>
								{/if}

								{#if selectedRun.token_usage}
									<div class="bg-gray-50 dark:bg-gray-900 rounded-lg p-2.5 shrink-0">
										<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5 font-medium uppercase tracking-wide">{$i18n.t('Token Usage')}</div>
										<div class="flex gap-4 text-xs">
											<span class="text-gray-600 dark:text-gray-400">{$i18n.t('Input')}: <strong class="text-gray-900 dark:text-white">{(selectedRun.token_usage.input_tokens ?? selectedRun.token_usage.prompt_tokens ?? 0).toLocaleString()}</strong></span>
											<span class="text-gray-600 dark:text-gray-400">{$i18n.t('Output')}: <strong class="text-gray-900 dark:text-white">{(selectedRun.token_usage.output_tokens ?? selectedRun.token_usage.completion_tokens ?? 0).toLocaleString()}</strong></span>
											<span class="text-gray-600 dark:text-gray-400">{$i18n.t('Total')}: <strong class="text-gray-900 dark:text-white">{selectedRun.token_usage.total_tokens?.toLocaleString() ?? 0}</strong></span>
										</div>
									</div>
								{/if}
							</div>
						{:else}
							<div class="text-gray-400 text-center py-16">{$i18n.t('Select a run to view details')}</div>
						{/if}
					</div>
				</div>
			</div>
		{/if}
	</div>
</Modal>

{#if loaded}
	<!-- Header -->
	<div class="mt-0.5 mb-2 flex flex-col gap-2">
		<div class="flex items-center justify-between">
			<div class="flex items-center text-lg font-bold px-0.5">
				{$i18n.t('Tracing')}
				<div class="flex self-center w-[1px] h-6 mx-2.5 bg-gray-50 dark:bg-gray-850" />
				<span class="text-lg font-medium text-gray-500 dark:text-gray-300">{total}</span>
			</div>
			<div class="flex gap-1">
				<Tooltip content={$i18n.t('Refresh')}>
					<Button
						kind="text"
						size="sm"
						type="button"
						on:click={() => {
							if (hasSearched) loadTraces();
						}}
					>
						<ArrowPath className="size-4" />
					</Button>
				</Tooltip>
			</div>
		</div>

		<!-- Search -->
		<div class="flex items-center gap-2">
			<div class="w-36">
				<Selector
					value={searchType}
					items={searchTypeOptions}
					size="sm"
					searchEnabled={false}
					on:change={(e) => {
						const v = e.detail.value;
						if (v === 'chat_id' || v === 'message_id' || v === 'trace_id') {
							searchType = v;
						}
					}}
				/>
			</div>
			<div class="flex-1 max-w-md">
				<Input
					bind:value={searchQuery}
					placeholder={`${$i18n.t('Search')}...`}
					size="sm"
					on:keydown={handleSearchKeydown}
				>
					<svelte:fragment slot="prefix">
						<Search className="size-4" />
					</svelte:fragment>
				</Input>
			</div>
			<Tooltip content={$i18n.t('Search')}>
				<Button kind="outlined" size="sm" type="button" on:click={handleSearch}>
					<Search className="size-4" />
				</Button>
			</Tooltip>
		</div>
	</div>

	<!-- Table -->
	<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
		{#if !hasSearched}
			<div class="text-center py-16 border border-dashed border-gray-300 dark:border-gray-700 rounded-lg">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-12 mx-auto text-gray-300 dark:text-gray-600 mb-4">
					<path fill-rule="evenodd" d="M10.5 3.75a6.75 6.75 0 1 0 0 13.5 6.75 6.75 0 0 0 0-13.5ZM2.25 10.5a8.25 8.25 0 1 1 14.59 5.28l4.69 4.69a.75.75 0 1 1-1.06 1.06l-4.69-4.69A8.25 8.25 0 0 1 2.25 10.5Z" clip-rule="evenodd" />
				</svg>
				<div class="text-gray-500 dark:text-gray-400 text-sm mb-1">{$i18n.t('Enter Chat ID or Message ID to search traces')}</div>
				<div class="text-gray-400 dark:text-gray-500 text-xs">{$i18n.t('Traces will be displayed after searching')}</div>
			</div>
		{:else if traces.length === 0}
			<div class="text-center text-sm text-gray-500 dark:text-gray-400 py-8">
				{$i18n.t('No traces found')}
			</div>
		{:else}
			<!-- trace_id별 개별 카드 -->
			<div class="space-y-3">
				{#each groupedTraces as group, idx (group.traceId)}
					<button
						class="block w-full text-left border border-gray-200 dark:border-gray-700 rounded-xl bg-white dark:bg-gray-900 p-4 hover:bg-gray-50 dark:hover:bg-gray-800 hover:border-gray-300 dark:hover:border-gray-600 transition cursor-pointer"
						on:click={() => openGroupTraces(group)}
						disabled={loadingTrace}
					>
						<div class="flex items-start gap-3">
							<!-- 메시지 아이콘 -->
							<div class="shrink-0 w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4 text-blue-600 dark:text-blue-400">
									<path fill-rule="evenodd" d="M3.43 2.524A41.29 41.29 0 0 1 10 2c2.236 0 4.43.18 6.57.524 1.437.231 2.43 1.49 2.43 2.902v5.148c0 1.413-.993 2.67-2.43 2.902a41.102 41.102 0 0 1-3.55.414c-.28.02-.521.18-.643.413l-1.712 3.293a.75.75 0 0 1-1.33 0l-1.713-3.293a.783.783 0 0 0-.642-.413 41.108 41.108 0 0 1-3.55-.414C1.993 13.245 1 11.986 1 10.574V5.426c0-1.413.993-2.67 2.43-2.902Z" clip-rule="evenodd" />
								</svg>
							</div>

							<!-- 메시지 내용 -->
							<div class="flex-1 min-w-0">
								<div class="text-sm text-gray-900 dark:text-white leading-relaxed line-clamp-2">
									{group.userMessage || $i18n.t('No message content')}
								</div>
								<div class="flex flex-wrap items-center gap-2 mt-1.5 text-xs text-gray-500 dark:text-gray-400">
									<code class="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded font-mono text-[10px]" title={group.traceId}>{shortId(group.traceId)}</code>
									<span class="text-gray-300 dark:text-gray-600">•</span>
									<span>{formatTime(group.latestTime)}</span>
									<span class="text-gray-300 dark:text-gray-600">•</span>
									<span class="font-mono">{formatDuration(group.totalLatency)}</span>
									{#if group.hasError}
										<Badge type="error" content={$i18n.t('Error')} />
									{/if}
								</div>
							</div>

							<!-- Run 타입 배지들 + 개수 -->
							<div class="shrink-0 flex flex-col items-end gap-1.5">
								<div class="flex items-center gap-1 flex-wrap justify-end">
									{#each group.traces as trace}
										{@const ti = getTaskLabel(trace)}
										<span class="flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded bg-gray-100 dark:bg-gray-800 {trace.status === 'error' ? 'ring-1 ring-red-400' : ''}">
											<span class="w-1.5 h-1.5 rounded-full {ti.color}"></span>
											<span class="text-gray-600 dark:text-gray-400">{ti.label}</span>
										</span>
									{/each}
								</div>
								<span class="text-[10px] text-gray-400 dark:text-gray-500">
									{group.traces.length} {$i18n.t('runs')}
								</span>
							</div>
						</div>
					</button>
				{/each}
			</div>

			{#if totalPages > 1}
				<div class="mt-3">
					<Pagination bind:page count={totalPages} />
				</div>
			{/if}
		{/if}
	</div>
{:else}
	<div class="flex items-center justify-center h-64">
		<div class="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-white"></div>
	</div>
{/if}

<TraceAnalysisReport bind:show={showAnalysisReport} analysis={analysisResult} />
