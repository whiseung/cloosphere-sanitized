<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';
	import { getContext, onMount, tick } from 'svelte';

	import { config, user, settings, tools as _tools, mobile } from '$lib/stores';
	import { createPicker } from '$lib/utils/google-drive-picker';

	import { getTools } from '$lib/apis/tools';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import DocumentArrowUpSolid from '$lib/components/icons/DocumentArrowUpSolid.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import GlobeAltSolid from '$lib/components/icons/GlobeAltSolid.svelte';
	import WrenchSolid from '$lib/components/icons/WrenchSolid.svelte';
	import CameraSolid from '$lib/components/icons/CameraSolid.svelte';
	import PhotoSolid from '$lib/components/icons/PhotoSolid.svelte';


	const i18n = getContext('i18n');

	export let screenCaptureHandler: Function;
	export let uploadFilesHandler: Function;
	export let inputFilesHandler: Function;

	export let uploadGoogleDriveHandler: Function;
	export let uploadOneDriveHandler: Function;
	export let uploadSharePointHandler: Function;

	export let selectedToolIds: string[] = [];

	// Feature toggles
	export let webSearchEnabled: boolean = false;
	export let imageGenerationEnabled: boolean = false;
	export let gmailEnabled: boolean = false;
	export let calendarEnabled: boolean = false;
	export let driveEnabled: boolean = false;

	// Google OAuth connection state — Gmail / Calendar 토글의 5축 게이트 중
	// (5) OAuth 축.  부모가 ``getMyEmailConnections`` 응답에서 파생해 전달.
	// connected = google 토큰 row 존재, 기능별 플래그 = 해당 기능 필수 scope 보유
	// (scope 부족이면 연결돼 있어도 해당 기능 disabled).
	export let googleScopes = { connected: false, gmail: false, calendar: false, drive: false };

	export let selectedImageConnectionIdx: number | null = null;
	export let imageConnections: { idx: number; name: string; engine: string; model: string; size?: string; azure_deployment_name?: string; azure_quality?: string; azure_output_format?: string }[] = [];

	// Agent-level capabilities (null = no agent, show all admin-enabled features)
	// Values: "off" = hidden, "on" = default enabled, "user" = default disabled but visible, true (legacy) = on
	export let modelCapabilities: Record<string, any> | null = null;

	/** Check if a capability is available (not "off") */
	const isCapAvailable = (key: string): boolean => {
		if (modelCapabilities === null) return true; // Regular model: show all
		const val = modelCapabilities[key];
		if (val === true) return true; // Legacy boolean
		if (val === 'on' || val === 'user') return true;
		return false;
	};

	/**
	 * Gmail / Calendar 토글의 5축 게이트 평가 — block reason 반환.
	 *
	 * Reasons (UI 동작 분기):
	 * - 'admin_off'      → admin 이 instance 전체로 비활성 (행 자체 숨김)
	 * - 'capability_off' → 현재 model/agent 가 이 capability='off' (행 자체 숨김)
	 * - 'group_denied'   → 사용자 group 에 features.{gmail,calendar}=false (disabled + tooltip)
	 * - 'not_connected'  → 사용자가 아직 Google OAuth(SSO) 연결 안 함 (행 자체 숨김)
	 *                      — 연결할 방법이 없는 상태에서 무의미한 토글을 노출하지 않는다.
	 * - 'scope_missing'  → 연결은 됐지만 토큰에 이 기능의 필수 scope 없음 —
	 *                      GWS scope 도입 이전 SSO 토큰 (disabled + 재연결 tooltip)
	 * - null             → 모든 축 통과, 토글 가능
	 *
	 * per-conversation 토글은 그 자체가 이 메뉴의 Switch.
	 */
	const googleBlockReason = (feature: 'gmail' | 'calendar' | 'drive'): string | null => {
		const enableKey =
			feature === 'gmail'
				? 'enable_gmail'
				: feature === 'calendar'
					? 'enable_calendar'
					: 'enable_drive';
		if (!$config?.features?.[enableKey]) return 'admin_off';
		// GWS 는 에이전트 capability 전용 — 일반(베이스) 모델(modelCapabilities === null)에서는
		// Google Workspace 메뉴를 노출하지 않는다. 에이전트에서 gmail/calendar/drive capability 를
		// 'on'/'user' 로 설정한 경우에만 노출된다 (web_search/image_generation 의 "일반 모델은
		// admin 활성 기능 모두 노출" 동작과 의도적으로 다름).
		if (modelCapabilities === null) return 'capability_off';
		if (!isCapAvailable(feature)) return 'capability_off';
		if (
			$user?.role !== 'admin' &&
			!$user?.permissions?.features?.[feature]
		)
			return 'group_denied';
		if (!googleScopes.connected) return 'not_connected';
		if (!googleScopes[feature]) return 'scope_missing';
		return null;
	};

	const shouldShowGoogleRow = (feature: 'gmail' | 'calendar' | 'drive'): boolean => {
		const r = googleBlockReason(feature);
		// admin_off / capability_off 외에 not_connected(사용자가 Google SSO 연결 안 함)도
		// 행 자체를 숨긴다. 에이전트에 gmail/calendar/drive 가 켜져 있어도, 사용자가
		// Settings → Connections 에서 Google OAuth 로그인을 하지 않았다면 Google Workspace
		// 메뉴를 노출하지 않는다(연결 수단이 없는 비활성 토글 제거).
		return r !== 'admin_off' && r !== 'capability_off' && r !== 'not_connected';
	};

	const blockTooltip = (reason: string | null, feature: 'gmail' | 'calendar' | 'drive'): string => {
		if (!reason) return '';
		if (reason === 'group_denied')
			return $i18n.t(
				'Your group does not have permission for this feature. Ask your admin.'
			);
		if (reason === 'not_connected')
			return $i18n.t(
				'Connect your Google account in Settings → Connections to use this.'
			);
		if (reason === 'scope_missing')
			return $i18n.t(
				'Your Google account is missing the required permissions. Reconnect it in Settings → Connections.'
			);
		return '';
	};

	// Google Workspace (채팅 더보기) — gmail/calendar/drive 채팅 토글을 이미지
	// 생성과 동일한 우측 플라이아웃 서브메뉴(showGoogleSubmenu)로 묶는다. 메인 행에
	// 활성 토글 개수를 배지로 노출하고, 클릭하면 오른쪽에 토글 패널이 펼쳐진다. 파일
	// 업로드 피커(enable_google_drive_integration)와는 무관 — 그 행은 안 건드린다.
	//
	// 주의: 가시성은 reactive 변수(`$: x = shouldShowGoogleRow(...)`)로 빼면 안 된다.
	// Svelte 는 `$:` 의존성을 함수 호출 내부($config/modelCapabilities 읽기)까지
	// 추적하지 못해 init 1회만 계산된 stale 값이 된다 → 에이전트 전환/설정 로드
	// 시 갱신 안 됨. 따라서 가시성 조건은 템플릿 {#if} 에 인라인으로 둔다
	// (섹션 가드와 동일 패턴 — 매 렌더 재평가).
	$: googleActiveCount =
		(shouldShowGoogleRow('gmail') && gmailEnabled && !googleBlockReason('gmail') ? 1 : 0) +
		(shouldShowGoogleRow('calendar') && calendarEnabled && !googleBlockReason('calendar')
			? 1
			: 0) +
		(shouldShowGoogleRow('drive') && driveEnabled && !googleBlockReason('drive') ? 1 : 0);

	export let onClose: Function;

	let tools = {};
	let show = false;
	let showImageSubmenu = false;
	let showGoogleSubmenu = false;

	$: if (show) {
		init();
	}

	$: if (!show) {
		showImageSubmenu = false;
		showGoogleSubmenu = false;
	}

	let fileUploadEnabled = true;
	$: fileUploadEnabled = $user?.role === 'admin' || $user?.permissions?.chat?.file_upload;

	const init = async () => {
		if ($_tools === null) {
			await _tools.set(await getTools(localStorage.token));
		}

		tools = $_tools.reduce((a, tool, i, arr) => {
			a[tool.id] = {
				name: tool.name,
				description: tool.meta.description,
				enabled: selectedToolIds.includes(tool.id)
			};
			return a;
		}, {});
	};

	const detectMobile = () => {
		const userAgent = navigator.userAgent || navigator.vendor || window.opera;
		return /android|iphone|ipad|ipod|windows phone/i.test(userAgent);
	};

	function getImageConnectionTooltip(conn: typeof imageConnections[0]) {
		const parts: string[] = [];
		if (conn.model) parts.push(`${$i18n.t('Model')}: ${conn.model}`);
		if (conn.azure_deployment_name) parts.push(`${$i18n.t('Deployment')}: ${conn.azure_deployment_name}`);
		if (conn.size) parts.push(`${$i18n.t('Size')}: ${conn.size}`);
		if (conn.azure_output_format) parts.push(`${$i18n.t('Format')}: ${conn.azure_output_format.toUpperCase()}`);
		if (conn.azure_quality) parts.push(`${$i18n.t('Quality')}: ${conn.azure_quality}`);
		return parts.join('<br>') || conn.engine;
	}

	function handleFileChange(event) {
		const inputFiles = Array.from(event.target?.files);
		if (inputFiles && inputFiles.length > 0) {
			console.log(inputFiles);
			inputFilesHandler(inputFiles);
		}
	}
</script>

<!-- Hidden file input used to open the camera on mobile -->
<input
	id="camera-input"
	type="file"
	accept="image/*"
	capture="environment"
	on:change={handleFileChange}
	style="display: none;"
/>

<Dropdown
	bind:show
	on:change={(e) => {
		if (e.detail === false) {
			onClose();
		}
	}}
>
	<Tooltip content={$i18n.t('More')}>
		<slot />
	</Tooltip>

	<div slot="content">
		<DropdownMenu.Content
			class="w-full max-w-[240px] rounded-xl px-1 py-1 border border-gray-300/30 dark:border-gray-700/50 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-sm"
			sideOffset={10}
			alignOffset={-8}
			side="top"
			align="start"
			transition={flyAndScale}
		>
			{#if Object.keys(tools).length > 0}
				<div class="  max-h-28 overflow-y-auto scrollbar-hidden">
					{#each Object.keys(tools) as toolId}
						<button
							class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer rounded-xl"
							on:click={() => {
								tools[toolId].enabled = !tools[toolId].enabled;
							}}
						>
							<div class="flex-1 truncate">
								<Tooltip
									content={tools[toolId]?.description ?? ''}
									placement="top-start"
									className="flex flex-1 gap-2 items-center"
								>
									<div class="shrink-0">
										<WrenchSolid />
									</div>

									<div class=" truncate">{tools[toolId].name}</div>
								</Tooltip>
							</div>

							<div class=" shrink-0">
								<Switch
									state={tools[toolId].enabled}
									on:change={async (e) => {
										const state = e.detail;
										await tick();
										if (state) {
											selectedToolIds = [...selectedToolIds, toolId];
										} else {
											selectedToolIds = selectedToolIds.filter((id) => id !== toolId);
										}
									}}
								/>
							</div>
						</button>
					{/each}
				</div>

				<hr class="border-black/5 dark:border-white/5 my-1" />
			{/if}

			<Tooltip
				content={!fileUploadEnabled ? $i18n.t('You do not have permission to upload files') : ''}
				className="w-full"
			>
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm  font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800  rounded-xl {!fileUploadEnabled
						? 'opacity-50'
						: ''}"
					on:click={() => {
						if (fileUploadEnabled) {
							if (!detectMobile()) {
								screenCaptureHandler();
							} else {
								const cameraInputElement = document.getElementById('camera-input');

								if (cameraInputElement) {
									cameraInputElement.click();
								}
							}
						}
					}}
				>
					<CameraSolid />
					<div class=" line-clamp-1">{$i18n.t('Capture')}</div>
				</DropdownMenu.Item>
			</Tooltip>

			<Tooltip
				content={!fileUploadEnabled ? $i18n.t('You do not have permission to upload files') : ''}
				className="w-full"
			>
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl {!fileUploadEnabled
						? 'opacity-50'
						: ''}"
					on:click={() => {
						if (fileUploadEnabled) {
							uploadFilesHandler();
						}
					}}
				>
					<DocumentArrowUpSolid />
					<div class="line-clamp-1">{$i18n.t('Upload Files')}</div>
				</DropdownMenu.Item>
			</Tooltip>

			{#if $config?.features?.enable_google_drive_integration}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl"
					on:click={() => {
						uploadGoogleDriveHandler();
					}}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87.3 78" class="w-5 h-5">
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
					<div class="line-clamp-1">{$i18n.t('Google Drive')}</div>
				</DropdownMenu.Item>
			{/if}

			{#if $config?.features?.enable_onedrive_integration}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl"
					on:click={() => {
						uploadOneDriveHandler();
					}}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="w-5 h-5" fill="none">
						<mask
							id="mask0_87_7796"
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
						<g mask="url(#mask0_87_7796)">
							<path
								d="M7.83017 26.0001C5.37824 26.0001 3.18957 24.8966 1.75391 23.1691L18.0429 16.3335L30.7089 23.4647C29.5926 24.9211 27.9066 26.0001 26.0004 25.9915C23.1254 26.0001 12.0629 26.0001 7.83017 26.0001Z"
								fill="url(#paint0_linear_87_7796)"
							/>
							<path
								d="M25.5785 13.3149L18.043 16.3334L30.709 23.4647C31.5199 22.4065 32.0004 21.0916 32.0004 19.6669C32.0004 16.1857 29.1321 13.3605 25.5833 13.3337C25.5817 13.3274 25.5801 13.3212 25.5785 13.3149Z"
								fill="url(#paint1_linear_87_7796)"
							/>
							<path
								d="M7.06445 10.7028L18.0423 16.3333L25.5779 13.3148C24.5051 9.11261 20.6237 6 15.9997 6C12.4141 6 9.27508 7.87166 7.54586 10.6716C7.3841 10.6773 7.22358 10.6877 7.06445 10.7028Z"
								fill="url(#paint2_linear_87_7796)"
							/>
							<path
								d="M1.7535 23.1687L18.0425 16.3331L7.06471 10.7026C3.09947 11.0792 0 14.3517 0 18.3331C0 20.1665 0.657197 21.8495 1.7535 23.1687Z"
								fill="url(#paint3_linear_87_7796)"
							/>
						</g>
						<defs>
							<linearGradient
								id="paint0_linear_87_7796"
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
								id="paint1_linear_87_7796"
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
								id="paint2_linear_87_7796"
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
								id="paint3_linear_87_7796"
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
					<div class="line-clamp-1">{$i18n.t('OneDrive')}</div>
				</DropdownMenu.Item>
			{/if}

			{#if $config?.features?.enable_sharepoint_integration}
				<DropdownMenu.Item
					class="flex gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-xl"
					on:click={() => {
						uploadSharePointHandler();
					}}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" class="w-5 h-5" fill="none">
						<circle cx="16" cy="14" r="10" fill="#036C70" />
						<circle cx="10" cy="22" r="8" fill="#1A9BA1" />
						<circle cx="20" cy="24" r="6" fill="#37C6D0" />
					</svg>
					<div class="line-clamp-1">{$i18n.t('SharePoint')}</div>
				</DropdownMenu.Item>
			{/if}

			<!-- Feature toggles: Web Search, Image, Gmail, Calendar -->
			{#if ($config?.features?.enable_web_search && ($user?.role === 'admin' || $user?.permissions?.features?.web_search) && isCapAvailable('web_search')) || ($config?.features?.enable_image_generation && ($user?.role === 'admin' || $user?.permissions?.features?.image_generation) && isCapAvailable('image_generation')) || shouldShowGoogleRow('gmail') || shouldShowGoogleRow('calendar') || shouldShowGoogleRow('drive')}
				<hr class="border-black/5 dark:border-white/5 my-1" />

				{#if $config?.features?.enable_web_search && ($user?.role === 'admin' || $user?.permissions?.features?.web_search) && isCapAvailable('web_search')}
					<button
						class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800"
						on:click={() => {
							webSearchEnabled = !webSearchEnabled;
						}}
					>
						<div class="flex gap-2 items-center flex-1 min-w-0">
							<div class="shrink-0">
								<GlobeAltSolid />
							</div>
							<div class="truncate">{$i18n.t('Web Search')}</div>
						</div>
						<!-- svelte-ignore a11y-click-events-have-key-events -->
						<div class="shrink-0" on:click|stopPropagation>
							<Switch
								state={webSearchEnabled || ($settings?.webSearch ?? false) === 'always'}
								on:change={(e) => {
									webSearchEnabled = e.detail;
								}}
							/>
						</div>
					</button>
				{/if}

				{#if $config?.features?.enable_image_generation && ($user?.role === 'admin' || $user?.permissions?.features?.image_generation) && isCapAvailable('image_generation')}
					{#if imageConnections.length > 0}
						<div class="relative">
							<button
								class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800"
								type="button"
								on:click={() => {
									showImageSubmenu = !showImageSubmenu;
									if (showImageSubmenu) showGoogleSubmenu = false;
								}}
							>
								<div class="flex gap-2 items-center flex-1 min-w-0">
									<div class="shrink-0">
										<PhotoSolid />
									</div>
									<div class="truncate">{$i18n.t('Image Generation')}</div>
									{#if selectedImageConnectionIdx !== null}
										<div class="ml-auto shrink-0 w-2 h-2 rounded-full bg-blue-500"></div>
									{/if}
								</div>
								<div class="shrink-0 text-gray-400">
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
										<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
									</svg>
								</div>
							</button>

							{#if showImageSubmenu}
								<div
									class="absolute left-full top-0 ml-1 min-w-[180px] max-w-[240px] rounded-xl px-1 py-1 border border-gray-300/30 dark:border-gray-700/50 z-[60] bg-white dark:bg-gray-850 dark:text-white shadow-lg"
								>
									<button
										class="flex w-full items-center gap-2 px-3 py-1.5 text-sm rounded-lg cursor-pointer {selectedImageConnectionIdx === null ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-50 dark:hover:bg-gray-800'}"
										type="button"
										on:click={() => {
											selectedImageConnectionIdx = null;
											imageGenerationEnabled = false;
											showImageSubmenu = false;
										}}
									>
										<span class="truncate">{$i18n.t('Disabled')}</span>
									</button>
									{#each imageConnections as conn}
										<Tooltip
											content={getImageConnectionTooltip(conn)}
											placement="right"
											className="w-full"
										>
											<button
												class="flex w-full items-center gap-2 px-3 py-1.5 text-sm rounded-lg cursor-pointer {selectedImageConnectionIdx === conn.idx ? 'bg-gray-100 dark:bg-gray-800' : 'hover:bg-gray-50 dark:hover:bg-gray-800'}"
												type="button"
												on:click={() => {
													selectedImageConnectionIdx = conn.idx;
													imageGenerationEnabled = true;
													showImageSubmenu = false;
												}}
											>
												<span class="text-xs font-medium text-blue-600 dark:text-blue-400 shrink-0">{conn.engine}</span>
												<span class="truncate">{conn.name}</span>
											</button>
										</Tooltip>
									{/each}
								</div>
							{/if}
						</div>
					{:else}
						<button
							class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800"
							on:click={() => {
								imageGenerationEnabled = !imageGenerationEnabled;
							}}
						>
							<div class="flex gap-2 items-center flex-1 min-w-0">
								<div class="shrink-0">
									<PhotoSolid />
								</div>
								<div class="truncate">{$i18n.t('Image')}</div>
							</div>
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<div class="shrink-0" on:click|stopPropagation>
								<Switch
									state={imageGenerationEnabled}
									on:change={(e) => {
										imageGenerationEnabled = e.detail;
									}}
								/>
							</div>
						</button>
					{/if}
				{/if}

				{#if shouldShowGoogleRow('gmail') || shouldShowGoogleRow('calendar') || shouldShowGoogleRow('drive')}
					<!-- Google Workspace — 이미지 생성과 동일한 우측 플라이아웃 서브메뉴 -->
					<div class="relative">
					<button
						class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium cursor-pointer rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800"
						type="button"
						on:click={() => {
							showGoogleSubmenu = !showGoogleSubmenu;
							if (showGoogleSubmenu) showImageSubmenu = false;
						}}
					>
						<div class="flex gap-2 items-center flex-1 min-w-0">
							<div class="shrink-0">
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
									<path d="M4.5 4.5h4v4h-4v-4zm7 0h4v4h-4v-4zm-7 7h4v4h-4v-4zm7 0h4v4h-4v-4z" />
								</svg>
							</div>
							<div class="truncate">{$i18n.t('Google Workspace')}</div>
							{#if googleActiveCount > 0}
								<div
									class="ml-1 shrink-0 min-w-4 text-center text-[10px] font-semibold leading-none text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-500/15 rounded-full px-1.5 py-1"
								>
									{googleActiveCount}
								</div>
							{/if}
						</div>
						<div class="shrink-0 text-gray-400">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="w-4 h-4"
							>
								<path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
							</svg>
						</div>
					</button>

					{#if showGoogleSubmenu}
						<div
							class="absolute left-full bottom-0 ml-1 min-w-[220px] max-w-[280px] rounded-xl px-1 py-1 border border-gray-300/30 dark:border-gray-700/50 z-[60] bg-white dark:bg-gray-850 dark:text-white shadow-lg flex flex-col"
						>
							{#if shouldShowGoogleRow('gmail')}
								{@const gmailReason = googleBlockReason('gmail')}
								<Tooltip
									content={blockTooltip(gmailReason, 'gmail')}
									placement="left"
									className="w-full"
								>
									<button
										class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium rounded-xl {gmailReason
											? 'opacity-50 cursor-not-allowed'
											: 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800'}"
										disabled={!!gmailReason}
										on:click={() => {
											if (!gmailReason) gmailEnabled = !gmailEnabled;
										}}
									>
										<div class="flex gap-2 items-center flex-1 min-w-0">
											<div class="shrink-0">
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" class="w-5 h-5">
													<path fill="#4caf50" d="M45,16.2l-5,2.75l-5,4.75L35,40h7c1.657,0,3-1.343,3-3V16.2z" />
													<path fill="#1e88e5" d="M3,16.2l3.614,1.71L13,23.7V40H6c-1.657,0-3-1.343-3-3V16.2z" />
													<polygon fill="#e53935" points="35,11.2 24,19.45 13,11.2 12,17 13,23.7 24,31.95 35,23.7 36,17" />
													<path fill="#c62828" d="M3,12.298V16.2l10,7.5V11.2L9.876,8.859C9.132,8.301,8.228,8,7.3,8h0C4.582,8,3,10.182,3,12.298z" />
													<path fill="#fbc02d" d="M45,12.298V16.2l-10,7.5V11.2l3.124-2.341C38.868,8.301,39.772,8,40.7,8h0C43.418,8,45,10.182,45,12.298z" />
												</svg>
											</div>
											<div class="truncate">{$i18n.t('Gmail')}</div>
										</div>
										<!-- svelte-ignore a11y-click-events-have-key-events -->
										<div class="shrink-0" on:click|stopPropagation>
											<Switch
												state={gmailEnabled && !gmailReason}
												disabled={!!gmailReason}
												on:change={(e) => {
													if (!gmailReason) gmailEnabled = e.detail;
												}}
											/>
										</div>
									</button>
								</Tooltip>
							{/if}

							{#if shouldShowGoogleRow('calendar')}
								{@const calendarReason = googleBlockReason('calendar')}
								<Tooltip
									content={blockTooltip(calendarReason, 'calendar')}
									placement="left"
									className="w-full"
								>
									<button
										class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium rounded-xl {calendarReason
											? 'opacity-50 cursor-not-allowed'
											: 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800'}"
										disabled={!!calendarReason}
										on:click={() => {
											if (!calendarReason) calendarEnabled = !calendarEnabled;
										}}
									>
										<div class="flex gap-2 items-center flex-1 min-w-0">
											<div class="shrink-0">
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" class="w-5 h-5">
													<rect width="22" height="22" x="13" y="13" fill="#fff" />
													<polygon fill="#1e88e5" points="25.68,20.92 26.688,22.36 28.272,21.208 28.272,29.56 30,29.56 30,18.616 28.56,18.616" />
													<path fill="#1e88e5" d="M22.943,23.745c0.625-0.574,1.013-1.37,1.013-2.249c0-1.747-1.533-3.168-3.417-3.168c-1.602,0-2.972,1.009-3.33,2.453l1.657,0.421c0.165-0.664,0.868-1.146,1.673-1.146c0.942,0,1.709,0.646,1.709,1.44c0,0.794-0.767,1.44-1.709,1.44h-0.997v1.728h0.997c1.081,0,1.993,0.751,1.993,1.64c0,0.904-0.866,1.64-1.931,1.64c-0.962,0-1.784-0.61-1.914-1.418L18,28.409c0.262,1.626,1.81,2.851,3.6,2.851c2.007,0,3.64-1.521,3.64-3.391C25.24,25.523,24.314,24.388,22.943,23.745z" />
													<polygon fill="#fbc02d" points="34,42 14,42 13,38 14,34 34,34 35,38" />
													<polygon fill="#4caf50" points="38,35 42,34 42,14 38,13 34,14 34,34" />
													<path fill="#1e88e5" d="M34,14l1-4l-1-4H9C7.343,6,6,7.343,6,9v25l4,1l4-1V14H34z" />
													<polygon fill="#e53935" points="34,34 34,42 42,34" />
													<path fill="#1565c0" d="M42,9v5H34l0-8h5C40.657,6,42,7.343,42,9z" />
													<path fill="#1565c0" d="M6,34v5c0,1.657,1.343,3,3,3h5l0-8H6z" />
												</svg>
											</div>
											<div class="truncate">{$i18n.t('Google Calendar')}</div>
										</div>
										<!-- svelte-ignore a11y-click-events-have-key-events -->
										<div class="shrink-0" on:click|stopPropagation>
											<Switch
												state={calendarEnabled && !calendarReason}
												disabled={!!calendarReason}
												on:change={(e) => {
													if (!calendarReason) calendarEnabled = e.detail;
												}}
											/>
										</div>
									</button>
								</Tooltip>
							{/if}

							{#if shouldShowGoogleRow('drive')}
								{@const driveReason = googleBlockReason('drive')}
								<Tooltip
									content={blockTooltip(driveReason, 'drive')}
									placement="left"
									className="w-full"
								>
									<button
										class="flex w-full justify-between gap-2 items-center px-3 py-2 text-sm font-medium rounded-xl {driveReason
											? 'opacity-50 cursor-not-allowed'
											: 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800'}"
										disabled={!!driveReason}
										on:click={() => {
											if (!driveReason) driveEnabled = !driveEnabled;
										}}
									>
										<div class="flex gap-2 items-center flex-1 min-w-0">
											<div class="shrink-0">
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87.3 78" class="w-5 h-5">
													<path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da" />
													<path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z" fill="#00ac47" />
													<path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z" fill="#ea4335" />
													<path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d" />
													<path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc" />
													<path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00" />
												</svg>
											</div>
											<div class="truncate">{$i18n.t('Google Drive')}</div>
										</div>
										<!-- svelte-ignore a11y-click-events-have-key-events -->
										<div class="shrink-0" on:click|stopPropagation>
											<Switch
												state={driveEnabled && !driveReason}
												disabled={!!driveReason}
												on:change={(e) => {
													if (!driveReason) driveEnabled = e.detail;
												}}
											/>
										</div>
									</button>
								</Tooltip>
							{/if}
						</div>
					{/if}
					</div>
				{/if}

				{/if}
		</DropdownMenu.Content>
	</div>
</Dropdown>
