<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';
	import Plotly from 'plotly.js-dist-min';
	import { PLOTLY_FONT_FAMILY } from '$lib/constants';

	import { createEventDispatcher } from 'svelte';
	import { onMount, tick, getContext, setContext } from 'svelte';
	import { writable, type Writable } from 'svelte/store';
	import type { i18n as i18nType, t } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	const dispatch = createEventDispatcher();

	import { createNewFeedback, getFeedbackById, updateFeedbackById } from '$lib/apis/evaluations';
	import { getChatById } from '$lib/apis/chats';
	import { generateTags, generateFollowUps } from '$lib/apis';

	import { config, models, settings, temporaryChatEnabled, TTSWorker, user, theme, userPermissions } from '$lib/stores';
	import { isFeatureAllowed } from '$lib/utils/license';
	import { synthesizeOpenAISpeech } from '$lib/apis/audio';

	import {
		copyToClipboard as _copyToClipboard,
		approximateToHumanReadable,
		getMessageContentParts,
		getCodeBlockContents,
		sanitizeResponseContent,
		createMessagesList,
		formatDate,
		removeDetails,
		removeAllDetails
	} from '$lib/utils';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { brandingUrls } from '$lib/stores/branding';

	import Name from './Name.svelte';
	import ProfileImage from './ProfileImage.svelte';
	import Skeleton from './Skeleton.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import RateComment from './RateComment.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import WebSearchResults from './ResponseMessage/WebSearchResults.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';

	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	import Error from './Error.svelte';
	import Citations from './Citations.svelte';
	import { dedupSources, type Citation } from '$lib/utils/citations';
	import ToolApprovalCard from './ToolApprovalCard.svelte';
	import AskUserCard from './AskUserCard.svelte';
	import AskUserFormCard from './AskUserFormCard.svelte';
	import FilePickerCard from './FilePickerCard.svelte';
	import CodeExecutions from './CodeExecutions.svelte';
	import QueryExecutions from './QueryExecutions.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import AgentReasoning from './Markdown/AgentReasoning.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';
	import FileItem from '$lib/components/common/FileItem.svelte';

	interface MessageType {
		id: string;
		model: string;
		content: string;
		files?: { type: string; url: string }[];
		timestamp: number;
		role: string;
		statusHistory?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		}[];
		status?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		};
		// show_reasoning=detailed 라이브 추론 — 전용 side-channel(message.content 와 분리).
		reasoning?: {
			steps?: {
				kind: 'tool' | 'text';
				tool?: string;
				arg?: string;
				result?: string;
				text?: string;
			}[];
			done?: boolean;
			duration?: number;
		};
		done: boolean;
		error?: boolean | { content: string };
		sources?: string[];
		code_executions?: {
			uuid: string;
			name: string;
			code: string;
			language?: string;
			result?: {
				error?: string;
				output?: string;
				files?: { name: string; url: string }[];
			};
		}[];
		query_executions?: {
			id: string;
			name: string;
			sql: string;
			result?: {
				columns: string[];
				data: Record<string, any>[];
				total_rows: number;
			} | null;
		}[];
		info?: {
			openai?: boolean;
			prompt_tokens?: number;
			completion_tokens?: number;
			total_tokens?: number;
			eval_count?: number;
			eval_duration?: number;
			prompt_eval_count?: number;
			prompt_eval_duration?: number;
			total_duration?: number;
			load_duration?: number;
			usage?: unknown;
		};
		annotation?: { type: string; rating: number };
	}

	export let chatId = '';
	export let history;
	export let messageId;

	let message: MessageType = JSON.parse(JSON.stringify(history.messages[messageId]));
	$: if (history.messages) {
		if (JSON.stringify(message) !== JSON.stringify(history.messages[messageId])) {
			message = JSON.parse(JSON.stringify(history.messages[messageId]));
		}
	}

	export let siblings;

	export let gotoMessage: Function = () => {};
	export let showPreviousMessage: Function;
	export let showNextMessage: Function;

	export let updateChat: Function;
	export let editMessage: Function;
	export let saveMessage: Function;
	export let rateMessage: Function;
	export let actionMessage: Function;
	export let deleteMessage: Function;

	export let submitMessage: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;

	export let addMessages: Function;
	export let handleHITLDecision: Function = () => {};

	export let isLastMessage = true;
	export let readOnly = false;

	let buttonsContainerElement: HTMLDivElement;
	let showDeleteConfirm = false;

	// Citations context — 본문 inline <Source> 가 매칭 citation 으로 popover 렌더
	const citationsStore = writable<Citation[]>([]);
	setContext('citations', citationsStore);
	$: citationsStore.set(dedupSources((message?.sources ?? message?.citations ?? []) as any[]));

	let followUps: string[] = [];
	let followUpsRequestedFor: string | null = null;

	const requestFollowUps = async (msg: MessageType) => {
		if (!msg?.done) return;
		if (!isLastMessage) return;
		if (!$config?.features?.enable_follow_up_generation) return;
		if (followUpsRequestedFor === msg.id) return;

		followUpsRequestedFor = msg.id;

		try {
			const messagesList = createMessagesList(history, msg.id);
			const result = await generateFollowUps(
				localStorage.token,
				msg.model,
				messagesList,
				chatId
			).catch((error) => {
				console.error('Follow-up generation failed:', error);
				return [];
			});
			if (Array.isArray(result)) {
				followUps = result;
			}
		} catch (e) {
			console.error('Follow-up generation error:', e);
		}
	};

	$: if (message?.done && isLastMessage) {
		requestFollowUps(message);
	}

	$: if (!isLastMessage && followUps.length > 0) {
		followUps = [];
		followUpsRequestedFor = null;
	}

	let model = null;
	$: model = $models.find((m) => m.id === message.model);

	// 트레이스 접근 가능 여부: admin이거나 evaluations read 이상 + trace 라이센스
	$: canViewTrace =
		isFeatureAllowed($config, 'trace') &&
		($user?.role === 'admin' ||
			(['read', 'write'].includes($userPermissions?.admin?.evaluations ?? 'none')));

	// DBSphere 차트 관련 상태
	let inlineIframeSrcdoc = '';
	let inlineTextContent = '';
	let inlineChartEligible = false;
	let chartDivs: HTMLElement[] = [];
	let chartDataList: any[] = [];
	let chartTypeOverrides: (string | null)[] = []; // 사용자 선택 차트 타입 (null=원래 타입)
	const dbsphereChartRegex = /\[\[\s*dbsphere:chart\s*\]\]/i;

	$: if (message?.content) {
		inlineChartEligible = dbsphereChartRegex.test(message.content);
		inlineTextContent = message.content
			.replace(dbsphereChartRegex, '')
			.replace(/\n{3,}/g, '\n\n')
			.trim();

		// JSON 파싱 시도 (Plotly.js 방식)
		const jsonMatch = message.content.match(/```json\n([\s\S]*?)\n```/);
		if (inlineChartEligible && jsonMatch) {
			try {
				// Python pandas의 NaN/Infinity를 null로 치환
				const sanitized = jsonMatch[1].replace(/\bNaN\b/g, 'null').replace(/\b-?Infinity\b/g, 'null');
				const parsed = JSON.parse(sanitized);
				// 배열이면 그대로, 단일 객체면 배열로 감싸기 (하위 호환)
				chartDataList = Array.isArray(parsed) ? parsed : [parsed];
				inlineIframeSrcdoc = '';
				// JSON 블록 제거
				inlineTextContent = inlineTextContent
					.replace(/```json[\s\S]*?```/gi, '')
					.trim();
			} catch (e) {
				console.error('Failed to parse chart JSON:', e);
				chartDataList = [];
			}
		} else {
			chartDataList = [];
			
			// HTML/JS 파싱 (iframe 방식 fallback)
			const { html: htmlContent, css: cssContent, js: jsContent } = getCodeBlockContents(
				message.content
			) as { html: string; css: string; js: string };

			if (inlineChartEligible && (htmlContent || cssContent || jsContent)) {
				inlineIframeSrcdoc = `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<${''}style>
		body { background: white; margin: 0; padding: 16px; }
		${cssContent ?? ''}
	</${''}style>
</head>
<body>
	${htmlContent ?? ''}
	<${''}script>
		${jsContent ?? ''}
	</${''}script>
</body>
</html>`;
				// 차트 코드 블록을 텍스트에서 제거
				inlineTextContent = inlineTextContent
					.replace(/```(html|css|js|javascript)[\s\S]*?```/gi, '')
					.trim();
			} else {
				inlineIframeSrcdoc = '';
			}
		}
	} else {
		inlineIframeSrcdoc = '';
		inlineTextContent = '';
		inlineChartEligible = false;
		chartDataList = [];
	}

	// Plotly 차트 렌더링 (멀티 차트 지원)
	let chartResizeObservers: ResizeObserver[] = [];
	$: if (chartDivs.length > 0 && chartDataList.length > 0 && inlineChartEligible) {
		renderAllCharts();
		// 각 차트에 ResizeObserver 연결
		chartDivs.forEach((div, idx) => {
			if (div?.parentElement && !chartResizeObservers[idx]) {
				chartResizeObservers[idx] = new ResizeObserver(() => {
					Plotly.Plots.resize(div);
				});
				chartResizeObservers[idx].observe(div.parentElement);
			}
		});
	}

	function renderAllCharts() {
		const isDark = $theme === 'dark' || ($theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
		chartDataList.forEach((chartItem, idx) => {
			const div = chartDivs[idx];
			if (!div || !chartItem) return;
			if (chartItem.columns && chartItem.data) {
				const override = chartTypeOverrides[idx];
				const renderItem = override ? { ...chartItem, chart_type: override } : chartItem;
				renderFromDataFrame(renderItem, isDark, div);
			} else {
				renderFromPlotlyJSON(chartItem, isDark, div);
			}
		});
	}

	// 차트 타입별 SVG 아이콘 (16x16 viewBox)
	const CHART_TYPE_ICONS: Record<string, { label: string; icon: string }> = {
		table: {
			label: 'Table',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path fill-rule="evenodd" d="M2 3.5A1.5 1.5 0 0 1 3.5 2h9A1.5 1.5 0 0 1 14 3.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9ZM3.5 3a.5.5 0 0 0-.5.5V6h4V3H3.5ZM3 7v2.5h4V7H3Zm0 3.5v2h.5a.5.5 0 0 0 .5-.5v-1.5H3ZM8 13h4.5a.5.5 0 0 0 .5-.5V10.5H8V13ZM13 9.5V7H8v2.5h5ZM8 6h5V3.5a.5.5 0 0 0-.5-.5H8v3Z" clip-rule="evenodd"/></svg>'
		},
		bar: {
			label: 'Bar',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 6h2v6H4V6Zm3-3h2v9H7V3Zm3 5h2v4h-2V8Z"/></svg>'
		},
		line: {
			label: 'Line',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path fill-rule="evenodd" d="M13.5 3.5 9.25 8l-2.5-2L4 9v1.2l3-3.2 2.5 2L14 4.7V3.5h-.5Z" clip-rule="evenodd"/></svg>'
		},
		pie: {
			label: 'Pie',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M7.5 1.018v6.482h6.482A6.5 6.5 0 1 1 7.5 1.018Z"/><path d="M8.5 1.018A6.502 6.502 0 0 1 14.982 7.5H8.5V1.018Z"/></svg>'
		},
		histogram: {
			label: 'Histogram',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 8h1.5v4H4V8Zm2.5-1H8v5H6.5V7ZM9 5h1.5v7H9V5Zm2.5 3H13v4h-1.5V8Z"/></svg>'
		},
		scatter: {
			label: 'Scatter',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><circle cx="5" cy="10" r="1.2"/><circle cx="7" cy="7" r="1.2"/><circle cx="9.5" cy="9" r="1.2"/><circle cx="10" cy="5" r="1.2"/><circle cx="12.5" cy="4" r="1.2"/></svg>'
		},
		heatmap: {
			label: 'Heatmap',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><rect x="2" y="2" width="3.5" height="3.5" rx=".5" opacity=".3"/><rect x="6.25" y="2" width="3.5" height="3.5" rx=".5" opacity=".6"/><rect x="10.5" y="2" width="3.5" height="3.5" rx=".5" opacity=".9"/><rect x="2" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".7"/><rect x="6.25" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".4"/><rect x="10.5" y="6.25" width="3.5" height="3.5" rx=".5" opacity=".8"/><rect x="2" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".5"/><rect x="6.25" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".9"/><rect x="10.5" y="10.5" width="3.5" height="3.5" rx=".5" opacity=".2"/></svg>'
		},
		grouped_bar: {
			label: 'Grouped Bar',
			icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor"><path d="M2 13.5V2h1v11h11v1H2.5a.5.5 0 0 1-.5-.5Z"/><path d="M4 7h1.2v5H4V7Zm1.8-2H7v7H5.8V5ZM8.5 8h1.2v4H8.5V8Zm1.8-2H11.5v6h-1.2V6Z"/></svg>'
		}
	};

	/** 차트 데이터의 컬럼 구성에 따라 호환 가능한 차트 타입 목록 반환 */
	function getAvailableChartTypes(chartItem: any): string[] {
		if (!chartItem?.columns || !chartItem?.data) return [];

		const numCols = chartItem.numeric_cols?.length ?? 0;
		const catCols = chartItem.categorical_cols?.length ?? 0;

		const types: string[] = ['table'];

		if (catCols > 0 && numCols > 0) {
			types.push('bar', 'pie');
		}
		if (numCols > 0) {
			types.push('line', 'histogram');
		}
		if (numCols >= 2) {
			types.push('scatter', 'heatmap');
		}
		if ((catCols >= 2 && numCols > 0) || (catCols >= 1 && numCols >= 2)) {
			types.push('grouped_bar');
		}

		return types;
	}

	/** 개별 차트 타입 변경 시 해당 차트만 재렌더링 */
	function onChartTypeChange(idx: number, newType: string) {
		chartTypeOverrides[idx] = newType;
		const isDark = $theme === 'dark' || ($theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
		const div = chartDivs[idx];
		const chartItem = chartDataList[idx];
		if (!div || !chartItem) return;
		const renderItem = { ...chartItem, chart_type: newType };
		renderFromDataFrame(renderItem, isDark, div);
	}

	function calculateCorrelation(x, y) {
		if (x.length !== y.length || x.length === 0) return 0;
		
		const n = x.length;
		const sumX = x.reduce((a, b) => a + b, 0);
		const sumY = y.reduce((a, b) => a + b, 0);
		const sumXY = x.reduce((sum, xi, i) => sum + xi * y[i], 0);
		const sumX2 = x.reduce((sum, xi) => sum + xi * xi, 0);
		const sumY2 = y.reduce((sum, yi) => sum + yi * yi, 0);
		
		const numerator = n * sumXY - sumX * sumY;
		const denominator = Math.sqrt((n * sumX2 - sumX * sumX) * (n * sumY2 - sumY * sumY));
		
		return denominator === 0 ? 0 : numerator / denominator;
	}

	function renderFromDataFrame(data, isDark, targetDiv) {
		const { columns, data: rows, chart_type, title, numeric_cols, categorical_cols, datetime_cols } = data;
		
		let traces = [];
		let layout = {
			title: { text: title || 'Chart' },
			paper_bgcolor: isDark ? '#1a1a1a' : 'white',
			plot_bgcolor: isDark ? '#2d2d2d' : 'white',
			font: { 
				color: isDark ? '#e5e5e5' : '#333',
				family: PLOTLY_FONT_FAMILY,
				size: 12
			},
			autosize: true,
			margin: { t: 50, r: 20, b: 50, l: 60 },
			hoverlabel: {
				bgcolor: isDark ? '#374151' : 'white',
				bordercolor: isDark ? '#4b5563' : '#e5e7eb',
				font: { color: isDark ? '#e5e5e5' : '#333' }
			},
			xaxis: {
				gridcolor: isDark ? '#374151' : '#e5e7eb',
				linecolor: isDark ? '#4b5563' : '#d1d5db',
				tickfont: { color: isDark ? '#9ca3af' : '#6b7280' }
			},
			yaxis: {
				gridcolor: isDark ? '#374151' : '#e5e7eb',
				linecolor: isDark ? '#4b5563' : '#d1d5db',
				tickfont: { color: isDark ? '#9ca3af' : '#6b7280' }
			}
		};

		const colors = ['#667eea', '#fe5d26', '#15a8a8', '#bf1363', '#f59e0b', '#8b5cf6', '#ec4899'];

		// 차트 타입에 따라 traces 생성
		switch (chart_type) {
			case 'bar':
				if (categorical_cols?.length > 0 && numeric_cols?.length > 0) {
					const xCol = categorical_cols[0];
					const yCol = numeric_cols[0];
					traces = [{
						type: 'bar',
						x: rows.map(row => row[xCol]),
						y: rows.map(row => row[yCol]),
						marker: { color: isDark ? colors[0] : colors[1] }
					}];
					layout.xaxis.title = { text: xCol };
					layout.yaxis.title = { text: yCol };
				}
				break;

			case 'line':
				if (numeric_cols?.length > 0) {
					const xCol = datetime_cols?.[0] || columns[0];
					traces = numeric_cols.slice(0, 5).map((col, i) => ({
						type: 'scatter',
						mode: 'lines+markers',
						name: col,
						x: rows.map(row => row[xCol]),
						y: rows.map(row => row[col]),
						line: { width: 2, color: colors[i % colors.length] },
						marker: { size: 5 }
					}));
					layout.xaxis.title = { text: xCol };
					layout.yaxis.title = { text: 'Value' };
					layout.hovermode = 'x unified';
				}
				break;

			case 'scatter':
				if (numeric_cols?.length >= 2) {
					traces = [{
						type: 'scatter',
						mode: 'markers',
						x: rows.map(row => row[numeric_cols[0]]),
						y: rows.map(row => row[numeric_cols[1]]),
						marker: { size: 8, color: colors[4], opacity: 0.7 }
					}];
					layout.xaxis.title = { text: numeric_cols[0] };
					layout.yaxis.title = { text: numeric_cols[1] };
				}
				break;

			case 'pie':
				if (categorical_cols?.length > 0 && numeric_cols?.length > 0) {
					traces = [{
						type: 'pie',
						labels: rows.map(row => row[categorical_cols[0]]),
						values: rows.map(row => row[numeric_cols[0]]),
						marker: { colors: colors }
					}];
					delete layout.xaxis;
					delete layout.yaxis;
				}
				break;

			case 'histogram':
				if (numeric_cols?.length > 0) {
					const col = numeric_cols[0];
					traces = [{
						type: 'histogram',
						x: rows.map(row => row[col]),
						marker: { color: isDark ? colors[2] : colors[1] }
					}];
					layout.xaxis.title = { text: col };
					layout.yaxis.title = { text: 'Count' };
					layout.showlegend = false;
				}
				break;

			case 'heatmap':
				if (numeric_cols?.length >= 2) {
					// 상관관계 히트맵 생성
					const corrMatrix = [];
					const labels = numeric_cols;
					
					for (let i = 0; i < numeric_cols.length; i++) {
						const row = [];
						for (let j = 0; j < numeric_cols.length; j++) {
							if (i === j) {
								row.push(1);
							} else {
								const col1 = numeric_cols[i];
								const col2 = numeric_cols[j];
								const values1 = rows.map(r => r[col1]).filter(v => v != null);
								const values2 = rows.map(r => r[col2]).filter(v => v != null);
								const corr = calculateCorrelation(values1, values2);
								row.push(corr);
							}
						}
						corrMatrix.push(row);
					}
					
					traces = [{
						type: 'heatmap',
						z: corrMatrix,
						x: labels,
						y: labels,
						colorscale: 'RdBu',
						zmid: 0,
						text: corrMatrix.map(row => row.map(val => val.toFixed(2))),
						texttemplate: '%{text}',
						textfont: { size: 10 }
					}];
					layout.xaxis.title = { text: '' };
					layout.yaxis.title = { text: '' };
				}
				break;

			case 'grouped_bar':
				if (categorical_cols?.length >= 2 && numeric_cols?.length > 0) {
					// 그룹별 막대 차트
					const groupCol = categorical_cols[1];
					const uniqueGroups = [...new Set(rows.map(row => row[groupCol]))];
					
					traces = uniqueGroups.map((group, i) => {
						const groupRows = rows.filter(row => row[groupCol] === group);
						return {
							type: 'bar',
							name: String(group),
							x: groupRows.map(row => row[categorical_cols[0]]),
							y: groupRows.map(row => row[numeric_cols[0]]),
							marker: { color: colors[i % colors.length] }
						};
					});
					layout.barmode = 'group';
					layout.xaxis.title = { text: categorical_cols[0] };
					layout.yaxis.title = { text: numeric_cols[0] };
				} else if (categorical_cols?.length >= 1 && numeric_cols?.length >= 2) {
					// 여러 수치 컬럼 비교
					traces = numeric_cols.slice(0, 5).map((col, i) => ({
						type: 'bar',
						name: col,
						x: rows.map(row => row[categorical_cols[0]]),
						y: rows.map(row => row[col]),
						marker: { color: colors[i % colors.length] }
					}));
					layout.barmode = 'group';
					layout.xaxis.title = { text: categorical_cols[0] };
					layout.yaxis.title = { text: 'Value' };
				}
				break;

			case 'table':
				// Plotly 테이블
				const headerValues = columns;
				const cellValues = columns.map(col => rows.map(row => row[col]));
				
				traces = [{
					type: 'table',
					header: {
						values: headerValues,
						fill: { color: isDark ? '#374151' : '#023d60' },
						font: { color: isDark ? '#e5e5e5' : 'white', size: 12 },
						align: 'left'
					},
					cells: {
						values: cellValues,
						fill: { color: isDark ? '#1a1a1a' : [rows.map((_, i) => i % 2 === 0 ? '#e7e1cf' : 'white')] },
						font: { color: isDark ? '#e5e5e5' : '#023d60', size: 11 },
						align: 'left'
					}
				}];
				delete layout.xaxis;
				delete layout.yaxis;
				layout.margin = { t: 50, r: 10, b: 10, l: 10 };
				break;

			default:
				// Fallback: 기본 bar chart (데이터가 있는 경우만)
				if (columns?.length >= 2) {
					const xCol = columns[0];
					const yCol = columns[1];
					traces = [{
						type: 'bar',
						x: rows.map(row => row[xCol]),
						y: rows.map(row => row[yCol]),
						marker: { color: isDark ? colors[0] : colors[1] }
					}];
					layout.xaxis.title = { text: xCol };
					layout.yaxis.title = { text: yCol };
				}
		}

		const config = {
			responsive: true,
			displayModeBar: true,
			displaylogo: false,
			modeBarButtonsToRemove: ['lasso2d', 'select2d'],
			toImageButtonOptions: {
				format: 'png',
				filename: 'chart',
				height: 800,
				width: 1200
			}
		};

		if (traces.length > 0) {
			Plotly.newPlot(targetDiv, traces, layout, config);
		}
	}

	function renderFromPlotlyJSON(chartData, isDark, targetDiv) {
		// 기존 Plotly JSON 형식 (fallback)
		const layout = {
			...chartData.layout,
			paper_bgcolor: isDark ? '#1a1a1a' : 'white',
			plot_bgcolor: isDark ? '#2d2d2d' : 'white',
			font: { 
				color: isDark ? '#e5e5e5' : '#333',
				family: PLOTLY_FONT_FAMILY,
				size: 12
			},
			autosize: true,
			margin: { t: 40, r: 20, b: 40, l: 60 },
			hoverlabel: {
				bgcolor: isDark ? '#374151' : 'white',
				bordercolor: isDark ? '#4b5563' : '#e5e7eb',
				font: { color: isDark ? '#e5e5e5' : '#333' }
			},
			xaxis: {
				...chartData.layout?.xaxis,
				gridcolor: isDark ? '#374151' : '#e5e7eb',
				linecolor: isDark ? '#4b5563' : '#d1d5db',
				tickfont: { color: isDark ? '#9ca3af' : '#6b7280' }
			},
			yaxis: {
				...chartData.layout?.yaxis,
				gridcolor: isDark ? '#374151' : '#e5e7eb',
				linecolor: isDark ? '#4b5563' : '#d1d5db',
				tickfont: { color: isDark ? '#9ca3af' : '#6b7280' }
			}
		};

		const config = {
			responsive: true,
			displayModeBar: true,
			displaylogo: false,
			modeBarButtonsToRemove: ['lasso2d', 'select2d'],
			toImageButtonOptions: {
				format: 'png',
				filename: 'chart',
				height: 800,
				width: 1200
			}
		};

		Plotly.newPlot(targetDiv, chartData.data, layout, config);
	}

	let edit = false;
	let editedContent = '';
	let editTextAreaElement: HTMLTextAreaElement;

	let messageIndexEdit = false;

	let audioParts: Record<number, HTMLAudioElement | null> = {};
	let speaking = false;
	let speakingIdx: number | undefined;

	let loadingSpeech = false;
	let showRateComment = false;

	const copyToClipboard = async (text) => {
		text = removeAllDetails(text);

		const res = await _copyToClipboard(text, $settings?.copyFormatted ?? false);
		if (res) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	const playAudio = (idx: number) => {
		return new Promise<void>((res) => {
			speakingIdx = idx;
			const audio = audioParts[idx];

			if (!audio) {
				return res();
			}

			audio.play();
			audio.onended = async () => {
				await new Promise((r) => setTimeout(r, 300));

				if (Object.keys(audioParts).length - 1 === idx) {
					speaking = false;
				}

				res();
			};
		});
	};

	const toggleSpeakMessage = async () => {
		if (speaking) {
			try {
				speechSynthesis.cancel();

				if (speakingIdx !== undefined && audioParts[speakingIdx]) {
					audioParts[speakingIdx]!.pause();
					audioParts[speakingIdx]!.currentTime = 0;
				}
			} catch {}

			speaking = false;
			speakingIdx = undefined;
			return;
		}

		if (!(message?.content ?? '').trim().length) {
			toast.info($i18n.t('No content to speak'));
			return;
		}

		speaking = true;

		if ($config.audio.tts.engine === '') {
			let voices = [];
			const getVoicesLoop = setInterval(() => {
				voices = speechSynthesis.getVoices();
				if (voices.length > 0) {
					clearInterval(getVoicesLoop);

					const voice =
						voices
							?.filter(
								(v) => v.voiceURI === ($settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice)
							)
							?.at(0) ?? undefined;

					console.log(voice);

					const speak = new SpeechSynthesisUtterance(message.content);
					speak.rate = $settings.audio?.tts?.playbackRate ?? 1;

					console.log(speak);

					speak.onend = () => {
						speaking = false;
						if ($settings.conversationMode) {
							document.getElementById('voice-input-button')?.click();
						}
					};

					if (voice) {
						speak.voice = voice;
					}

					speechSynthesis.speak(speak);
				}
			}, 100);
		} else {
			loadingSpeech = true;

			const messageContentParts: string[] = getMessageContentParts(
				message.content,
				$config?.audio?.tts?.split_on ?? 'punctuation'
			);

			if (!messageContentParts.length) {
				console.log('No content to speak');
				toast.info($i18n.t('No content to speak'));

				speaking = false;
				loadingSpeech = false;
				return;
			}

			console.debug('Prepared message content for TTS', messageContentParts);

			audioParts = messageContentParts.reduce(
				(acc, _sentence, idx) => {
					acc[idx] = null;
					return acc;
				},
				{} as typeof audioParts
			);

			let lastPlayedAudioPromise = Promise.resolve(); // Initialize a promise that resolves immediately

			if ($settings.audio?.tts?.engine === 'browser-kokoro') {
				if (!$TTSWorker) {
					await TTSWorker.set(
						new KokoroWorker({
							dtype: $settings.audio?.tts?.engineConfig?.dtype ?? 'fp32'
						})
					);

					await $TTSWorker.init();
				}

				for (const [idx, sentence] of messageContentParts.entries()) {
					const blob = await $TTSWorker
						.generate({
							text: sentence,
							voice: $settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice
						})
						.catch((error) => {
							console.error(error);
							toast.error($i18n.t(`${error}`));

							speaking = false;
							loadingSpeech = false;
						});

					if (blob) {
						const audio = new Audio(blob);
						audio.playbackRate = $settings.audio?.tts?.playbackRate ?? 1;

						audioParts[idx] = audio;
						loadingSpeech = false;
						lastPlayedAudioPromise = lastPlayedAudioPromise.then(() => playAudio(idx));
					}
				}
			} else {
				for (const [idx, sentence] of messageContentParts.entries()) {
					const res = await synthesizeOpenAISpeech(
						localStorage.token,
						$settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice
							? ($settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice)
							: $config?.audio?.tts?.voice,
						sentence
					).catch((error) => {
						console.error(error);
						toast.error($i18n.t(`${error}`));

						speaking = false;
						loadingSpeech = false;
					});

					if (res) {
						const blob = await res.blob();
						const blobUrl = URL.createObjectURL(blob);
						const audio = new Audio(blobUrl);
						audio.playbackRate = $settings.audio?.tts?.playbackRate ?? 1;

						audioParts[idx] = audio;
						loadingSpeech = false;
						lastPlayedAudioPromise = lastPlayedAudioPromise.then(() => playAudio(idx));
					}
				}
			}
		}
	};

	let preprocessedDetailsCache = [];

	function preprocessForEditing(content: string): string {
		// Replace <details>...</details> with unique ID placeholder
		const detailsBlocks = [];
		let i = 0;

		content = content.replace(/<details[\s\S]*?<\/details>/gi, (match) => {
			detailsBlocks.push(match);
			return `<details id="__DETAIL_${i++}__"/>`;
		});

		// Store original blocks in the editedContent or globally (see merging later)
		preprocessedDetailsCache = detailsBlocks;

		return content;
	}

	function postprocessAfterEditing(content: string): string {
		const restoredContent = content.replace(
			/<details id="__DETAIL_(\d+)__"\/>/g,
			(_, index) => preprocessedDetailsCache[parseInt(index)] || ''
		);

		return restoredContent;
	}

	const editMessageHandler = async () => {
		edit = true;

		editedContent = preprocessForEditing(message.content);

		await tick();

		editTextAreaElement.style.height = '';
		editTextAreaElement.style.height = `${editTextAreaElement.scrollHeight}px`;
	};

	const editMessageConfirmHandler = async () => {
		const messageContent = postprocessAfterEditing(editedContent ? editedContent : '');
		editMessage(message.id, messageContent, false);

		edit = false;
		editedContent = '';

		await tick();
	};

	const saveAsCopyHandler = async () => {
		const messageContent = postprocessAfterEditing(editedContent ? editedContent : '');

		editMessage(message.id, messageContent);

		edit = false;
		editedContent = '';

		await tick();
	};

	const cancelEditMessage = async () => {
		edit = false;
		editedContent = '';
		await tick();
	};

	let feedbackLoading = false;

	const feedbackHandler = async (rating: number | null = null, details: object | null = null) => {
		feedbackLoading = true;
		console.log('Feedback', rating, details);

		const updatedMessage = {
			...message,
			annotation: {
				...(message?.annotation ?? {}),
				...(rating !== null ? { rating: rating } : {}),
				...(details ? details : {})
			}
		};

		const chat = await getChatById(localStorage.token, chatId).catch((error) => {
			toast.error($i18n.t(`${error}`));
		});
		if (!chat) {
			return;
		}

		const messages = createMessagesList(history, message.id);

		let feedbackItem = {
			type: 'rating',
			data: {
				...(updatedMessage?.annotation ? updatedMessage.annotation : {}),
				model_id: message?.selectedModelId ?? message.model,
				...(history.messages[message.parentId].childrenIds.length > 1
					? {
							sibling_model_ids: history.messages[message.parentId].childrenIds
								.filter((id) => id !== message.id)
								.map((id) => history.messages[id]?.selectedModelId ?? history.messages[id].model)
						}
					: {})
			},
			meta: {
				arena: message ? message.arena : false,
				model_id: message.model,
				message_id: message.id,
				message_index: messages.length,
				chat_id: chatId
			},
			snapshot: {
				chat: chat
			}
		};

		const baseModels = [
			feedbackItem.data.model_id,
			...(feedbackItem.data.sibling_model_ids ?? [])
		].reduce((acc, modelId) => {
			const model = $models.find((m) => m.id === modelId);
			if (model) {
				acc[model.id] = model?.info?.base_model_id ?? null;
			} else {
				// Log or handle cases where corresponding model is not found
				console.warn(`Model with ID ${modelId} not found`);
			}
			return acc;
		}, {});
		feedbackItem.meta.base_models = baseModels;

		let feedback = null;
		if (message?.feedbackId) {
			feedback = await updateFeedbackById(
				localStorage.token,
				message.feedbackId,
				feedbackItem
			).catch((error) => {
				toast.error($i18n.t(`${error}`));
			});
		} else {
			feedback = await createNewFeedback(localStorage.token, feedbackItem).catch((error) => {
				toast.error($i18n.t(`${error}`));
			});

			if (feedback) {
				updatedMessage.feedbackId = feedback.id;
			}
		}

		console.log(updatedMessage);
		saveMessage(message.id, updatedMessage);

		await tick();

		if (!details) {
			showRateComment = true;

			if (!updatedMessage.annotation?.tags) {
				// attempt to generate tags
				const tags = await generateTags(localStorage.token, message.model, messages, chatId).catch(
					(error) => {
						console.error(error);
						return [];
					}
				);
				console.log(tags);

				if (tags) {
					updatedMessage.annotation.tags = tags;
					feedbackItem.data.tags = tags;

					saveMessage(message.id, updatedMessage);
					await updateFeedbackById(
						localStorage.token,
						updatedMessage.feedbackId,
						feedbackItem
					).catch((error) => {
						toast.error($i18n.t(`${error}`));
					});
				}
			}
		}

		feedbackLoading = false;
	};

	const deleteMessageHandler = async () => {
		deleteMessage(message.id);
	};

	$: if (!edit) {
		(async () => {
			await tick();
		})();
	}

	onMount(async () => {
		// console.log('ResponseMessage mounted');

		await tick();
		if (buttonsContainerElement) {
			console.log(buttonsContainerElement);
			buttonsContainerElement.addEventListener('wheel', function (event) {
				// console.log(event.deltaY);

				event.preventDefault();
				if (event.deltaY !== 0) {
					// Adjust horizontal scroll position based on vertical scroll
					buttonsContainerElement.scrollLeft += event.deltaY;
				}
			});
		}
	});
</script>

<DeleteConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete message?')}
	on:confirm={() => {
		deleteMessageHandler();
	}}
/>

{#key message.id}
	<div
		class=" flex w-full message-{message.id}"
		id="message-{message.id}"
		dir={$settings.chatDirection}
	>
		<div class={`shrink-0 ltr:mr-3 rtl:ml-3`}>
			<ProfileImage
				src={model?.info?.meta?.profile_image_url ??
					($i18n.language === 'dg-DG' ? `/doge.png` : $brandingUrls.favicon)}
				className={'size-8'}
			/>
		</div>

		<!-- ltr:pr-11 / rtl:pl-11 = ProfileImage size-8 (32px) + mr-3 (12px) = 44px gutter mirrored for symmetry; keep in sync if ProfileImage size changes -->
		<div class="flex-auto w-0 ltr:pl-1 ltr:pr-11 rtl:pr-1 rtl:pl-11">
			<Name>
				<Tooltip content={model?.name ?? message.model} placement="top-start">
					<span class="line-clamp-1 text-black dark:text-white">
						{model?.name ?? message.model}
					</span>
				</Tooltip>

				{#if message.timestamp}
					<div
						class=" self-center text-xs invisible group-hover:visible text-gray-400 font-medium first-letter:capitalize ml-0.5 translate-y-[1px]"
					>
						<Tooltip content={dayjs(message.timestamp * 1000).format('LLLL')}>
							<span class="line-clamp-1">{formatDate(message.timestamp * 1000)}</span>
						</Tooltip>
					</div>
				{/if}
			</Name>

			<div>
				<div class="chat-{message.role} w-full min-w-full markdown-prose">
					<div>
						{#if (message?.statusHistory ?? [...(message?.status ? [message?.status] : [])]).length > 0}
							{@const status = (
								message?.statusHistory ?? [...(message?.status ? [message?.status] : [])]
							).at(-1)}
							{#if !status?.hidden}
								<div class="status-description flex items-center gap-2 py-0.5">
									{#if status?.done === false}
										<div class="">
											<Spinner className="size-4" />
										</div>
									{/if}

									{#if status?.action === 'web_search' && status?.urls}
										<WebSearchResults {status}>
											<div class="flex flex-col justify-center -space-y-0.5">
												<div
													class="{status?.done === false
														? 'shimmer'
														: ''} text-base line-clamp-1 text-wrap"
												>
													<!-- $i18n.t("Generating search query") -->
													<!-- $i18n.t("No search query generated") -->

													<!-- $i18n.t('Searched {{count}} sites') -->
													{#if status?.description.includes('{{count}}')}
														{$i18n.t(status?.description, {
															count: status?.urls.length
														})}
													{:else if status?.description === 'No search query generated'}
														{$i18n.t('No search query generated')}
													{:else if status?.description === 'Generating search query'}
														{$i18n.t('Generating search query')}
													{:else}
														{$i18n.t(status?.description, {
															toolName: status?.detail ?? '',
															detail: status?.detail ?? '',
															searchQuery: status?.query ?? ''
														})}
													{/if}
												</div>
											</div>
										</WebSearchResults>
									{:else if status?.action === 'knowledge_search'}
										<div class="flex flex-col justify-center -space-y-0.5">
											<div
												class="{status?.done === false
													? 'shimmer'
													: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
											>
												{$i18n.t(`Searching Knowledge for "{{searchQuery}}"`, {
													searchQuery: status.query
												})}
											</div>
										</div>
									{:else}
										<div class="flex flex-col justify-center -space-y-0.5">
											<div
												class="{status?.done === false
													? 'shimmer'
													: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
											>
												<!-- $i18n.t(`Searching "{{searchQuery}}"`) -->
												{#if status?.description.includes('{{searchQuery}}')}
													{$i18n.t(status?.description, {
														searchQuery: status?.query
													})}
												{:else if status?.description === 'No search query generated'}
													{$i18n.t('No search query generated')}
												{:else if status?.description === 'Generating search query'}
													{$i18n.t('Generating search query')}
												{:else}
													{$i18n.t(status?.description, {
														toolName: status?.detail ?? '',
														detail: status?.detail ?? '',
														searchQuery: status?.query ?? ''
													})}
												{/if}
											</div>
										</div>
									{/if}
								</div>
							{/if}
						{/if}

						{#if message?.files && message.files?.filter((f) => f.type === 'image').length > 0}
							<div class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap">
								{#each message.files as file}
									<div>
										{#if file.type === 'image'}
											<Image src={file.url} alt={message.content} />
										{:else}
											<FileItem
												item={file}
												url={file.url}
												name={file.name}
												type={file.type}
												size={file?.size}
												colorClassName="bg-white dark:bg-gray-850 "
											/>
										{/if}
									</div>
								{/each}
							</div>
						{/if}

						{#if edit === true}
							<div class="w-full bg-gray-50 dark:bg-gray-800 rounded-3xl px-5 py-3 my-2">
								<textarea
									id="message-edit-{message.id}"
									bind:this={editTextAreaElement}
									class=" bg-transparent outline-hidden w-full resize-none"
									bind:value={editedContent}
									on:input={(e) => {
										e.target.style.height = '';
										e.target.style.height = `${e.target.scrollHeight}px`;
									}}
									on:keydown={(e) => {
										if (e.key === 'Escape') {
											document.getElementById('close-edit-message-button')?.click();
										}

										const isCmdOrCtrlPressed = e.metaKey || e.ctrlKey;
										const isEnterPressed = e.key === 'Enter';

										if (isCmdOrCtrlPressed && isEnterPressed) {
											document.getElementById('confirm-edit-message-button')?.click();
										}
									}}
								/>

								<div class=" mt-2 mb-1 flex justify-between text-sm font-medium">
									<div>
										<button
											id="save-new-message-button"
											class=" px-4 py-2 bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 border border-gray-100 dark:border-gray-700 text-gray-700 dark:text-gray-200 transition rounded-3xl"
											on:click={() => {
												saveAsCopyHandler();
											}}
										>
											{$i18n.t('Save As Copy')}
										</button>
									</div>

									<div class="flex space-x-1.5">
										<button
											id="close-edit-message-button"
											class="px-4 py-2 bg-white dark:bg-gray-900 hover:bg-gray-100 text-gray-800 dark:text-gray-100 transition rounded-3xl"
											on:click={() => {
												cancelEditMessage();
											}}
										>
											{$i18n.t('Cancel')}
										</button>

										<button
											id="confirm-edit-message-button"
											class=" px-4 py-2 bg-gray-900 dark:bg-white hover:bg-gray-850 text-gray-100 dark:text-gray-800 transition rounded-3xl"
											on:click={() => {
												editMessageConfirmHandler();
											}}
										>
											{$i18n.t('Save')}
										</button>
									</div>
								</div>
							</div>
						{:else}
							<div class="w-full flex flex-col relative" id="response-content-container">
								{#if message?.reasoning?.steps?.length}
									<!-- show_reasoning=detailed: 라이브 "추론 과정" 윈도우.
									     전용 필드(message.reasoning)에서 렌더 — message.content
									     (답변 본문)와 분리되어 API/임베드 등 다른 소비자엔 영향 없음. -->
									<AgentReasoning reasoning={message.reasoning} id={message.id} />
								{/if}
								{#if message.content === '' && !message.error}
									<Skeleton />
								{:else if message.content && message.error !== true}
									<!-- always show message contents even if there's an error -->
									<!-- unless message.error === true which is legacy error handling, where the error message is stored in message.content -->
									<ContentRenderer
										id={message.id}
										{history}
										content={inlineChartEligible ? inlineTextContent : message.content}
										sources={message.sources}
										floatingButtons={message?.done && !readOnly}
										save={!readOnly}
										{model}
										onTaskClick={async (e) => {
											console.log(e);
										}}
										onSourceClick={() => {
											// no-op: inline <Source> chips now render their own popover via Citations context
										}}
										onAddMessages={({ modelId, parentId, messages }) => {
											addMessages({ modelId, parentId, messages });
										}}
										on:update={(e) => {
											const { raw, oldContent, newContent } = e.detail;

											history.messages[message.id].content = history.messages[
												message.id
											].content.replace(raw, raw.replace(oldContent, newContent));

											updateChat();
										}}
										on:select={(e) => {
											const { type, content } = e.detail;

											if (type === 'explain') {
												submitMessage(
													message.id,
													`Explain this section to me in more detail\n\n\`\`\`\n${content}\n\`\`\``
												);
											} else if (type === 'ask') {
												const input = e.detail?.input ?? '';
												submitMessage(message.id, `\`\`\`\n${content}\n\`\`\`\n${input}`);
											}
										}}
									/>

									{#if inlineChartEligible}
										{#if chartDataList.length > 0}
											<!-- Plotly.js 멀티 차트 렌더링 -->
											{#each chartDataList as chartItem, idx}
												{@const availableTypes = getAvailableChartTypes(chartItem)}
												{#if availableTypes.length > 1}
													<div class="mt-4 flex items-center gap-0.5 p-0.5 w-fit rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-850">
														{#each availableTypes as typeKey}
															{@const meta = CHART_TYPE_ICONS[typeKey]}
															{@const isActive = (chartTypeOverrides[idx] ?? chartItem.chart_type) === typeKey}
															{#if meta}
																<Tooltip content={$i18n.t(meta.label)} placement="top">
																	<button
																		class="p-1.5 rounded-md transition-colors {
																			isActive
																				? 'bg-gray-800 text-white dark:bg-white dark:text-gray-900'
																				: 'text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-500 dark:hover:text-gray-200 dark:hover:bg-gray-800'
																		}"
																		on:click={() => onChartTypeChange(idx, typeKey)}
																	>
																		<span class="block size-4">{@html meta.icon}</span>
																	</button>
																</Tooltip>
															{/if}
														{/each}
													</div>
												{/if}
												<div class="mt-1 w-full rounded-lg overflow-auto resize border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
													style="min-height: 300px; height: 500px;"
												>
													<div
														bind:this={chartDivs[idx]}
														class="w-full h-full"
													/>
												</div>
											{/each}
										{:else if inlineIframeSrcdoc}
											<!-- iframe fallback -->
											<div class="mt-4 w-full">
												<iframe
													title={$i18n.t('DBSphere Chart')}
													srcdoc={inlineIframeSrcdoc}
													class="w-full rounded-lg border border-gray-200 dark:border-gray-700"
													style="min-height: 500px; height: 500px;"
													sandbox="allow-scripts allow-same-origin"
												/>
											</div>
										{/if}
									{/if}
								{/if}

								{#if message?.error}
									<Error content={message?.error?.content ?? message.content} />
								{/if}

								{#if message?.sources || message?.citations}
									<Citations
										id={message?.id}
										sources={message?.sources ?? message?.citations}
										content={message?.content ?? ''}
									/>
								{/if}

								{#if message?.hitl_pending && (message.hitl_pending.actions?.length ?? 0) > 0}
									<div class="cloo-hitl-stack">
										<!-- keyed by action 객체: 연속 interrupt(ask_user→resume→ask_user)
										     시 hitl_pending 이 새 actions 배열로 교체되면 카드를 새 인스턴스로
										     재생성한다. 안 그러면 같은 인덱스의 카드가 재사용돼 내부 busy
										     플래그가 stale 하게 남아 두 번째 답변부터 보내기가 막힌다. -->
										{#each message.hitl_pending.actions as action, actionIndex (action)}
											{#if action?.name === 'ask_user'}
												<AskUserCard
													{action}
													{actionIndex}
													pending={!message.hitl_pending.locked &&
														message.hitl_pending.decisions?.[actionIndex] == null}
													decision={message.hitl_pending.decisions?.[actionIndex]?.type ??
														null}
													answeredText={message.hitl_pending.decisions?.[actionIndex]
														?.message ?? ''}
													on:decide={(e) =>
														handleHITLDecision(message.id, e.detail.actionIndex, e.detail.decision)}
												/>
											{:else if action?.name === 'ask_user_form'}
												<AskUserFormCard
													{action}
													{actionIndex}
													pending={!message.hitl_pending.locked &&
														message.hitl_pending.decisions?.[actionIndex] == null}
													decision={message.hitl_pending.decisions?.[actionIndex]?.type ??
														null}
													answeredText={message.hitl_pending.decisions?.[actionIndex]
														?.message ?? ''}
													on:decide={(e) =>
														handleHITLDecision(message.id, e.detail.actionIndex, e.detail.decision)}
												/>
											{:else if action?.name === 'drive_select_files'}
												<FilePickerCard
													{action}
													{actionIndex}
													pending={!message.hitl_pending.locked &&
														message.hitl_pending.decisions?.[actionIndex] == null}
													decision={message.hitl_pending.decisions?.[actionIndex]?.type ??
														null}
													answeredText={message.hitl_pending.decisions?.[actionIndex]
														?.message ?? ''}
													on:decide={(e) =>
														handleHITLDecision(message.id, e.detail.actionIndex, e.detail.decision)}
												/>
											{:else}
												<ToolApprovalCard
													{action}
													{actionIndex}
													pending={!message.hitl_pending.locked &&
														message.hitl_pending.decisions?.[actionIndex] == null}
													decision={message.hitl_pending.decisions?.[actionIndex]?.type ??
														null}
													on:decide={(e) =>
														handleHITLDecision(message.id, e.detail.actionIndex, e.detail.decision)}
												/>
											{/if}
										{/each}
									</div>
								{/if}

								{#if message.code_executions}
									<CodeExecutions codeExecutions={message.code_executions} />
								{/if}

								{#if message.query_executions}
									<QueryExecutions queryExecutions={message.query_executions} />
								{/if}
							</div>
						{/if}
					</div>
				</div>

				{#if !edit && isLastMessage && message.done && followUps.length > 0 && !readOnly}
					<div class="mt-4">
						<div class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
							{$i18n.t('Follow-up questions')}
						</div>
						<div class="flex flex-col gap-1.5">
							{#each followUps as followUp}
								<button
									type="button"
									class="group w-full flex items-center justify-between gap-3 px-3.5 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition text-left"
									on:click={() => {
										submitMessage(message.id, followUp);
									}}
								>
									<span class="flex-1">{followUp}</span>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="w-3.5 h-3.5 shrink-0 text-gray-400 dark:text-gray-500 group-hover:text-gray-600 dark:group-hover:text-gray-300 transition"
									>
										<path
											fill-rule="evenodd"
											d="M3 10a.75.75 0 01.75-.75h10.638L10.23 5.29a.75.75 0 111.04-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.04-1.08l4.158-3.96H3.75A.75.75 0 013 10z"
											clip-rule="evenodd"
										/>
									</svg>
								</button>
							{/each}
						</div>
					</div>
				{/if}

				{#if !edit}
					<div
						bind:this={buttonsContainerElement}
						class="flex justify-start overflow-x-auto buttons text-gray-600 dark:text-gray-500 mt-6"
					>
						{#if message.done || siblings.length > 1}
							{#if siblings.length > 1}
								<div class="flex self-center min-w-fit" dir="ltr">
									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.75 19.5 8.25 12l7.5-7.5"
											/>
										</svg>
									</button>

									{#if messageIndexEdit}
										<div
											class="text-sm flex justify-center font-semibold self-center dark:text-gray-100 min-w-fit"
										>
											<input
												id="message-index-input-{message.id}"
												type="number"
												value={siblings.indexOf(message.id) + 1}
												min="1"
												max={siblings.length}
												on:focus={(e) => {
													e.target.select();
												}}
												on:blur={(e) => {
													gotoMessage(message, e.target.value - 1);
													messageIndexEdit = false;
												}}
												on:keydown={(e) => {
													if (e.key === 'Enter') {
														gotoMessage(message, e.target.value - 1);
														messageIndexEdit = false;
													}
												}}
												class="bg-transparent font-semibold self-center dark:text-gray-100 min-w-fit outline-hidden"
											/>/{siblings.length}
										</div>
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="text-sm tracking-widest font-semibold self-center dark:text-gray-100 min-w-fit"
											on:dblclick={async () => {
												messageIndexEdit = true;

												await tick();
												const input = document.getElementById(`message-index-input-${message.id}`);
												if (input) {
													input.focus();
													input.select();
												}
											}}
										>
											{siblings.indexOf(message.id) + 1}/{siblings.length}
										</div>
									{/if}

									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showNextMessage(message);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="m8.25 4.5 7.5 7.5-7.5 7.5"
											/>
										</svg>
									</button>
								</div>
							{/if}

							{#if message.done}
								{#if !readOnly}
									{#if $user?.role === 'user' ? ($user?.permissions?.chat?.edit ?? true) : true}
										<Tooltip content={$i18n.t('Edit')} placement="bottom">
											<button
												class="{isLastMessage
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
												on:click={() => {
													editMessageHandler();
												}}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2.3"
													stroke="currentColor"
													class="w-4 h-4"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}
								{/if}

								<Tooltip content={$i18n.t('Copy')} placement="bottom">
									<button
										class="{isLastMessage
											? 'visible'
											: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition copy-response-button"
										on:click={() => {
											copyToClipboard(message.content);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2.3"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184"
											/>
										</svg>
									</button>
								</Tooltip>

								{#if $user?.role === 'admin' || ($user?.permissions?.chat?.tts ?? true)}
									<Tooltip content={$i18n.t('Read Aloud')} placement="bottom">
										<button
											id="speak-button-{message.id}"
											class="{isLastMessage
												? 'visible'
												: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
											on:click={() => {
												if (!loadingSpeech) {
													toggleSpeakMessage();
												}
											}}
										>
											{#if loadingSpeech}
												<svg
													class=" w-4 h-4"
													fill="currentColor"
													viewBox="0 0 24 24"
													xmlns="http://www.w3.org/2000/svg"
												>
													<style>
														.spinner_S1WN {
															animation: spinner_MGfb 0.8s linear infinite;
															animation-delay: -0.8s;
														}

														.spinner_Km9P {
															animation-delay: -0.65s;
														}

														.spinner_JApP {
															animation-delay: -0.5s;
														}

														@keyframes spinner_MGfb {
															93.75%,
															100% {
																opacity: 0.2;
															}
														}
													</style>
													<circle class="spinner_S1WN" cx="4" cy="12" r="3" />
													<circle class="spinner_S1WN spinner_Km9P" cx="12" cy="12" r="3" />
													<circle class="spinner_S1WN spinner_JApP" cx="20" cy="12" r="3" />
												</svg>
											{:else if speaking}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2.3"
													stroke="currentColor"
													class="w-4 h-4"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M17.25 9.75 19.5 12m0 0 2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6 4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z"
													/>
												</svg>
											{:else}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2.3"
													stroke="currentColor"
													class="w-4 h-4"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
													/>
												</svg>
											{/if}
										</button>
									</Tooltip>
								{/if}

	
								{#if message.usage}
									<Tooltip
										content={message.usage
											? `<pre>${sanitizeResponseContent(
													JSON.stringify(message.usage, null, 2)
														.replace(/"([^(")"]+)":/g, '$1:')
														.slice(1, -1)
														.split('\n')
														.map((line) => line.slice(2))
														.map((line) => (line.endsWith(',') ? line.slice(0, -1) : line))
														.join('\n')
												)}</pre>`
											: ''}
										placement="bottom"
									>
										<button
											class=" {isLastMessage
												? 'visible'
												: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition whitespace-pre-wrap"
											on:click={() => {
												console.log(message);
											}}
											id="info-{message.id}"
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="2.3"
												stroke="currentColor"
												class="w-4 h-4"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
												/>
											</svg>
										</button>
									</Tooltip>
								{/if}

								{#if !readOnly}
									{#if !$temporaryChatEnabled && ($config?.features.enable_message_rating ?? true)}
										<Tooltip content={$i18n.t('Good Response')} placement="bottom">
											<button
												class="{isLastMessage
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg {(
													message?.annotation?.rating ?? ''
												).toString() === '1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition disabled:cursor-progress disabled:hover:bg-transparent"
												disabled={feedbackLoading}
												on:click={async () => {
													await feedbackHandler(1);
													window.setTimeout(() => {
														document
															.getElementById(`message-feedback-${message.id}`)
															?.scrollIntoView();
													}, 0);
												}}
											>
												<svg
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
													/>
												</svg>
											</button>
										</Tooltip>

										<Tooltip content={$i18n.t('Bad Response')} placement="bottom">
											<button
												class="{isLastMessage
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg {(
													message?.annotation?.rating ?? ''
												).toString() === '-1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition disabled:cursor-progress disabled:hover:bg-transparent"
												disabled={feedbackLoading}
												on:click={async () => {
													await feedbackHandler(-1);
													window.setTimeout(() => {
														document
															.getElementById(`message-feedback-${message.id}`)
															?.scrollIntoView();
													}, 0);
												}}
											>
												<svg
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}

									{#if isLastMessage}
										<Tooltip content={$i18n.t('Continue Response')} placement="bottom">
											<button
												type="button"
												id="continue-response-button"
												class="{isLastMessage
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition regenerate-response-button"
												on:click={() => {
													continueResponse();
												}}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2.3"
													stroke="currentColor"
													class="w-4 h-4"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
													/>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M15.91 11.672a.375.375 0 0 1 0 .656l-5.603 3.113a.375.375 0 0 1-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112Z"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}

									<Tooltip content={$i18n.t('Regenerate')} placement="bottom">
										<button
											type="button"
											class="{isLastMessage
												? 'visible'
												: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition regenerate-response-button"
											on:click={() => {
												showRateComment = false;
												regenerateResponse(message);

												(model?.actions ?? []).forEach((action) => {
													dispatch('action', {
														id: action.id,
														event: {
															id: 'regenerate-response',
															data: {
																messageId: message.id
															}
														}
													});
												});
											}}
										>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												fill="none"
												viewBox="0 0 24 24"
												stroke-width="2.3"
												stroke="currentColor"
												class="w-4 h-4"
											>
												<path
													stroke-linecap="round"
													stroke-linejoin="round"
													d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
												/>
											</svg>
										</button>
									</Tooltip>

									{#if siblings.length > 1}
										<Tooltip content={$i18n.t('Delete')} placement="bottom">
											<button
												type="button"
												id="delete-response-button"
												class="{isLastMessage
													? 'visible'
													: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition regenerate-response-button"
												on:click={() => {
													showDeleteConfirm = true;
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
														d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
													/>
												</svg>
											</button>
										</Tooltip>
									{/if}

									{#if isLastMessage}
										{#each model?.actions ?? [] as action}
											<Tooltip content={action.name} placement="bottom">
												<button
													type="button"
													class="{isLastMessage
														? 'visible'
														: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
													on:click={() => {
														actionMessage(action.id, message);
													}}
												>
													{#if action.icon_url}
														<div class="size-4">
															<img
																src={action.icon_url}
																class="w-4 h-4 {action.icon_url.includes('svg')
																	? 'dark:invert-[80%]'
																	: ''}"
																style="fill: currentColor;"
																alt={action.name}
															/>
														</div>
													{:else}
														<Sparkles strokeWidth="2.1" className="size-4" />
													{/if}
												</button>
											</Tooltip>
										{/each}
									{/if}
								{/if}
							{/if}
						{/if}

						<!-- Copy Message ID / Trace Button -->
						{#if message.done}
							<Tooltip content={canViewTrace ? $i18n.t('View Trace') : $i18n.t('Copy Message ID')} placement="bottom">
								<button
									class="{isLastMessage
										? 'visible'
										: 'invisible group-hover:visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
									on:click={() => {
										if (canViewTrace) {
											// 추적 페이지로 이동
											window.open(`/admin/evaluations?tab=tracing&chat_id=${chatId}`, '_blank');
										} else {
											// 클립보드에 복사
											const info = `Chat ID: ${chatId}\nMessage ID: ${message.id}`;
											navigator.clipboard.writeText(info);
											toast.success($i18n.t('Message ID copied'));
										}
									}}
								>
									{#if canViewTrace}
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
												d="M13.19 8.688a4.5 4.5 0 0 1 1.242 7.244l-4.5 4.5a4.5 4.5 0 0 1-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 0 0-6.364-6.364l-4.5 4.5a4.5 4.5 0 0 0 1.242 7.244"
											/>
										</svg>
									{:else}
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
												d="M5.25 8.25h15m-16.5 7.5h15m-1.8-13.5-3.9 19.5m-2.1-19.5-3.9 19.5"
											/>
										</svg>
									{/if}
								</button>
							</Tooltip>
						{/if}
					</div>

					{#if message.done && showRateComment}
						<RateComment
							bind:message
							bind:show={showRateComment}
							on:save={async (e) => {
								await feedbackHandler(null, {
									...e.detail
								});
							}}
						/>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/key}

<style>
	.buttons::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.buttons {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	.cloo-hitl-stack {
		display: flex;
		flex-direction: column;
		gap: var(--cloo-space-2);
		margin-top: var(--cloo-space-3);
	}
</style>
