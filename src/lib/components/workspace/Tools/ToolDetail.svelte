<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';
	const i18n = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { user, models } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';

	import {
		getToolConnectionById,
		updateToolConnectionById,
		getToolConnectionTools,
		verifyToolConnectionReachability,
		classifyToolConnectionTools
	} from '$lib/apis/tool-connections';
	import { verifyToolServerConnection } from '$lib/apis/configs';
	import { getToolServerData } from '$lib/apis';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import LockClosed from '$lib/components/icons/LockClosed.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '../common/WorkspaceDetailHeader.svelte';
	import ToolDescriptionSection from '../common/ToolDescriptionSection.svelte';
	import MCPConnectionForm from './MCPConnectionForm.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import WorkspaceTagSelector from '$lib/components/common/WorkspaceTagSelector.svelte';
	import { getGroups } from '$lib/apis/groups';
	import { formatBackendError } from '$lib/utils/error';

	let id: string | null = null;
	let tool: any = null;
	let loading = false;
	let testingConnection = false;
	let loadingFunctions = false;
	let connectionTestResult: any = null;

	let showAccessControlModal = false;
	let settingsDirty = false;
	let tagSelector: any;
	let group_ids: string[] = [];

	$: isOwnerOrAdmin = $user?.role === 'admin' || tool?.user_id === $user?.id;

	$: canWrite = $user?.role === 'admin' || (
		$user?.permissions?.workspace?.tools === 'write' && (
			tool?.user_id === $user?.id
			|| tool?.access_control?.write?.user_ids?.includes($user?.id)
			|| tool?.access_control?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))
		)
	);

	// Connection form fields
	let connectionType: 'openapi' | 'mcp' = 'openapi';
	let url = '';
	let path = 'openapi.json';
	let authType: 'bearer' | 'session' = 'bearer';
	let apiKey = '';
	let enabled = true;

	// OpenAPI 스펙 소스 — 'url'(원격 fetch) | 'inline'(붙여넣기/업로드).
	// inline 은 스펙 URL 이 로그인 게이트 뒤에 있을 때 사용. url 은 호출 base 로 양쪽 공통.
	let specSource: 'url' | 'inline' = 'url';
	let specText = '';
	let specFileInput: HTMLInputElement;
	const specPlaceholder = '{ "openapi": "3.0.1", "servers": [...], "paths": { ... } }';

	// MCP connection fields
	let mcpConnection: {
		type: string;
		url: string;
		auth_type: string;
		key: string;
		headers: Record<string, string>;
		enabled: boolean;
		enabled_tools?: string[];
	} = {
		type: 'mcp',
		url: '',
		auth_type: 'none',
		key: '',
		headers: {},
		enabled: true,
		enabled_tools: []
	};

	// 도구 화이트리스트 — 빈 배열이면 전체 활성화로 해석.
	// 사용자가 첫 토글 시 functions 전체 이름을 채워 넣고 그 하나만 빼는 식.
	let enabledTools: string[] = [];

	// HITL approval override — { tool_name: "read" | "write" }.
	// 비어있으면 백엔드 휴리스틱(OpenAPI HTTP method, MCP 이름 patterns) 사용.
	// tool.meta.approval_overrides 에 저장.
	let approvalOverrides: Record<string, 'read' | 'write'> = {};

	// 휴리스틱 디폴트 — 백엔드의 classify_tool_action 과 동일 로직.
	const READ_PREFIXES = [
		'get_', 'list_', 'search_', 'find_', 'fetch_', 'read_',
		'describe_', 'show_', 'query_', 'lookup_', 'view_', 'retrieve_',
		'browse_', 'scan_', 'check_', 'count_', 'verify_', 'validate_',
		'inspect_', 'is_', 'has_', 'download_', 'export_'
	];
	const READ_SUFFIXES = ['_get', '_list', '_search', '_find', '_fetch', '_read', '_info', '_status',
		'_stats', '_count', '_check', '_health', '_metrics'];
	// write(상태 변경) 동사 접두사 — 이름이 _list 등으로 끝나도 write 로 본다(접미사보다 우선).
	const WRITE_PREFIXES = [
		'create_', 'update_', 'delete_', 'remove_', 'add_', 'set_', 'send_', 'move_', 'copy_',
		'share_', 'upload_', 'put_', 'post_', 'patch_', 'insert_', 'modify_', 'edit_', 'write_',
		'replace_', 'reply_', 'forward_', 'accept_', 'decline_', 'cancel_', 'complete_', 'enable_',
		'disable_', 'clear_', 'mark_', 'rename_', 'merge_', 'archive_', 'restore_', 'revoke_',
		'grant_', 'assign_', 'unassign_', 'register_', 'deregister_', 'install_', 'uninstall_',
		'run_', 'execute_', 'trigger_', 'approve_', 'reject_', 'publish_', 'unpublish_', 'start_',
		'stop_', 'draft_', 'import_', 'sync_', 'push_'
	];

	const classifyDefault = (func: any): 'read' | 'write' => {
		// OpenAPI: HTTP method
		if (func?.method) {
			const m = String(func.method).toUpperCase();
			if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return 'read';
			return 'write';
		}
		// MCP: 도구 이름 patterns (하이픈→언더스코어 정규화, write 접두사를 read 접미사보다 우선)
		const name = String(func?.name || '').toLowerCase().replace(/-/g, '_');
		if (READ_PREFIXES.some((p) => name.startsWith(p))) return 'read';
		if (WRITE_PREFIXES.some((p) => name.startsWith(p))) return 'write';
		if (READ_SUFFIXES.some((s) => name.endsWith(s))) return 'read';
		return 'write';
	};

	const getCategory = (func: any, overrides: Record<string, 'read' | 'write'>): 'read' | 'write' =>
		overrides[func.name] ?? classifyDefault(func);

	const isOverridden = (func: any, overrides: Record<string, 'read' | 'write'>): boolean =>
		overrides[func.name] !== undefined;

	const setCategory = (func: any, value: 'read' | 'write') => {
		const heuristic = classifyDefault(func);
		const next = { ...approvalOverrides };
		if (value === heuristic) {
			// 휴리스틱과 일치하면 override 제거 (디폴트로 환원)
			delete next[func.name];
		} else {
			next[func.name] = value;
		}
		approvalOverrides = next;
	};

	// AI 자동 분류 — LLM 1회 배치로 read/write 판단 → override 맵에 반영(휴리스틱과 같으면
	// override 안 두고 auto 유지, 다르면 명시 override). 사용자가 검토 후 저장.
	let classifying = false;
	const aiClassifyHandler = async () => {
		if (classifying || functions.length === 0) return;
		// 활성(체크)된 도구만 분류한다 — R/W 는 실제 사용하는 도구에만 의미가 있으므로.
		const names = [...enabledTools];
		if (names.length === 0) {
			toast.error($i18n.t('Select at least one tool to classify.'));
			return;
		}
		classifying = true;
		const res = await classifyToolConnectionTools(localStorage.token, id!, aiModelId, names).catch(
			(e) => {
				toast.error(`${e}`);
				return null;
			}
		);
		if (res?.classifications) {
			const next = { ...approvalOverrides };
			let count = 0;
			for (const f of functions) {
				const llm = res.classifications[f.name];
				if (llm !== 'read' && llm !== 'write') continue;
				if (llm === classifyDefault(f)) delete next[f.name];
				else next[f.name] = llm;
				count++;
			}
			approvalOverrides = next;
			settingsDirty = true;
			toast.success($i18n.t('AI classified {{count}} tools', { count }));
		}
		classifying = false;
	};

	// Tool description for agent (stored in meta.tool_description)
	let toolDescription = '';
	let generatingToolDesc = false;
	let aiModelId = '';

	// Functions list from OpenAPI spec or MCP tools
	let functions: any[] = [];

	// 함수(operation)별 서버 도달 결과 — name → { ok, status, latency_ms, detail }
	let reachability: Record<string, any> = {};
	let functionQuery = '';

	$: filteredFunctions = functions.filter((f) =>
		f.name.toLowerCase().includes(functionQuery.toLowerCase()) ||
		(f.description && f.description.toLowerCase().includes(functionQuery.toLowerCase()))
	);

	// 화이트리스트 체크 헬퍼 — enabledTools=[] 면 전체 체크된 상태로 보여준다.
	// 화이트리스트는 명시 리스트로 관리. 로드된 enabled_tools 가 비어있으면(=전체 활성)
	// 도구 목록 로드 시 전체 이름으로 확장 → 전체선택/해제 버튼이 정상 동작. 저장 시 전체면 [] 로 환원.
	let toolsInitialized = false;
	$: if (functions.length > 0 && !toolsInitialized) {
		enabledTools =
			enabledTools.length === 0
				? functions.map((f) => f.name)
				: enabledTools.filter((n) => functions.some((f) => f.name === n));
		toolsInitialized = true;
	}

	// 반응형 Set — 템플릿이 직접 참조해 enabledTools 변경(토글/전체선택/해제) 시 즉시 갱신.
	$: enabledSet = new Set(enabledTools);

	const toggleTool = (name: string) => {
		enabledTools = enabledTools.includes(name)
			? enabledTools.filter((n) => n !== name)
			: [...enabledTools, name];
		settingsDirty = true;
	};

	const selectAllTools = () => {
		enabledTools = functions.map((f) => f.name);
		settingsDirty = true;
	};
	const deselectAllTools = () => {
		enabledTools = [];
		settingsDirty = true;
	};

	// AI 분류용 모델 목록 (ToolDescriptionSection 과 동일 소스, aiModelId 공유).
	type ModelLike = { id: string; name: string; preset?: boolean; arena?: boolean };
	$: modelItems = [
		{ value: '', label: $i18n.t('Select AI Model (Default)') },
		...(($models as unknown as ModelLike[]) ?? [])
			.filter((m) => !m.preset && !m.arena)
			.map((m) => ({ value: m.id, label: m.name }))
	];

	const formatFunctionTooltip = (func: any): string => {
		let html = `<div class="text-left max-w-xs">`;
		html += `<div class="font-semibold mb-1">${func.name}</div>`;

		if (func.description) {
			html += `<div class="text-gray-300 text-xs mb-2">${func.description}</div>`;
		}

		if (func.parameters?.properties) {
			const props = func.parameters.properties;
			const required = func.parameters.required || [];
			const paramKeys = Object.keys(props);

			if (paramKeys.length > 0) {
				html += `<div class="text-xs font-medium mb-1">Parameters:</div>`;
				html += `<div class="space-y-1">`;

				for (const key of paramKeys) {
					const prop = props[key];
					const isRequired = required.includes(key);
					html += `<div class="text-xs">`;
					html += `<span class="text-blue-300 font-mono">${key}</span>`;
					if (prop.type) {
						html += `<span class="text-gray-400">: ${prop.type}</span>`;
					}
					if (isRequired) {
						html += `<span class="text-red-400 ml-1">*</span>`;
					}
					if (prop.description) {
						html += `<div class="text-gray-400 ml-2 text-[10px]">${prop.description}</div>`;
					}
					html += `</div>`;
				}

				html += `</div>`;
			}
		}

		html += `</div>`;
		return html;
	};

	const loadTool = async () => {
		const res = await getToolConnectionById(localStorage.token, id!).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			tool = res;
			toolDescription = tool.meta?.tool_description || '';
			approvalOverrides = { ...(tool.meta?.approval_overrides || {}) };

			// Load connection data if exists
			if (tool.data?.connection) {
				const conn = tool.data.connection;
				connectionType = conn.type || 'openapi';

				if (connectionType === 'openapi') {
					url = conn.url || '';
					path = conn.path || 'openapi.json';
					authType = conn.auth_type || 'bearer';
					apiKey = conn.key || '';
					enabled = conn.enabled !== false;
					if (conn.spec) {
						specSource = 'inline';
						specText = JSON.stringify(conn.spec, null, 2);
					} else {
						specSource = 'url';
						specText = '';
					}
				} else if (connectionType === 'mcp') {
					mcpConnection = {
						type: 'mcp',
						url: conn.url || '',
						auth_type: conn.auth_type || 'none',
						key: conn.key || '',
						headers: conn.headers || {},
						enabled: conn.enabled !== false,
						enabled_tools: Array.isArray(conn.enabled_tools) ? conn.enabled_tools : []
					};
					enabledTools = [...(mcpConnection.enabled_tools ?? [])];
				}
			}
		} else {
			goto('/workspace/tools');
		}
	};

	// 인라인 OpenAPI 스펙 파싱/검증 — 유효하면 객체, 아니면 null(토스트).
	const parseSpecText = (): any | null => {
		const text = specText.trim();
		if (!text) {
			toast.error($i18n.t('Please paste or upload an OpenAPI spec.'));
			return null;
		}
		let parsed: any;
		try {
			parsed = JSON.parse(text);
		} catch (e) {
			toast.error($i18n.t('Invalid JSON. Please check the spec.'));
			return null;
		}
		if (!parsed || typeof parsed !== 'object' || !parsed.paths) {
			toast.error($i18n.t('Invalid OpenAPI spec: missing "paths".'));
			return null;
		}
		return parsed;
	};

	const triggerSpecUpload = () => {
		specFileInput?.click();
	};

	const onSpecFileChange = async (e: Event) => {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		try {
			const text = await file.text();
			specText = text;
			settingsDirty = true;
			// 스펙의 servers[0].url 로 호출 base URL 자동 채움(비어있을 때만).
			try {
				const parsed = JSON.parse(text);
				if (!url && Array.isArray(parsed?.servers) && parsed.servers[0]?.url) {
					url = parsed.servers[0].url;
				}
			} catch (_) {}
		} catch (err) {
			toast.error($i18n.t('Failed to read file.'));
		}
		// 같은 파일 재선택 가능하도록 초기화.
		input.value = '';
	};

	const saveHandler = async (showToast = true, navigateOnSuccess = false) => {
		loading = true;

		if (!tool.name || tool.name.trim() === '') {
			toast.error($i18n.t('Please enter a tool name.'));
			loading = false;
			return;
		}

		let connectionData: any;

		if (connectionType === 'openapi') {
			connectionData = {
				type: connectionType,
				url: url.replace(/\/$/, ''), // Remove trailing slash
				path,
				auth_type: authType,
				key: apiKey,
				enabled
			};
			if (specSource === 'inline') {
				const parsed = parseSpecText();
				if (!parsed) {
					loading = false;
					return;
				}
				connectionData.spec = parsed;
			}
		} else if (connectionType === 'mcp') {
			// enabled_tools 정규화: 모든 도구가 다 포함되면 [] 로 (= 전체 활성)
			let normalizedEnabled = enabledTools;
			if (
				functions.length > 0 &&
				normalizedEnabled.length === functions.length &&
				functions.every((f) => normalizedEnabled.includes(f.name))
			) {
				normalizedEnabled = [];
			}
			connectionData = {
				type: 'mcp',
				url: mcpConnection.url,
				auth_type: mcpConnection.auth_type,
				key: mcpConnection.key,
				headers: mcpConnection.headers,
				enabled: mcpConnection.enabled,
				enabled_tools: normalizedEnabled
			};
		}

		const res = await updateToolConnectionById(localStorage.token, id!, {
			name: tool.name,
			description: tool.description || '',
			data: {
				...tool.data,
				connection: connectionData
			},
			meta: {
				...(tool.meta || {}),
				tool_description: toolDescription,
				approval_overrides: approvalOverrides
			},
			access_control: tool.access_control
		}).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			if (showToast) {
				toast.success($i18n.t('Tool saved successfully.'));
			}
			tool = res;
			settingsDirty = false;
			if (navigateOnSuccess) {
				goto('/workspace/tools');
			}
		}

		loading = false;
	};

	const testConnectionHandler = async () => {
		testingConnection = true;
		connectionTestResult = null;
		functions = [];
		reachability = {};

		if (connectionType === 'openapi') {
			if (!url) {
				toast.error($i18n.t('Please enter a URL.'));
				testingConnection = false;
				return;
			}

			if (specSource === 'inline') {
				// 인라인 스펙: 먼저 저장 후 백엔드 커넥터로 도구 목록 조회.
				const parsed = parseSpecText();
				if (!parsed) {
					testingConnection = false;
					return;
				}
				await saveHandler(false);
				try {
					const tools = await getToolConnectionTools(localStorage.token, id!);
					functions = tools.map((t: any) => ({
						name: t.name,
						description: t.description || '',
						parameters: t.parameters || {},
						method: t.method,
						path: t.path
					}));
					// 스펙 파싱 후 각 함수(operation)별 실제 서버 도달 확인 (인라인은 fetch가 없으므로).
					try {
						const rb = await verifyToolConnectionReachability(localStorage.token, id!);
						const results = rb?.results ?? [];
						reachability = Object.fromEntries(results.map((r: any) => [r.name, r]));
						const okN = rb?.ok ?? 0;
						const failN = rb?.failed ?? 0;
						if (failN === 0) {
							connectionTestResult = {
								success: true,
								message: $i18n.t('All {{count}} functions reachable', { count: okN })
							};
							toast.success(
								$i18n.t('Connection successful! Found {{count}} tools.', { count: tools.length })
							);
						} else if (okN === 0) {
							connectionTestResult = {
								success: false,
								message: $i18n.t('All {{count}} functions unreachable', { count: failN })
							};
							toast.error($i18n.t('Server unreachable'));
						} else {
							connectionTestResult = {
								warning: true,
								message: $i18n.t('{{ok}} reachable · {{failed}} failed (of {{total}})', {
									ok: okN,
									failed: failN,
									total: okN + failN
								})
							};
							toast.warning($i18n.t('Some functions unreachable'));
						}
					} catch (e) {
						// 도달 프로브 실패 — 스펙 유효까지만 보고
						connectionTestResult = {
							success: true,
							message: $i18n.t('Connection successful! Found {{count}} tools.', {
								count: tools.length
							})
						};
					}
				} catch (e) {
					connectionTestResult = { success: false, message: `${e}` };
					toast.error($i18n.t('Connection failed'));
				}
				testingConnection = false;
				return;
			}

			try {
				const res = await verifyToolServerConnection(localStorage.token, {
					url: url.replace(/\/$/, ''),
					path,
					auth_type: authType,
					key: apiKey,
					config: { enable: enabled }
				});

				if (res) {
					connectionTestResult = { success: true, message: $i18n.t('Connection successful') };
					toast.success($i18n.t('Connection successful!'));
					// Auto-fetch functions after successful connection
					await fetchFunctionsHandler();
				}
			} catch (e) {
				connectionTestResult = { success: false, message: `${e}` };
				toast.error($i18n.t('Connection failed'));
			}
		} else if (connectionType === 'mcp') {
			// MCP 연결 테스트: 먼저 저장 후 도구 목록 조회
			if (!mcpConnection.url) {
				toast.error($i18n.t('Please enter a URL.'));
				testingConnection = false;
				return;
			}

			// 먼저 저장
			await saveHandler(false);

			// 도구 목록 조회로 연결 테스트
			try {
				const tools = await getToolConnectionTools(localStorage.token, id!);
				functions = tools.map((t: any) => ({
					name: t.name,
					description: t.description || '',
					parameters: t.parameters || {},
					isMcp: true
				}));
				connectionTestResult = { success: true, message: $i18n.t('Connection successful') };
				toast.success($i18n.t('Connection successful! Found {{count}} tools.', { count: tools.length }));
			} catch (e) {
				connectionTestResult = { success: false, message: `${e}` };
				toast.error($i18n.t('Connection failed'));
			}
		}

		testingConnection = false;
	};

	const fetchFunctionsHandler = async () => {
		loadingFunctions = true;

		try {
			if (connectionType === 'mcp') {
				// MCP: API로 도구 목록 조회
				const tools = await getToolConnectionTools(localStorage.token, id!);
				functions = tools.map((t: any) => ({
					name: t.name,
					description: t.description || '',
					parameters: t.parameters || {},
					isMcp: true
				}));
			} else {
				// OpenAPI
				const fullUrl = `${url.replace(/\/$/, '')}/${path}`;
				const token = authType === 'bearer' ? apiKey : localStorage.token;
				const data = await getToolServerData(token, fullUrl);

				if (data) {
					// Parse OpenAPI spec to extract functions
					if (data.specs) {
						functions = data.specs.map((spec: any) => ({
							name: spec.name,
							description: spec.description || '',
							parameters: spec.parameters || {}
						}));
					} else if (data.paths) {
						// Standard OpenAPI format
						functions = [];
						for (const [pathKey, methods] of Object.entries(data.paths)) {
							for (const [method, details] of Object.entries(methods as any)) {
								if (['get', 'post', 'put', 'delete', 'patch'].includes(method)) {
									functions.push({
										name: (details as any).operationId || `${method.toUpperCase()} ${pathKey}`,
										description: (details as any).summary || (details as any).description || '',
										method: method.toUpperCase(),
										path: pathKey
									});
								}
							}
						}
					}
				}
			}
		} catch (e) {
			console.error('Failed to fetch functions:', e);
		}

		loadingFunctions = false;
	};

	async function aiGenerateToolDescription() {
		if (generatingToolDesc || functions.length === 0) return;
		generatingToolDesc = true;
		try {
			const toolList = functions
				.map((f) => f.name + (f.description ? ` - ${f.description}` : ''))
				.join('\n');

			const prompt = `이 도구 서버를 언제 사용해야 하는지 설명을 작성하라.

[도구 서버]
이름: ${tool.name}
타입: ${connectionType.toUpperCase()}
도구(${functions.length}개):
${toolList}

[규칙]
- 위 도구에 실제로 존재하는 기능만 언급하라. 추측하거나 없는 기능을 추가하지 마라
- 어떤 질문이 들어왔을 때 이 도구 서버를 사용해야 하는지 1~2문장으로 작성하라
- 설명만 출력하라`;

			const body: Record<string, any> = { prompt, max_completion_tokens: 2048 };
			if (aiModelId) body.model = aiModelId;
			const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/generate`, {
				method: 'POST',
				headers: {
					Accept: 'application/json',
					'Content-Type': 'application/json',
					authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(body)
			});

			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(formatBackendError(err, $i18n) ?? `HTTP ${res.status}`);
			}

			const data = await res.json();
			const content = data?.choices?.[0]?.message?.content ?? '';
			if (content) {
				toolDescription = content.trim();
				settingsDirty = true;
			} else {
				toast.warning($i18n.t('No result generated. Please try again.'));
			}
		} catch (e: any) {
			toast.error(e?.message ?? formatBackendError(e, $i18n) ?? `${e}`);
		} finally {
			generatingToolDesc = false;
		}
	}

	onMount(async () => {
		id = $page.params.id;

		try {
			const groups = await getGroups(localStorage.token);
			group_ids = groups.map((group: any) => group.id);
		} catch (e) {
			console.error('Failed to load groups:', e);
		}

		await loadTool();
	});
</script>

<div class="flex flex-col w-full h-full translate-y-1">
	{#if tool}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={tool.access_control}
			allowPublic={$user?.permissions?.sharing?.public_tools || $user?.role === 'admin'}
			onChange={() => {
				saveHandler(false);
			}}
			accessRoles={['read', 'write']}
		/>

		<!-- Header -->
		<WorkspaceDetailHeader
			backHref="/workspace/tools"
			badgeContent={$i18n.t('Tool')}
			bind:name={tool.name}
			namePlaceholder={$i18n.t('Tool Name')}
			bind:description={tool.description}
			descriptionPlaceholder={$i18n.t('Tool Description')}
			resourceType="tool"
			resourceId={id ?? ''}
			bind:tagSelector
			showAccess={isOwnerOrAdmin && canWrite}
			{canWrite}
			saving={loading}
			on:change={() => (settingsDirty = true)}
			on:access={() => (showAccessControlModal = true)}
			on:save={() => saveHandler(true, true)}
		>
			<svelte:fragment slot="below">
				<ToolDescriptionSection
					bind:value={toolDescription}
					bind:aiModelId
					generating={generatingToolDesc}
					aiDisabled={functions.length === 0}
					helpText={$i18n.t('Describe when the agent should use this tool server.')}
					placeholder={$i18n.t('e.g. Use for project issue management, message sending, and API integrations.')}
					on:generate={aiGenerateToolDescription}
					on:change={() => (settingsDirty = true)}
				/>
			</svelte:fragment>
		</WorkspaceDetailHeader>

		<!-- Content: Left (Form) + Right (Functions) -->
		<div class="flex flex-col lg:flex-row flex-1 h-full max-h-full pb-2.5 gap-3">
			<!-- Left: Connection Settings -->
			<div class="flex-1 overflow-y-auto order-2 lg:order-1">
				<div class="max-w-md mx-auto w-full space-y-3 px-2 sm:px-0">
					<!-- Info box -->
					<div class="bg-blue-500/10 text-blue-700 dark:text-blue-200 rounded-lg px-3 py-2.5 text-xs">
						<div class="flex gap-2">
							<svg class="size-4 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
							</svg>
							<div>
								{#if connectionType === 'openapi'}
									<div class="font-medium mb-0.5">{$i18n.t('OpenAPI Tool Server')}</div>
									<div class="opacity-90">{$i18n.t('Connect to an OpenAPI compatible API server to use its endpoints as tools.')}</div>
								{:else}
									<div class="font-medium mb-0.5">{$i18n.t('MCP Server')}</div>
									<div class="opacity-90">{$i18n.t('Connect to an MCP (Model Context Protocol) server to use its tools.')}</div>
								{/if}
							</div>
						</div>
					</div>

					<!-- Connection Type -->
					<div class="flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Connection Type')}</div>
						<div class="flex items-center relative">
							<select
								class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right"
								bind:value={connectionType}
								on:change={() => {
									functions = [];
									connectionTestResult = null;
								}}
							>
								<option value="openapi">OpenAPI</option>
								<option value="mcp">MCP</option>
							</select>
						</div>
					</div>

					{#if connectionType === 'openapi'}
						<!-- Spec Source -->
						<div class="flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('Spec Source')}</div>
							<div class="flex items-center relative">
								<select
									class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right"
									bind:value={specSource}
									on:change={() => {
										functions = [];
										connectionTestResult = null;
										settingsDirty = true;
									}}
								>
									<option value="url">{$i18n.t('Fetch from URL')}</option>
									<option value="inline">{$i18n.t('Paste / Upload spec')}</option>
								</select>
							</div>
						</div>

						<!-- API Base URL (호출 base — 양쪽 모드 공통) -->
						<div class="flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('API Base URL')}</div>
							<input
								type="text"
								class="w-56 px-2 py-1 rounded-sm text-xs text-right bg-transparent dark:bg-gray-900 outline-hidden"
								bind:value={url}
								placeholder="https://api.example.com"
							/>
						</div>

						{#if specSource === 'url'}
							<!-- Path -->
							<div class="flex w-full justify-between items-center">
								<div class="self-center text-xs font-medium">{$i18n.t('OpenAPI Spec Path')}</div>
								<input
									type="text"
									class="w-48 px-2 py-1 rounded-sm text-xs text-right bg-transparent dark:bg-gray-900 outline-hidden"
									bind:value={path}
									placeholder="openapi.json"
								/>
							</div>
						{:else}
							<!-- Inline spec (붙여넣기 / 업로드) -->
							<div class="flex flex-col w-full gap-1">
								<div class="flex w-full justify-between items-center">
									<div class="self-center text-xs font-medium">{$i18n.t('OpenAPI Spec (JSON)')}</div>
									<button
										type="button"
										class="px-2 py-1 text-xs font-medium rounded-lg transition-colors bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										on:click={triggerSpecUpload}
									>
										{$i18n.t('Upload file')}
									</button>
								</div>
								<textarea
									class="w-full h-40 px-2 py-1.5 rounded-sm text-xs font-mono bg-transparent dark:bg-gray-900 border border-gray-100 dark:border-gray-800 outline-hidden resize-y"
									bind:value={specText}
									on:input={() => (settingsDirty = true)}
									placeholder={specPlaceholder}
									spellcheck="false"
								></textarea>
								<div class="text-xs text-gray-500">
									{$i18n.t(
										'Paste the OpenAPI JSON, or upload a .json file. Used when the spec URL requires login.'
									)}
								</div>
								<input
									type="file"
									accept=".json,application/json"
									bind:this={specFileInput}
									class="hidden"
									on:change={onSpecFileChange}
								/>
							</div>
						{/if}

						<!-- Auth Type -->
						<div class="flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('Auth Type')}</div>
							<div class="flex items-center relative">
								<select
									class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right"
									bind:value={authType}
								>
									<option value="bearer">Bearer Token</option>
									<option value="session">Session</option>
								</select>
							</div>
						</div>

						<!-- API Key (if bearer) -->
						{#if authType === 'bearer'}
							<div class="flex w-full justify-between items-center">
								<div class="self-center text-xs font-medium">{$i18n.t('API Key')}</div>
								<div class="w-48">
									<SensitiveInput
										inputClassName="w-full px-2 py-1 rounded-sm text-xs text-right bg-transparent dark:bg-gray-900 outline-hidden"
										bind:value={apiKey}
										placeholder="sk-..."
										required={false}
									/>
								</div>
							</div>
						{:else}
							<div class="text-xs text-gray-500 italic">
								{$i18n.t('Session auth will use the current user\'s credentials.')}
							</div>
						{/if}

						<!-- Enabled -->
						<div class="flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('Enabled')}</div>
							<Switch bind:state={enabled} />
						</div>
					{:else if connectionType === 'mcp'}
						<!-- MCP Connection Form -->
						<MCPConnectionForm bind:connection={mcpConnection} />

						<!-- Enabled -->
						<div class="flex w-full justify-between items-center">
							<div class="self-center text-xs font-medium">{$i18n.t('Enabled')}</div>
							<Switch bind:state={mcpConnection.enabled} />
						</div>
					{/if}

					<!-- Connection Test Result -->
					{#if connectionTestResult}
						<div
							class="mt-2 p-2 rounded-lg text-xs {connectionTestResult.warning
								? 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300'
								: connectionTestResult.success
									? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300'
									: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300'}"
						>
							<div class="flex items-center gap-1.5">
								{#if connectionTestResult.warning}
									<svg class="size-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
										<path
											fill-rule="evenodd"
											d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z"
											clip-rule="evenodd"
										/>
									</svg>
								{:else if connectionTestResult.success}
									<svg class="size-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
										<path
											fill-rule="evenodd"
											d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
											clip-rule="evenodd"
										/>
									</svg>
								{:else}
									<svg class="size-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
										<path
											fill-rule="evenodd"
											d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
											clip-rule="evenodd"
										/>
									</svg>
								{/if}
								<span class="font-medium">{connectionTestResult.message}</span>
							</div>
						</div>
					{/if}

					<!-- Action Buttons -->
					<div class="flex justify-end gap-2 pt-4">
						<button
							class="px-3 py-1.5 text-xs font-medium rounded-lg transition-colors
								bg-gray-100 text-gray-700 hover:bg-gray-200
								dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700
								disabled:opacity-50 disabled:cursor-not-allowed"
							on:click={testConnectionHandler}
							disabled={testingConnection ||
								(connectionType === 'openapi'
									? !url || (specSource === 'inline' && !specText.trim())
									: !mcpConnection.url)}
						>
							{#if testingConnection}
								<div class="flex items-center gap-1.5">
									<Spinner className="size-3" />
									{$i18n.t('Testing...')}
								</div>
							{:else}
								{$i18n.t('Test Connection')}
							{/if}
						</button>
					</div>
				</div>
			</div>

			<!-- Right: Functions Panel -->
			<div
				class="w-full lg:w-1/2 lg:shrink-0 flex flex-col py-2 rounded-2xl border border-gray-50 dark:border-gray-850 order-1 lg:order-2 max-h-64 lg:max-h-none lg:h-full"
			>
				<div class="flex flex-col w-full h-full">
					<!-- Panel Header -->
					<div class="px-3 mb-2">
						<div class="flex items-center justify-between mb-2">
							<div class="text-sm font-medium">{$i18n.t('Available Functions')}</div>
							{#if functions.length > 0}
								<div class="text-xs text-gray-500">
									{functions.length} {$i18n.t('functions')}
								</div>
							{/if}
						</div>
						{#if functions.length > 0}
							<div class="flex items-center justify-between gap-2 flex-wrap mb-2">
								<div class="flex items-center gap-1">
									<button
										type="button"
										class="px-2 py-1 text-xs rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										on:click={selectAllTools}
									>
										{$i18n.t('Select all')}
									</button>
									<button
										type="button"
										class="px-2 py-1 text-xs rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
										on:click={deselectAllTools}
									>
										{$i18n.t('Deselect all')}
									</button>
								</div>
								<div class="flex items-center gap-1.5">
									<div class="w-40">
										<Selector
											bind:value={aiModelId}
											items={modelItems}
											size="sm"
											searchEnabled
											placeholder={$i18n.t('Select AI Model (Default)')}
										/>
									</div>
									<Tooltip
										content={$i18n.t(
											'Classify the checked tools read/write with AI. Review and save.'
										)}
										placement="top"
									>
										<button
											type="button"
											class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-lg transition-colors bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
											on:click={aiClassifyHandler}
											disabled={classifying}
										>
											{#if classifying}
												<Spinner className="size-3" />
											{:else}
												<SparklesSolid className="size-3.5" />
											{/if}
											{$i18n.t('Classify with AI')}
										</button>
									</Tooltip>
								</div>
							</div>
						{/if}

						<!-- Search -->
						<div class="flex mb-0.5">
							<div class="self-center ml-1 mr-3">
								<MagnifyingGlass className="size-3.5 text-gray-400" />
							</div>
							<input
								class="w-full text-xs pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
								placeholder={$i18n.t('Search functions...')}
								bind:value={functionQuery}
							/>
						</div>
					</div>

					<hr class="border-gray-50 dark:border-gray-850" />

					<!-- Functions List -->
					<div class="flex-1 overflow-y-auto px-2 pt-2 scrollbar-hidden">
						{#if loadingFunctions}
							<div class="flex justify-center py-8">
								<Spinner className="size-5" />
							</div>
						{:else if functions.length === 0}
							<div class="flex flex-col items-center justify-center py-8 text-center">
								<div class="text-gray-400 dark:text-gray-600 mb-2">
									<svg class="size-8 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
										<path stroke-linecap="round" stroke-linejoin="round" d="M11.42 15.17L17.25 21A2.652 2.652 0 0021 17.25l-5.877-5.877M11.42 15.17l2.496-3.03c.317-.384.74-.626 1.208-.766M11.42 15.17l-4.655 5.653a2.548 2.548 0 11-3.586-3.586l6.837-5.63m5.108-.233c.55-.164 1.163-.188 1.743-.14a4.5 4.5 0 004.486-6.336l-3.276 3.277a3.004 3.004 0 01-2.25-2.25l3.276-3.276a4.5 4.5 0 00-6.336 4.486c.091 1.076-.071 2.264-.904 2.95l-.102.085m-1.745 1.437L5.909 7.5H4.5L2.25 3.75l1.5-1.5L7.5 4.5v1.409l4.26 4.26m-1.745 1.437l1.745-1.437m6.615 8.206L15.75 15.75M4.867 19.125h.008v.008h-.008v-.008z" />
									</svg>
								</div>
								<p class="text-xs text-gray-500 dark:text-gray-400">
									{$i18n.t('Test connection to see functions')}
								</p>
							</div>
						{:else if filteredFunctions.length === 0}
							<div class="text-center py-8 text-xs text-gray-500">
								{$i18n.t('No functions found')}
							</div>
						{:else}
							{#each filteredFunctions as func}
								<Tooltip
									content={formatFunctionTooltip(func)}
									placement="left"
									className="block"
								>
									<div
										class="flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900 {connectionType === 'mcp' ? 'cursor-pointer' : ''}"
										role={connectionType === 'mcp' ? 'button' : undefined}
										tabindex={connectionType === 'mcp' ? 0 : undefined}
										on:click={() => {
											if (connectionType === 'mcp') toggleTool(func.name);
										}}
										on:keydown={(e) => {
											if (connectionType === 'mcp' && (e.key === 'Enter' || e.key === ' ')) {
												e.preventDefault();
												toggleTool(func.name);
											}
										}}
									>
										{#if connectionType === 'mcp'}
											<div class="pt-0.5 shrink-0">
												<Checkbox state={enabledSet.has(func.name) ? 'checked' : 'unchecked'} />
											</div>
										{/if}
										<div class="flex flex-col gap-1 flex-1 min-w-0">
											<div class="flex items-center gap-2">
												{#if func.method}
													<span class="text-[10px] font-mono px-1 py-0.5 rounded shrink-0
														{func.method === 'GET' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : ''}
														{func.method === 'POST' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300' : ''}
														{func.method === 'PUT' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300' : ''}
														{func.method === 'DELETE' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300' : ''}
														{func.method === 'PATCH' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300' : ''}"
													>
														{func.method}
													</span>
												{:else if func.isMcp}
													<span class="text-[10px] font-mono px-1 py-0.5 rounded shrink-0 bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
														MCP
													</span>
												{/if}
												<span class="text-xs font-medium truncate">{func.name}</span>
												{#if reachability[func.name]}
													{@const rb = reachability[func.name]}
													<span
														class="text-[10px] font-medium px-1 py-0.5 rounded shrink-0 {rb.ok
															? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
															: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}"
														title={rb.ok
															? $i18n.t('Reachable (HTTP {{status}}, {{ms}}ms)', {
																	status: rb.status,
																	ms: rb.latency_ms
																})
															: $i18n.t('Failed: {{detail}}', { detail: rb.detail || '' })}
													>
														{rb.ok ? '✓' : '✗'}
													</span>
												{/if}
												<!-- HITL approval category — 휴리스틱 디폴트, 사용자가 override 가능 -->
												<div
													class="ml-auto flex items-center gap-0.5 shrink-0 text-[10px] font-medium rounded overflow-hidden border border-gray-200 dark:border-gray-700"
													role="group"
													on:click|stopPropagation
													on:keydown|stopPropagation
												>
													<button
														type="button"
														class="px-1.5 py-0.5 transition-colors {getCategory(func, approvalOverrides) === 'read' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}"
														title={$i18n.t('Read (auto-approved)')}
														on:click={() => setCategory(func, 'read')}
													>R</button>
													<button
														type="button"
														class="px-1.5 py-0.5 transition-colors {getCategory(func, approvalOverrides) === 'write' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' : 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800'}"
														title={$i18n.t('Write (requires user approval)')}
														on:click={() => setCategory(func, 'write')}
													>W</button>
													{#if !isOverridden(func, approvalOverrides)}
														<span
															class="px-1 text-[9px] text-gray-400 dark:text-gray-500"
															title={$i18n.t('Auto: classified by heuristic')}
														>auto</span>
													{/if}
												</div>
											</div>
											{#if func.description}
												<div class="text-[11px] text-gray-500 line-clamp-2">{func.description}</div>
											{/if}
											{#if func.path}
												<div class="text-[10px] text-gray-400 font-mono truncate">{func.path}</div>
											{/if}
										</div>
									</div>
								</Tooltip>
							{/each}
						{/if}
					</div>
				</div>
			</div>
		</div>
	{:else}
		<div class="w-full h-full flex justify-center items-center">
			<Spinner />
		</div>
	{/if}
</div>
