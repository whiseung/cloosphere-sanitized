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
		classifyToolConnectionTools
	} from '$lib/apis/tool-connections';
	import { getGroups } from '$lib/apis/groups';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
	import AccessControlModal from '../common/AccessControlModal.svelte';
	import WorkspaceDetailHeader from '../common/WorkspaceDetailHeader.svelte';
	import ToolDescriptionSection from '../common/ToolDescriptionSection.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { formatBackendError } from '$lib/utils/error';

	// service_id → 표시 라벨 / auth_type → provider 라벨 (카탈로그 정적 매핑).
	const SERVICE_LABELS: Record<string, string> = {
		'google-workspace': 'Google Workspace',
		'microsoft-365': 'Microsoft 365'
	};
	const PROVIDER_LABELS: Record<string, string> = {
		oauth_google: 'Google',
		oauth_microsoft: 'Microsoft'
	};

	let id: string | null = null;
	let item: any = null;
	let loading = false;
	let testingConnection = false;
	let loadingFunctions = false;
	let connectionTestResult: any = null;

	let showAccessControlModal = false;
	let settingsDirty = false;
	let tagSelector: any;
	let group_ids: string[] = [];

	$: isOwnerOrAdmin = $user?.role === 'admin' || item?.user_id === $user?.id;

	$: canWrite =
		$user?.role === 'admin' ||
		($user?.permissions?.workspace?.marketplace === 'write' &&
			(item?.user_id === $user?.id ||
				item?.access_control?.write?.user_ids?.includes($user?.id) ||
				item?.access_control?.write?.group_ids?.some((gid: string) => group_ids.includes(gid))));

	$: serviceLabel = SERVICE_LABELS[item?.meta?.service_id] ?? $i18n.t('Connection');
	$: providerLabel = PROVIDER_LABELS[mcpConnection.auth_type] ?? mcpConnection.auth_type;

	// MCP connection fields (auth_type 은 카탈로그 고정 — 읽기 전용).
	let mcpConnection: {
		url: string;
		auth_type: string;
		key: string;
		headers: Record<string, string>;
		enabled: boolean;
		enabled_tools?: string[];
	} = {
		url: '',
		auth_type: 'none',
		key: '',
		headers: {},
		enabled: true,
		enabled_tools: []
	};

	// 도구 화이트리스트 — 빈 배열이면 전체 활성화로 해석.
	let enabledTools: string[] = [];

	// HITL approval override — { tool_name: "read" | "write" }. meta.approval_overrides 에 저장.
	let approvalOverrides: Record<string, 'read' | 'write'> = {};

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
		// MCP 도구는 하이픈 명명(list-mail-...)이 흔하므로 언더스코어로 정규화. write 접두사를
		// read 접미사보다 먼저 봐서 create_..._list 류가 read 로 새지 않게 한다(백엔드와 동일).
		const name = String(func?.name || '')
			.toLowerCase()
			.replace(/-/g, '_');
		if (READ_PREFIXES.some((p) => name.startsWith(p))) return 'read';
		if (WRITE_PREFIXES.some((p) => name.startsWith(p))) return 'write';
		if (READ_SUFFIXES.some((s) => name.endsWith(s))) return 'read';
		return 'write';
	};
	// 권위 read_only (서버 정의에서 부여) → 'read'|'write'|'' (판별 불가). 마켓플레이스 1st-party 만 채워짐.
	const authorityOf = (func: any): 'read' | 'write' | '' =>
		func?.read_only === true ? 'read' : func?.read_only === false ? 'write' : '';
	// 매핑됐지만 권위 미확정인 도구의 기본은 빈값(사용자/AI 가 설정), 미매핑(일반 도구)은 휴리스틱.
	const baseOf = (func: any): 'read' | 'write' | '' =>
		authorityOf(func) || (func?.category ? '' : classifyDefault(func));
	// 우선순위: 사용자 override > 권위 read_only > 빈값/휴리스틱.
	const getCategory = (
		func: any,
		overrides: Record<string, 'read' | 'write'>
	): 'read' | 'write' | '' => overrides[func.name] ?? baseOf(func);
	const isOverridden = (func: any, overrides: Record<string, 'read' | 'write'>): boolean =>
		overrides[func.name] !== undefined;
	const setCategory = (func: any, value: 'read' | 'write') => {
		const base = baseOf(func);
		const next = { ...approvalOverrides };
		if (value === base) delete next[func.name];
		else next[func.name] = value;
		approvalOverrides = next;
		settingsDirty = true;
	};

	// AI 자동 분류 — LLM 1회 배치로 read/write 판단 → override 맵에 반영. 사용자 검토 후 저장.
	let classifying = false;
	const aiClassifyHandler = async () => {
		if (classifying || functions.length === 0) return;
		// 체크된 도구 중 권위 미확정(빈값)이고 아직 수동 설정 안 된 것만 분류한다 —
		// 서버 정의로 권위 확정된 도구는 분류 불필요(LLM 낭비/오염 방지).
		const names = functions
			.filter(
				(f) =>
					enabledSet.has(f.name) &&
					authorityOf(f) === '' &&
					approvalOverrides[f.name] === undefined
			)
			.map((f) => f.name);
		if (names.length === 0) {
			toast.error($i18n.t('No blank tools to classify. Check tools whose read/write is unset.'));
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
			for (const name of names) {
				const llm = res.classifications[name];
				if (llm !== 'read' && llm !== 'write') continue;
				next[name] = llm; // 빈값 도구 → override 로 설정
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

	let functions: any[] = [];
	let functionQuery = '';

	$: filteredFunctions = functions.filter(
		(f) =>
			f.name.toLowerCase().includes(functionQuery.toLowerCase()) ||
			(f.description && f.description.toLowerCase().includes(functionQuery.toLowerCase()))
	);

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

	// 도메인 카테고리(서버 정의 기준). 좌측 버튼이 카테고리별 일괄 화이트리스트.
	$: categories = (() => {
		const seen = new Set<string>();
		const order: string[] = [];
		for (const f of functions) {
			if (f.category && !seen.has(f.category)) {
				seen.add(f.category);
				order.push(f.category);
			}
		}
		return order;
	})();
	// 카테고리 전체 선택 여부 (enabledSet 반응형 — 버튼 하이라이트용).
	$: categorySelected = (() => {
		const m: Record<string, boolean> = {};
		for (const c of categories) {
			const names = functions.filter((f) => f.category === c).map((f) => f.name);
			m[c] = names.length > 0 && names.every((n) => enabledSet.has(n));
		}
		return m;
	})();
	const categoryCount = (cat: string) => functions.filter((f) => f.category === cat).length;
	// 카테고리별 OAuth 스코프 사용 가능 여부 — 백엔드 /{id}/tools 가 도구에 usable/scope_reason/
	// needed_scopes 를 부여(같은 카테고리는 동일값). usable=null 이면 판별 불가(배지 미표시).
	$: categoryAccess = (() => {
		const m: Record<string, { usable: boolean | null; title: string }> = {};
		for (const c of categories) {
			const f = functions.find((x) => x.category === c);
			const usable = f?.usable ?? null;
			let title = '';
			if (usable === false) {
				if (f?.scope_reason === 'not_requested') {
					title = $i18n.t(
						'Not available — scope not requested (needs setup + app registration).'
					);
				} else {
					const needed = (f?.needed_scopes ?? [])
						.map((s: string) => s.split('/').pop())
						.join(', ');
					title =
						$i18n.t('No permission — admin consent or re-login required.') +
						(needed ? ` (${needed})` : '');
				}
			} else if (usable === true) {
				title = $i18n.t('Permission granted.');
			}
			m[c] = { usable, title };
		}
		return m;
	})();
	const toggleCategory = (cat: string) => {
		const names = functions.filter((f) => f.category === cat).map((f) => f.name);
		if (names.every((n) => enabledSet.has(n))) {
			const rm = new Set(names);
			enabledTools = enabledTools.filter((n) => !rm.has(n));
		} else {
			enabledTools = [...new Set([...enabledTools, ...names])];
		}
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
					if (prop.type) html += `<span class="text-gray-400">: ${prop.type}</span>`;
					if (isRequired) html += `<span class="text-red-400 ml-1">*</span>`;
					if (prop.description)
						html += `<div class="text-gray-400 ml-2 text-[10px]">${prop.description}</div>`;
					html += `</div>`;
				}
				html += `</div>`;
			}
		}
		html += `</div>`;
		return html;
	};

	const loadItem = async () => {
		const res = await getToolConnectionById(localStorage.token, id!).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			item = res;
			toolDescription = item.meta?.tool_description || '';
			approvalOverrides = { ...(item.meta?.approval_overrides || {}) };

			const conn = item.data?.connection ?? {};
			mcpConnection = {
				url: conn.url || '',
				auth_type: conn.auth_type || 'none',
				key: conn.key || '',
				headers: conn.headers || {},
				enabled: conn.enabled !== false,
				enabled_tools: Array.isArray(conn.enabled_tools) ? conn.enabled_tools : []
			};
			enabledTools = [...(mcpConnection.enabled_tools ?? [])];
		} else {
			goto('/workspace/marketplace');
		}
	};

	const saveHandler = async (showToast = true, navigateOnSuccess = false) => {
		loading = true;

		if (!item.name || item.name.trim() === '') {
			toast.error($i18n.t('Please enter a name.'));
			loading = false;
			return;
		}

		let normalizedEnabled = enabledTools;
		if (
			functions.length > 0 &&
			normalizedEnabled.length === functions.length &&
			functions.every((f) => normalizedEnabled.includes(f.name))
		) {
			normalizedEnabled = [];
		}

		const connectionData = {
			type: 'mcp',
			url: mcpConnection.url.trim(),
			auth_type: mcpConnection.auth_type,
			key: mcpConnection.key,
			headers: mcpConnection.headers,
			enabled: mcpConnection.enabled,
			enabled_tools: normalizedEnabled
		};

		const res = await updateToolConnectionById(localStorage.token, id!, {
			name: item.name,
			description: item.description || '',
			data: { ...item.data, connection: connectionData },
			// source/service_id 마커는 item.meta 스프레드로 보존된다.
			meta: {
				...(item.meta || {}),
				tool_description: toolDescription,
				approval_overrides: approvalOverrides
			},
			access_control: item.access_control
		}).catch((e) => {
			toast.error($i18n.t(`${e}`));
			return null;
		});

		if (res) {
			if (showToast) toast.success($i18n.t('Connection saved successfully.'));
			item = res;
			settingsDirty = false;
			if (navigateOnSuccess) goto('/workspace/marketplace');
		}
		loading = false;
	};

	const testConnectionHandler = async () => {
		testingConnection = true;
		connectionTestResult = null;
		functions = [];

		if (!mcpConnection.url) {
			toast.error($i18n.t('Please enter a URL.'));
			testingConnection = false;
			return;
		}

		// 먼저 저장 후 도구 목록 조회로 연결 테스트.
		await saveHandler(false);

		try {
			const tools = await getToolConnectionTools(localStorage.token, id!);
			functions = tools.map((t: any) => ({
				name: t.name,
				description: t.description || '',
				parameters: t.parameters || {},
				category: t.category ?? null,
				read_only: t.read_only ?? null,
				isMcp: true
			}));
			connectionTestResult = { success: true, message: $i18n.t('Connection successful') };
			toast.success(
				$i18n.t('Connection successful! Found {{count}} tools.', { count: tools.length })
			);
		} catch (e) {
			connectionTestResult = { success: false, message: `${e}` };
			toast.error($i18n.t('Connection failed'));
		}

		testingConnection = false;
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
이름: ${item.name}
타입: MCP
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
		await loadItem();
	});
</script>

<div class="flex flex-col w-full h-full translate-y-1">
	{#if item}
		<AccessControlModal
			bind:show={showAccessControlModal}
			bind:accessControl={item.access_control}
			allowPublic={$user?.role === 'admin'}
			onChange={() => {
				saveHandler(false);
			}}
			accessRoles={['read', 'write']}
		/>

		<!-- Header -->
		<WorkspaceDetailHeader
			backHref="/workspace/marketplace"
			badgeContent={serviceLabel}
			bind:name={item.name}
			namePlaceholder={$i18n.t('Connection Name')}
			bind:description={item.description}
			descriptionPlaceholder={$i18n.t('Connection Description')}
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

		<!-- Content: Left (Connection) + Right (Functions) -->
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
								<div class="font-medium mb-0.5">{serviceLabel}</div>
								<div class="opacity-90">
									{$i18n.t(
										"This connection injects each user's own SSO access token into the Authorization header on every call. No key needed — users connect by signing in with the matching provider."
									)}
								</div>
							</div>
						</div>
					</div>

					<!-- Service URL -->
					<div class="flex flex-col gap-1">
						<Input
							label={$i18n.t('Service URL')}
							caption={$i18n.t('Reachable from the Cloosphere backend (server-to-server)')}
							size="sm"
							type="url"
							bind:value={mcpConnection.url}
							placeholder="http://localhost:8000/mcp"
							on:input={() => (settingsDirty = true)}
							readOnly={!canWrite}
						/>
					</div>

					<!-- Provider (read-only — 카탈로그 고정) -->
					<div class="flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Provider')}</div>
						<span class="inline-flex items-center gap-1.5 text-xs font-medium px-2 py-1 rounded-full bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300">
							{providerLabel} · {$i18n.t('User SSO')}
						</span>
					</div>

					<!-- Enabled -->
					<div class="flex w-full justify-between items-center">
						<div class="self-center text-xs font-medium">{$i18n.t('Enabled')}</div>
						<Switch bind:state={mcpConnection.enabled} on:change={() => (settingsDirty = true)} />
					</div>

					<!-- Connection Test Result -->
					{#if connectionTestResult}
						<div
							class="mt-2 p-2 rounded-lg text-xs {connectionTestResult.success
								? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300'
								: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300'}"
						>
							<div class="flex items-center gap-1.5">
								{#if connectionTestResult.success}
									<svg class="size-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
										<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
									</svg>
								{:else}
									<svg class="size-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
										<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
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
							disabled={testingConnection || !mcpConnection.url}
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

					<!-- 카테고리별 일괄 선택 (연결 테스트 후) — 클릭 시 우측 도구 체크 -->
					{#if functions.length > 0 && categories.length > 0}
						<div class="pt-4 mt-2 border-t border-gray-100 dark:border-gray-850">
							<div class="text-xs font-medium text-gray-600 dark:text-gray-300 mb-2">
								{$i18n.t('Tool categories')}
							</div>
							<div class="flex flex-wrap gap-1.5">
								<button
									type="button"
									class="px-2.5 py-1 text-xs rounded-full transition-colors {functions.every((f) =>
										enabledSet.has(f.name)
									)
										? 'bg-blue-500/15 text-blue-700 dark:text-blue-200 outline outline-1 outline-blue-300 dark:outline-blue-700'
										: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'}"
									on:click={() =>
										functions.every((f) => enabledSet.has(f.name))
											? deselectAllTools()
											: selectAllTools()}
								>
									{$i18n.t('All')} ({functions.length})
								</button>
								{#each categories as cat (cat)}
									<button
										type="button"
										title={categoryAccess[cat]?.title}
										class="px-2.5 py-1 text-xs rounded-full transition-colors {categorySelected[cat]
											? 'bg-blue-500/15 text-blue-700 dark:text-blue-200 outline outline-1 outline-blue-300 dark:outline-blue-700'
											: 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'}"
										on:click={() => toggleCategory(cat)}
									>
										{#if categoryAccess[cat]?.usable === true}
											<span
												class="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1 align-middle"
											></span>
										{:else if categoryAccess[cat]?.usable === false}
											<span
												class="inline-block w-1.5 h-1.5 rounded-full bg-red-500 mr-1 align-middle"
											></span>
										{/if}
										{cat} ({categoryCount(cat)})
									</button>
								{/each}
							</div>
							<div class="text-[11px] text-gray-400 dark:text-gray-500 mt-1.5">
								{$i18n.t('Click a category to select its tools on the right.')}
							</div>
							{#if categories.some((c) => categoryAccess[c]?.usable === false)}
								<div
									class="text-[11px] text-red-500 dark:text-red-400 mt-1 flex items-center gap-1"
								>
									<span class="inline-block w-1.5 h-1.5 rounded-full bg-red-500"></span>
									{$i18n.t('Red = no permission for this category (hover for details).')}
								</div>
							{/if}
						</div>
					{/if}
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
							<div class="flex items-center justify-end gap-2 flex-wrap mb-2">
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
								<Tooltip content={formatFunctionTooltip(func)} placement="left" className="block">
									<div
										class="flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-900 cursor-pointer"
										role="button"
										tabindex="0"
										on:click={() => toggleTool(func.name)}
										on:keydown={(e) => {
											if (e.key === 'Enter' || e.key === ' ') {
												e.preventDefault();
												toggleTool(func.name);
											}
										}}
									>
										<div class="pt-0.5 shrink-0">
											<Checkbox state={enabledSet.has(func.name) ? 'checked' : 'unchecked'} />
										</div>
										<div class="flex flex-col gap-1 flex-1 min-w-0">
											<div class="flex items-center gap-2">
												<span class="text-[10px] font-mono px-1 py-0.5 rounded shrink-0 bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300">
													MCP
												</span>
												<span class="text-xs font-medium truncate">{func.name}</span>
												<!-- HITL approval category — 휴리스틱 디폴트, 사용자 override 가능 -->
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
														{#if getCategory(func, approvalOverrides) === ''}
															<span
																class="px-1 text-[9px] text-amber-500 dark:text-amber-400"
																title={$i18n.t('Unset — set read/write or use AI classify')}
															>?</span>
														{:else}
															<span
																class="px-1 text-[9px] text-gray-400 dark:text-gray-500"
																title={$i18n.t('Auto: from server definition or heuristic')}
															>auto</span>
														{/if}
													{/if}
												</div>
											</div>
											{#if func.description}
												<div class="text-[11px] text-gray-500 line-clamp-2">{func.description}</div>
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
