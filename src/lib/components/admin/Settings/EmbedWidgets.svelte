<script lang="ts">
	import { onMount, getContext, createEventDispatcher } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { models } from '$lib/stores';

	import {
		getEmbedWidgets,
		createEmbedWidget,
		updateEmbedWidgetById,
		deleteEmbedWidgetById,
		type EmbedWidget,
		type EmbedWidgetForm
	} from '$lib/apis/embed-widgets';

	import { DropdownMenu } from 'bits-ui';
	import { flyAndScale } from '$lib/utils/transitions';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import PencilSquare from '$lib/components/icons/PencilSquare.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	let widgets: EmbedWidget[] = [];
	let loading = true;

	// Modal state
	let showModal = false;
	let editingWidget: EmbedWidget | null = null;

	// Form state
	let formName = '';
	let formDescription = '';
	let formModelId = '';
	let formAllowedAgents: string[] = [];
	let formSystemPrompt = '';
	let formWelcomeMessage = '';
	let formAllowedDomains = '';
	let formTheme = 'auto';
	let formPosition = 'bottom-right';
	let formMaxMessages = 0;
	let formFileUpload = true;
	let formMarkdown = true;
	let formCodeHighlight = true;
	let formWebSearch = false;
	let formIsActive = true;

	// Embed code display
	let showEmbedCode = false;
	let embedCodeWidgetId = '';
	let embedCodeWidgetName = '';

	// Delete confirm
	let showDeleteConfirm = false;
	let deletingWidgetId = '';

	// Design editor
	let showDesignModal = false;
	let designWidget: EmbedWidget | null = null;
	let designMode = 'bubble';
	let designTheme = 'auto';
	let designPosition = 'bottom-right';
	let designWelcomeMessage = '';
	let designMaxMessages = 0;
	let designFileUpload = true;
	let designMarkdown = true;
	let designCodeHighlight = true;
	let designWebSearch = false;
	// Default color values (Cloosphere design tokens)
	const COLOR_DEFAULTS = {
		primary: '#171717',
		bubbleIcon: '#ffffff',
		headerBg: '#ffffff',
		headerText: '#171717',
		background: '#ffffff',
		messageText: '#171717',
		sendButton: '#171717',
		sendButtonIcon: '#ffffff'
	};

	type ThemePreset = {
		id: string;
		name: string;
		description: string;
		// 'light' | 'dark' — Layout 탭의 기본 테마와 동기화됨
		theme: 'light' | 'dark';
		// Two swatches that visually summarize the theme on the preset chip
		swatch: [string, string];
		colors: {
			primary: string;
			bubbleIcon: string;
			headerBg: string;
			headerText: string;
			background: string;
			messageText: string;
			sendButton: string;
			sendButtonIcon: string;
		};
	};

	const THEME_PRESETS: ThemePreset[] = [
		{
			id: 'default-light',
			name: 'Light',
			description: 'Framework default — light mode, no custom colors',
			theme: 'light',
			swatch: ['#FFFFFF', '#171717'],
			// 빈 문자열 = framework 디폴트 사용
			colors: {
				primary: '',
				bubbleIcon: '',
				headerBg: '',
				headerText: '',
				background: '',
				messageText: '',
				sendButton: '',
				sendButtonIcon: ''
			}
		},
		{
			id: 'default-dark',
			name: 'Dark',
			description: 'Framework default — dark mode, no custom colors',
			theme: 'dark',
			swatch: ['#0A0A0A', '#FAFAFA'],
			colors: {
				primary: '',
				bubbleIcon: '',
				headerBg: '',
				headerText: '',
				background: '',
				messageText: '',
				sendButton: '',
				sendButtonIcon: ''
			}
		},
		{
			id: 'slate',
			name: 'Slate',
			description: 'Minimal monochrome — explicit black accents',
			theme: 'light',
			swatch: ['#171717', '#FFFFFF'],
			colors: {
				primary: '#171717',
				bubbleIcon: '#FFFFFF',
				headerBg: '#FFFFFF',
				headerText: '#171717',
				background: '#FFFFFF',
				messageText: '#171717',
				sendButton: '#171717',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'midnight',
			name: 'Midnight',
			description: 'Dark, sleek, late-night focus',
			theme: 'dark',
			swatch: ['#0F172A', '#6366F1'],
			colors: {
				primary: '#0F172A',
				bubbleIcon: '#E0E7FF',
				headerBg: '#1E293B',
				headerText: '#F8FAFC',
				background: '#0F172A',
				messageText: '#E2E8F0',
				sendButton: '#6366F1',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'ocean',
			name: 'Ocean',
			description: 'Calm corporate blue',
			theme: 'light',
			swatch: ['#0369A1', '#0EA5E9'],
			colors: {
				primary: '#0369A1',
				bubbleIcon: '#FFFFFF',
				headerBg: '#0369A1',
				headerText: '#FFFFFF',
				background: '#F0F9FF',
				messageText: '#0C4A6E',
				sendButton: '#0EA5E9',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'aurora',
			name: 'Aurora',
			description: 'Vivid violet with a pink accent',
			theme: 'light',
			swatch: ['#7C3AED', '#EC4899'],
			colors: {
				primary: '#7C3AED',
				bubbleIcon: '#FFFFFF',
				headerBg: '#7C3AED',
				headerText: '#FFFFFF',
				background: '#FAF5FF',
				messageText: '#3B0764',
				sendButton: '#EC4899',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'sunset',
			name: 'Sunset',
			description: 'Warm orange, energetic and friendly',
			theme: 'light',
			swatch: ['#EA580C', '#F59E0B'],
			colors: {
				primary: '#EA580C',
				bubbleIcon: '#FFFFFF',
				headerBg: '#EA580C',
				headerText: '#FFFFFF',
				background: '#FFF7ED',
				messageText: '#7C2D12',
				sendButton: '#F59E0B',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'forest',
			name: 'Forest',
			description: 'Natural greens, grounded and trustworthy',
			theme: 'light',
			swatch: ['#15803D', '#10B981'],
			colors: {
				primary: '#15803D',
				bubbleIcon: '#FFFFFF',
				headerBg: '#15803D',
				headerText: '#FFFFFF',
				background: '#F0FDF4',
				messageText: '#14532D',
				sendButton: '#10B981',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'rose',
			name: 'Rose',
			description: 'Elegant rose with rich text',
			theme: 'light',
			swatch: ['#9F1239', '#F43F5E'],
			colors: {
				primary: '#9F1239',
				bubbleIcon: '#FFFFFF',
				headerBg: '#9F1239',
				headerText: '#FFFFFF',
				background: '#FFF1F2',
				messageText: '#4C0519',
				sendButton: '#F43F5E',
				sendButtonIcon: '#FFFFFF'
			}
		},
		{
			id: 'cyberpunk',
			name: 'Cyberpunk',
			description: 'Dark canvas with neon cyan accents',
			theme: 'dark',
			swatch: ['#18181B', '#22D3EE'],
			colors: {
				primary: '#18181B',
				bubbleIcon: '#22D3EE',
				headerBg: '#18181B',
				headerText: '#22D3EE',
				background: '#09090B',
				messageText: '#E4E4E7',
				sendButton: '#22D3EE',
				sendButtonIcon: '#0F172A'
			}
		},
		{
			id: 'ember',
			name: 'Ember',
			description: 'Warm dark canvas with candle-lit amber glow',
			theme: 'dark',
			swatch: ['#1C1917', '#F59E0B'],
			colors: {
				primary: '#292524',
				bubbleIcon: '#FBBF24',
				headerBg: '#292524',
				headerText: '#FCD34D',
				background: '#1C1917',
				messageText: '#E7E5E4',
				sendButton: '#F59E0B',
				sendButtonIcon: '#1C1917'
			}
		},
		{
			id: 'mono',
			name: 'Mono',
			description: 'Pure black on white — print magazine vibes',
			theme: 'light',
			swatch: ['#000000', '#FFFFFF'],
			colors: {
				primary: '#000000',
				bubbleIcon: '#FFFFFF',
				headerBg: '#FFFFFF',
				headerText: '#000000',
				background: '#FFFFFF',
				messageText: '#000000',
				sendButton: '#000000',
				sendButtonIcon: '#FFFFFF'
			}
		}
	];

	const applyThemePreset = (preset: ThemePreset) => {
		// 기본 테마(light/dark)도 함께 적용 — 색상과 일관성 유지
		designTheme = preset.theme;
		designPrimaryColor = preset.colors.primary;
		designBubbleIconColor = preset.colors.bubbleIcon;
		designHeaderColor = preset.colors.headerBg;
		designHeaderTextColor = preset.colors.headerText;
		designBackgroundColor = preset.colors.background;
		designMessageTextColor = preset.colors.messageText;
		designSendButtonColor = preset.colors.sendButton;
		designSendButtonIconColor = preset.colors.sendButtonIcon;
		// 미리보기 새로고침
		setTimeout(() => loadPreview(), 0);
	};

	let designPrimaryColor = COLOR_DEFAULTS.primary;
	let designBubbleIconColor = '';
	let designHeaderColor = '';
	let designHeaderTextColor = '';
	let designMessageTextColor = '';
	let designBackgroundColor = '';
	let designSendButtonColor = '';
	let designSendButtonIconColor = '';
	let designSendButtonIconUrl = '';
	let designBubbleIconUrl = '';
	let designWidth = '';
	let designHeight = '';
	let designShowHeader = true;
	let designShowHeaderCloseButton = true;
	let designBubbleOpenStyle: 'popup' | 'side-right' | 'side-left' | 'side-bottom' = 'popup';
	let designBubbleDraggable = false;
	let designBubbleResizable = false;
	let designBubbleSize = 56;
	let designHeaderText = '';

	// ---- Auth Mode ----
	type AuthMode = 'login' | 'sso' | 'guest';
	let designAuthMode: AuthMode = 'login';

	// ---- SSO ----
	type SsoProviderKey = 'microsoft' | 'google' | 'github' | 'oidc';
	type SsoRole = 'pending' | 'user' | 'admin';
	// Svelte 템플릿 파서는 `as Type` 캐스트를 거절하므로
	// 옵션 배열을 타입 안전하게 미리 선언해 캐스트 없이 참조한다.
	const SSO_PROVIDER_OPTIONS: Array<{ key: SsoProviderKey; label: string }> = [
		{ key: 'microsoft', label: 'Microsoft Entra ID' },
		{ key: 'google', label: 'Google' },
		{ key: 'github', label: 'GitHub' },
		{ key: 'oidc', label: 'Generic OIDC' }
	];
	let designSsoEnabled = false;
	let designSsoProviders: SsoProviderKey[] = [];
	let designSsoAutoSignup = true;
	let designSsoDefaultRole: SsoRole = 'user';
	// Microsoft options
	let designSsoMicrosoftTenantId = '';
	let designSsoMicrosoftAudiences = ''; // 콤마/공백 구분
	// Google options
	let designSsoGoogleAudiences = '';
	// OIDC options
	let designSsoOidcIssuers = '';
	let designSsoOidcAudiences = '';
	let designShowAvatar = true;
	let designAvatarUrl = '';
	let designBotName = '';

	// ---- Guest ----
	let designGuestEnabled = false;
	let designGuestCollectInfo = true;
	let designGuestRequiredFields: string[] = ['name'];
	let designGuestOptionalFields: string[] = ['email'];
	let designGuestAutoProcceed = false;
	let designGuestJwtExpiresIn = '24h';

	// 편집 모달 오픈 시점의 auth 탭 스냅샷. 저장 시 스냅샷과 일치하면
	// sso/guest 블록을 기존 config 로부터 그대로 보존한다 — 인증 탭을
	// 건드리지 않은 저장이 guest.enabled=true 를 덮어쓰는 사고 방지.
	let authInitialSnapshot = '';
	const captureAuthSnapshot = (): string =>
		JSON.stringify([
			designAuthMode,
			[...designSsoProviders].sort(),
			designSsoAutoSignup,
			designSsoDefaultRole,
			designSsoMicrosoftTenantId,
			designSsoMicrosoftAudiences,
			designSsoGoogleAudiences,
			designSsoOidcIssuers,
			designSsoOidcAudiences,
			designGuestCollectInfo,
			[...designGuestRequiredFields].sort(),
			[...designGuestOptionalFields].sort(),
			designGuestAutoProcceed,
			designGuestJwtExpiresIn
		]);

	type ModelListItem = {
		id: string;
		name: string;
		type: 'agent' | 'flow' | 'model';
		image: string;
	};

	const getModelType = (m: any): 'agent' | 'flow' | 'model' => {
		if (m.owned_by === 'flow' || m.owned_by === 'agent_flow') return 'flow';
		if (m.info?.base_model_id && m.info?.base_model_id !== '') return 'agent';
		return 'model';
	};

	const typeSort = { agent: 0, flow: 1, model: 2 };
	const typeLabel: Record<string, string> = { agent: 'Agent', flow: 'Flow', model: 'Model' };
	const typeBadgeClass: Record<string, string> = {
		agent: 'bg-blue-500/15 text-blue-600 dark:text-blue-400',
		flow: 'bg-purple-500/15 text-purple-600 dark:text-purple-400',
		model: 'bg-gray-500/15 text-gray-600 dark:text-gray-400'
	};

	$: modelListItems = ($models ?? [])
		.filter((m) => m.id && m.name && !(m.info?.meta?.hidden ?? false))
		.map((m) => ({
			id: m.id,
			name: m.name,
			type: getModelType(m),
			image: m.info?.meta?.profile_image_url || ''
		}))
		.sort((a, b) => typeSort[a.type] - typeSort[b.type] || a.name.localeCompare(b.name)) as ModelListItem[];

	let modelSearchValue = '';
	let showModelDropdown = false;

	$: filteredModelList = modelSearchValue.trim()
		? modelListItems.filter(
				(m) =>
					m.name.toLowerCase().includes(modelSearchValue.toLowerCase()) ||
					m.id.toLowerCase().includes(modelSearchValue.toLowerCase())
			)
		: modelListItems;

	$: selectedModelItem = modelListItems.find((m) => m.id === formModelId);

	$: themeItems = [
		{ value: 'auto', label: $i18n.t('Auto') },
		{ value: 'light', label: $i18n.t('Light') },
		{ value: 'dark', label: $i18n.t('Dark') }
	];

	$: positionItems = [
		{ value: 'bottom-right', label: $i18n.t('Bottom Right') },
		{ value: 'bottom-left', label: $i18n.t('Bottom Left') }
	];

	$: bubbleOpenStyleItems = [
		{ value: 'popup', label: $i18n.t('Popup (above bubble)') },
		{ value: 'side-right', label: $i18n.t('Side Panel (Right)') },
		{ value: 'side-left', label: $i18n.t('Side Panel (Left)') },
		{ value: 'side-bottom', label: $i18n.t('Side Panel (Bottom)') }
	];

	$: modeItems = [
		{ value: 'bubble', label: $i18n.t('Bubble') },
		{ value: 'side-right', label: $i18n.t('Side Panel (Right)') },
		{ value: 'side-left', label: $i18n.t('Side Panel (Left)') },
		{ value: 'side-bottom', label: $i18n.t('Side Panel (Bottom)') },
		{ value: 'inline', label: $i18n.t('Inline') },
		{ value: 'fullscreen', label: $i18n.t('Fullscreen') }
	];

	const loadWidgets = async () => {
		loading = true;
		try {
			widgets = await getEmbedWidgets(localStorage.token);
		} catch (e) {
			toast.error(e as string);
		}
		loading = false;
	};

	const toggleAllowedAgent = (id: string, checked: boolean) => {
		if (checked) {
			if (!formAllowedAgents.includes(id)) {
				formAllowedAgents = [...formAllowedAgents, id];
			}
		} else {
			formAllowedAgents = formAllowedAgents.filter((a) => a !== id);
		}
	};

	const resetForm = () => {
		formName = '';
		formDescription = '';
		formModelId = '';
		formAllowedAgents = [];
		formSystemPrompt = '';
		formWelcomeMessage = '';
		formAllowedDomains = '';
		formTheme = 'auto';
		formPosition = 'bottom-right';
		formMaxMessages = 0;
		formFileUpload = true;
		formMarkdown = true;
		formCodeHighlight = true;
		formWebSearch = false;
		formIsActive = true;
	};

	const openCreateModal = () => {
		editingWidget = null;
		resetForm();
		showModal = true;
	};

	const openEditModal = (widget: EmbedWidget) => {
		editingWidget = widget;
		formName = widget.name;
		formDescription = widget.description || '';
		formModelId = widget.model_id;
		formSystemPrompt = widget.system_prompt || '';
		const cfg = (widget.config || {}) as Record<string, unknown>;
		formAllowedAgents = Array.isArray(cfg.allowed_agents)
			? ((cfg.allowed_agents as string[]).filter((a) => a && a !== widget.model_id))
			: [];
		formWelcomeMessage = (cfg.welcome_message as string) || '';
		formAllowedDomains = ((cfg.allowed_domains as string[]) || []).join(', ');
		formTheme = (cfg.theme as string) || 'auto';
		formPosition = (cfg.position as string) || 'bottom-right';
		formMaxMessages = (cfg.max_messages_per_session as number) || 0;
		const features = (cfg.features || {}) as Record<string, boolean>;
		formFileUpload = features.file_upload !== false;
		formMarkdown = features.markdown !== false;
		formCodeHighlight = features.code_highlight !== false;
		formWebSearch = features.web_search === true;
		formIsActive = widget.is_active !== false;
		showModal = true;
	};

	const buildFormData = (): EmbedWidgetForm => {
		// 편집 모달은 기본 속성(name/description/model/features/...)만 다룬다.
		// 기존 config 의 sso/guest/mode/colors 등은 이 모달에서 노출되지 않으므로
		// 반드시 보존해야 한다 — 새 payload 로 전체 config 를 교체하지 않는다.
		const existingConfig = (editingWidget?.config || {}) as Record<string, unknown>;
		return {
			name: formName.trim(),
			description: formDescription.trim() || undefined,
			model_id: formModelId,
			system_prompt: formSystemPrompt.trim() || undefined,
			config: {
				...existingConfig,
				theme: formTheme,
				position: formPosition,
				allowed_agents: formAllowedAgents.filter((a) => a && a !== formModelId),
				allowed_domains: formAllowedDomains
					.split(',')
					.map((d) => d.trim())
					.filter(Boolean),
				features: {
					file_upload: formFileUpload,
					markdown: formMarkdown,
					code_highlight: formCodeHighlight,
					web_search: formWebSearch
				},
				max_messages_per_session: formMaxMessages,
				welcome_message: formWelcomeMessage.trim()
			},
			is_active: formIsActive
		};
	};

	const submitHandler = async () => {
		if (!formName.trim()) {
			toast.error($i18n.t('Widget name is required'));
			return;
		}
		if (!formModelId) {
			toast.error($i18n.t('Please select a model'));
			return;
		}

		try {
			const data = buildFormData();
			if (editingWidget) {
				await updateEmbedWidgetById(localStorage.token, editingWidget.id, data);
				toast.success($i18n.t('Widget updated successfully'));
			} else {
				const created = await createEmbedWidget(localStorage.token, data);
				if (created) {
					toast.success($i18n.t('Widget created successfully'));
					showModal = false;
					await loadWidgets();
					openEmbedCode(created.id, created.name);
					return;
				}
			}
			showModal = false;
			await loadWidgets();
		} catch (e) {
			toast.error(e as string);
		}
	};

	const confirmDelete = (id: string) => {
		deletingWidgetId = id;
		showDeleteConfirm = true;
	};

	const deleteWidget = async () => {
		try {
			await deleteEmbedWidgetById(localStorage.token, deletingWidgetId);
			toast.success($i18n.t('Widget deleted successfully'));
			showDeleteConfirm = false;
			await loadWidgets();
		} catch (e) {
			toast.error(e as string);
		}
	};

	const openEmbedCode = (id: string, name: string) => {
		embedCodeWidgetId = id;
		embedCodeWidgetName = name;
		showEmbedCode = true;
	};

	const getEmbedSnippet = (widgetId: string) => {
		const baseUrl = window.location.origin;
		return `<script src="${baseUrl}/static/embed/embed.js" data-widget-id="${widgetId}"><\/script>`;
	};

	const openDesignModal = (widget: EmbedWidget) => {
		designWidget = widget;
		const cfg = (widget.config || {}) as Record<string, unknown>;
		designMode = (cfg.mode as string) || 'bubble';
		designTheme = (cfg.theme as string) || 'auto';
		designPosition = (cfg.position as string) || 'bottom-right';
		designWelcomeMessage = (cfg.welcome_message as string) || '';
		designMaxMessages = (cfg.max_messages_per_session as number) || 0;
		const features = (cfg.features || {}) as Record<string, boolean>;
		designFileUpload = features.file_upload !== false;
		designMarkdown = features.markdown !== false;
		designCodeHighlight = features.code_highlight !== false;
		designWebSearch = features.web_search === true;
		designPrimaryColor = (cfg.primary_color as string) || '#171717';
		designBubbleIconColor = (cfg.bubble_icon_color as string) || '';
		designHeaderColor = (cfg.header_color as string) || '';
		designHeaderTextColor = (cfg.header_text_color as string) || '';
		designMessageTextColor = (cfg.message_text_color as string) || '';
		designBackgroundColor = (cfg.background_color as string) || '';
		designSendButtonColor = (cfg.send_button_color as string) || '';
		designSendButtonIconColor = (cfg.send_button_icon_color as string) || '';
		designSendButtonIconUrl = (cfg.send_button_icon_url as string) || '';
		designBubbleIconUrl = (cfg.bubble_icon_url as string) || '';
		designWidth = (cfg.width as string) || '';
		designHeight = (cfg.height as string) || '';
		designShowHeader = cfg.show_header !== false;
		designShowHeaderCloseButton = cfg.show_header_close_button !== false;
		designBubbleOpenStyle = (cfg.bubble_open_style as 'popup' | 'side-right' | 'side-left' | 'side-bottom') || 'popup';
		designBubbleDraggable = cfg.bubble_draggable === true;
		designBubbleResizable = cfg.bubble_resizable === true;
		designBubbleSize =
			typeof cfg.bubble_size === 'number' && cfg.bubble_size > 0 ? cfg.bubble_size : 56;
		designHeaderText = (cfg.header_text as string) || '';
		designShowAvatar = cfg.show_avatar !== false;
		designAvatarUrl = (cfg.avatar_url as string) || '';
		designBotName = (cfg.bot_name as string) || '';

		// SSO config load
		const ssoCfg = (cfg.sso || {}) as Record<string, any>;
		designSsoEnabled = ssoCfg.enabled === true;

		// Guest config load
		const guestCfg_ = (cfg.guest || {}) as Record<string, any>;
		const guestEnabled_ = guestCfg_.enabled === true;

		// Auth mode 결정: SSO > Guest > Login
		designAuthMode = designSsoEnabled ? 'sso' : guestEnabled_ ? 'guest' : 'login';
		designSsoProviders = Array.isArray(ssoCfg.providers)
			? (ssoCfg.providers.filter((p: string) =>
					['microsoft', 'google', 'github', 'oidc'].includes(p)
				) as SsoProviderKey[])
			: [];
		designSsoAutoSignup = ssoCfg.auto_signup !== false;
		const role = ssoCfg.default_role;
		designSsoDefaultRole = role === 'pending' || role === 'admin' ? role : 'user';

		const provOpts = (ssoCfg.provider_options || {}) as Record<string, any>;
		const ms = provOpts.microsoft || {};
		designSsoMicrosoftTenantId = (ms.tenant_id as string) || '';
		designSsoMicrosoftAudiences = Array.isArray(ms.trusted_audiences)
			? ms.trusted_audiences.join(', ')
			: '';
		const goog = provOpts.google || {};
		designSsoGoogleAudiences = Array.isArray(goog.trusted_audiences)
			? goog.trusted_audiences.join(', ')
			: '';
		const oidc = provOpts.oidc || {};
		designSsoOidcIssuers = Array.isArray(oidc.trusted_issuers)
			? oidc.trusted_issuers.join(', ')
			: '';
		designSsoOidcAudiences = Array.isArray(oidc.trusted_audiences)
			? oidc.trusted_audiences.join(', ')
			: '';

		// Guest config load
		const guestCfg = (cfg.guest || {}) as Record<string, any>;
		designGuestEnabled = guestEnabled_;
		designGuestCollectInfo = guestCfg.collect_info !== false;
		designGuestRequiredFields = Array.isArray(guestCfg.required_fields) ? guestCfg.required_fields : ['name'];
		designGuestOptionalFields = Array.isArray(guestCfg.optional_fields) ? guestCfg.optional_fields : ['email'];
		designGuestAutoProcceed = guestCfg.auto_proceed === true;
		designGuestJwtExpiresIn = (guestCfg.jwt_expires_in as string) || '24h';

		// 모든 auth 상태 로드 완료 후 스냅샷 저장. saveDesign 에서 이 값과
		// 비교해 인증 탭이 실제로 수정됐는지 판별한다.
		authInitialSnapshot = captureAuthSnapshot();

		showDesignModal = true;
		// defer so designWidget is set before building URL
		setTimeout(() => loadPreview(), 0);
	};

	// 콤마/공백/줄바꿈 구분 문자열 → 배열
	const parseList = (s: string): string[] =>
		s
			.split(/[\s,]+/)
			.map((x) => x.trim())
			.filter((x) => x.length > 0);

	// SSO 폼 → config JSON
	const buildSsoConfig = () => {
		// authMode가 sso가 아니면 비활성화
		if (designAuthMode !== 'sso') {
			return { enabled: false };
		}

		const providerOptions: Record<string, any> = {};
		if (designSsoProviders.includes('microsoft')) {
			const ms: Record<string, any> = {};
			if (designSsoMicrosoftTenantId.trim()) ms.tenant_id = designSsoMicrosoftTenantId.trim();
			const audList = parseList(designSsoMicrosoftAudiences);
			if (audList.length > 0) ms.trusted_audiences = audList;
			if (Object.keys(ms).length > 0) providerOptions.microsoft = ms;
		}
		if (designSsoProviders.includes('google')) {
			const goog: Record<string, any> = {};
			const audList = parseList(designSsoGoogleAudiences);
			if (audList.length > 0) goog.trusted_audiences = audList;
			if (Object.keys(goog).length > 0) providerOptions.google = goog;
		}
		if (designSsoProviders.includes('oidc')) {
			const oidc: Record<string, any> = {};
			const issuers = parseList(designSsoOidcIssuers);
			if (issuers.length > 0) oidc.trusted_issuers = issuers;
			const auds = parseList(designSsoOidcAudiences);
			if (auds.length > 0) oidc.trusted_audiences = auds;
			if (Object.keys(oidc).length > 0) providerOptions.oidc = oidc;
		}
		// github은 옵션이 없음

		const out: Record<string, any> = {
			enabled: true,
			providers: designSsoProviders,
			auto_signup: designSsoAutoSignup,
			default_role: designSsoDefaultRole,
			match_by: 'email'
		};
		if (Object.keys(providerOptions).length > 0) {
			out.provider_options = providerOptions;
		}
		return out;
	};

	const buildGuestConfig = () => {
		// authMode가 guest가 아니면 비활성화
		if (designAuthMode !== 'guest') {
			return { enabled: false };
		}
		return {
			enabled: true,
			collect_info: designGuestCollectInfo,
			required_fields: designGuestRequiredFields,
			optional_fields: designGuestOptionalFields,
			auto_proceed: designGuestAutoProcceed,
			jwt_expires_in: designGuestJwtExpiresIn || '24h'
		};
	};

	const toggleSsoProvider = (key: SsoProviderKey) => {
		if (designSsoProviders.includes(key)) {
			designSsoProviders = designSsoProviders.filter((p) => p !== key);
		} else {
			designSsoProviders = [...designSsoProviders, key];
		}
	};

	const saveDesign = async () => {
		if (!designWidget) return;
		try {
			const existingConfig = (designWidget.config || {}) as Record<string, unknown>;
			const authChanged = captureAuthSnapshot() !== authInitialSnapshot;
			const preservedSso =
				(existingConfig.sso as Record<string, unknown> | undefined) ?? { enabled: false };
			const preservedGuest =
				(existingConfig.guest as Record<string, unknown> | undefined) ?? { enabled: false };
			const data: EmbedWidgetForm = {
				name: designWidget.name,
				description: designWidget.description || undefined,
				model_id: designWidget.model_id,
				system_prompt: designWidget.system_prompt || undefined,
				config: {
					...existingConfig,
					mode: designMode,
					theme: designTheme,
					position: designPosition,
					primary_color: designPrimaryColor || undefined,
					bubble_icon_color: designBubbleIconColor || undefined,
					header_color: designHeaderColor || undefined,
					header_text_color: designHeaderTextColor || undefined,
					message_text_color: designMessageTextColor || undefined,
					background_color: designBackgroundColor || undefined,
					send_button_color: designSendButtonColor || undefined,
					send_button_icon_color: designSendButtonIconColor || undefined,
					send_button_icon_url: designSendButtonIconUrl || undefined,
					bubble_icon_url: designBubbleIconUrl || undefined,
					width: designWidth || undefined,
					height: designHeight || undefined,
					show_header: designShowHeader,
					show_header_close_button: designShowHeaderCloseButton,
					bubble_open_style: designBubbleOpenStyle,
					bubble_draggable: designBubbleDraggable,
					bubble_resizable: designBubbleResizable,
					bubble_size: designBubbleSize,
					sso: authChanged ? buildSsoConfig() : preservedSso,
					guest: authChanged ? buildGuestConfig() : preservedGuest,
					header_text: designHeaderText || undefined,
					show_avatar: designShowAvatar,
					avatar_url: designAvatarUrl || undefined,
					bot_name: designBotName || undefined,
					welcome_message: designWelcomeMessage.trim(),
					max_messages_per_session: designMaxMessages,
					features: {
						file_upload: designFileUpload,
						markdown: designMarkdown,
						code_highlight: designCodeHighlight,
						web_search: designWebSearch
					}
				},
				is_active: designWidget.is_active !== false
			};
			await updateEmbedWidgetById(localStorage.token, designWidget.id, data);
			toast.success($i18n.t('Design saved successfully'));
			showDesignModal = false;
			await loadWidgets();
		} catch (e) {
			toast.error(e as string);
		}
	};

	let designPreviewUrl = '';
	let designTab = 'layout';
	let bubbleIconInput: HTMLInputElement;

	// Preset bubble icons (inline SVG data URIs)
	const BUBBLE_ICON_PRESETS = [
		{
			id: 'chat',
			label: 'Chat',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 0 1-3.476.383.39.39 0 0 0-.297.17l-2.755 4.133a.75.75 0 0 1-1.248 0l-2.755-4.133a.39.39 0 0 0-.297-.17 48.9 48.9 0 0 1-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'sparkles',
			label: 'Sparkles',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M9 4.5a.75.75 0 0 1 .721.544l.813 2.846a3.75 3.75 0 0 0 2.576 2.576l2.846.813a.75.75 0 0 1 0 1.442l-2.846.813a3.75 3.75 0 0 0-2.576 2.576l-.813 2.846a.75.75 0 0 1-1.442 0l-.813-2.846a3.75 3.75 0 0 0-2.576-2.576l-2.846-.813a.75.75 0 0 1 0-1.442l2.846-.813A3.75 3.75 0 0 0 7.466 7.89l.813-2.846A.75.75 0 0 1 9 4.5ZM18 1.5a.75.75 0 0 1 .728.568l.258 1.036c.236.94.97 1.674 1.91 1.91l1.036.258a.75.75 0 0 1 0 1.456l-1.036.258c-.94.236-1.674.97-1.91 1.91l-.258 1.036a.75.75 0 0 1-1.456 0l-.258-1.036a2.625 2.625 0 0 0-1.91-1.91l-1.036-.258a.75.75 0 0 1 0-1.456l1.036-.258a2.625 2.625 0 0 0 1.91-1.91l.258-1.036A.75.75 0 0 1 18 1.5Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'message',
			label: 'Message',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M5.337 21.718a6.707 6.707 0 0 1-.533-.074.75.75 0 0 1-.44-1.223 3.73 3.73 0 0 0 .814-1.686c.023-.115-.022-.317-.254-.543C3.274 16.587 2.25 14.41 2.25 12c0-5.03 4.428-9 9.75-9s9.75 3.97 9.75 9c0 5.03-4.428 9-9.75 9-.833 0-1.643-.097-2.417-.279a6.721 6.721 0 0 1-4.246.997Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'robot',
			label: 'Robot',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M12 2.25a.75.75 0 0 1 .75.75v.75h2.25a3 3 0 0 1 3 3v.75h.75a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-13.5a3 3 0 0 1-3-3v-6a3 3 0 0 1 3-3h.75v-.75a3 3 0 0 1 3-3h2.25V3a.75.75 0 0 1 .75-.75ZM9 13.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Zm6 0a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'headset',
			label: 'Support',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75v3.75a3 3 0 0 0 3 3h1.5a1.5 1.5 0 0 0 1.5-1.5v-4.5a1.5 1.5 0 0 0-1.5-1.5H3.806a8.25 8.25 0 0 1 16.388 0H17.25a1.5 1.5 0 0 0-1.5 1.5v4.5a1.5 1.5 0 0 0 1.5 1.5h1.232a3.001 3.001 0 0 1-2.982 2.625H13.5a1.5 1.5 0 0 0 0 3h2a6.001 6.001 0 0 0 5.978-5.625H21a.75.75 0 0 0 .75-.75V12c0-5.385-4.365-9.75-9.75-9.75Z"/></svg>'
		},
		{
			id: 'question',
			label: 'Help',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M2.25 12c0-5.385 4.365-9.75 9.75-9.75s9.75 4.365 9.75 9.75-4.365 9.75-9.75 9.75S2.25 17.385 2.25 12Zm8.706-1.442c1.146-.573 2.437.463 2.126 1.706l-.709 2.836.042-.02a.75.75 0 0 1 .67 1.34l-.04.022c-1.147.573-2.438-.463-2.127-1.706l.71-2.836-.042.02a.75.75 0 1 1-.671-1.34l.041-.022ZM12 9a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'bolt',
			label: 'Bolt',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clip-rule="evenodd"/></svg>'
		}
	];

	// Preset send button icons
	const SEND_ICON_PRESETS = [
		{
			id: 'paper-airplane-tilt',
			label: 'Paper Airplane',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor"><path d="M3.105 2.289a.75.75 0 0 0-.826.95l1.414 4.925A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.154.75.75 0 0 0 0-1.115A28.897 28.897 0 0 0 3.105 2.29Z"/></svg>'
		},
		{
			id: 'sparkles',
			label: 'Sparkles',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M9 4.5a.75.75 0 0 1 .721.544l.813 2.846a3.75 3.75 0 0 0 2.576 2.576l2.846.813a.75.75 0 0 1 0 1.442l-2.846.813a3.75 3.75 0 0 0-2.576 2.576l-.813 2.846a.75.75 0 0 1-1.442 0l-.813-2.846a3.75 3.75 0 0 0-2.576-2.576l-2.846-.813a.75.75 0 0 1 0-1.442l2.846-.813A3.75 3.75 0 0 0 7.466 7.89l.813-2.846A.75.75 0 0 1 9 4.5ZM18 1.5a.75.75 0 0 1 .728.568l.258 1.036c.236.94.97 1.674 1.91 1.91l1.036.258a.75.75 0 0 1 0 1.456l-1.036.258c-.94.236-1.674.97-1.91 1.91l-.258 1.036a.75.75 0 0 1-1.456 0l-.258-1.036a2.625 2.625 0 0 0-1.91-1.91l-1.036-.258a.75.75 0 0 1 0-1.456l1.036-.258a2.625 2.625 0 0 0 1.91-1.91l.258-1.036A.75.75 0 0 1 18 1.5Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'paper-plane',
			label: 'Paper Plane',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="M3.478 2.404a.75.75 0 0 0-.926.941l2.432 7.905H13.5a.75.75 0 0 1 0 1.5H4.984l-2.432 7.905a.75.75 0 0 0 .926.94 60.519 60.519 0 0 0 18.445-8.986.75.75 0 0 0 0-1.218A60.517 60.517 0 0 0 3.478 2.404Z"/></svg>'
		},
		{
			id: 'rocket',
			label: 'Rocket',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M9.315 7.584C12.195 3.883 16.695 1.5 21.75 1.5a.75.75 0 0 1 .75.75c0 5.056-2.383 9.555-6.084 12.436A6.75 6.75 0 0 1 9.75 22.5a.75.75 0 0 1-.75-.75v-4.131A15.838 15.838 0 0 1 6.382 15H2.25a.75.75 0 0 1-.75-.75 6.75 6.75 0 0 1 7.815-6.666ZM15 6.75a2.25 2.25 0 1 0 0 4.5 2.25 2.25 0 0 0 0-4.5Z" clip-rule="evenodd"/><path d="M5.26 17.242a.75.75 0 1 0-.897-1.203 5.243 5.243 0 0 0-2.05 5.022.75.75 0 0 0 .625.627 5.243 5.243 0 0 0 5.022-2.051.75.75 0 1 0-1.202-.897 3.744 3.744 0 0 1-3.008 1.51c0-1.23.592-2.323 1.51-3.008Z"/></svg>'
		},
		{
			id: 'star',
			label: 'Star',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M10.788 3.21c.448-1.077 1.976-1.077 2.424 0l2.082 5.007 5.404.433c1.164.093 1.636 1.545.749 2.305l-4.117 3.527 1.257 5.273c.271 1.136-.964 2.033-1.96 1.425L12 18.354 7.373 21.18c-.996.608-2.231-.29-1.96-1.425l1.257-5.273-4.117-3.527c-.887-.76-.415-2.212.749-2.305l5.404-.433 2.082-5.006Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'sparkle-single',
			label: 'Sparkle',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M12 2.25a.75.75 0 0 1 .728.568l1.37 5.487a3.75 3.75 0 0 0 2.597 2.597l5.487 1.37a.75.75 0 0 1 0 1.456l-5.487 1.37a3.75 3.75 0 0 0-2.597 2.597l-1.37 5.487a.75.75 0 0 1-1.456 0l-1.37-5.487a3.75 3.75 0 0 0-2.597-2.597l-5.487-1.37a.75.75 0 0 1 0-1.456l5.487-1.37a3.75 3.75 0 0 0 2.597-2.597l1.37-5.487A.75.75 0 0 1 12 2.25Z" clip-rule="evenodd"/></svg>'
		},
		{
			id: 'bolt',
			label: 'Bolt',
			svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path fill-rule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clip-rule="evenodd"/></svg>'
		}
	];

	const svgToDataUrl = (svg: string): string => {
		return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
	};

	const selectPresetIcon = (svg: string) => {
		designBubbleIconUrl = svgToDataUrl(svg);
	};

	const isPresetSelected = (svg: string): boolean => {
		return designBubbleIconUrl === svgToDataUrl(svg);
	};

	const selectSendPreset = (svg: string) => {
		designSendButtonIconUrl = svgToDataUrl(svg);
	};

	const isSendPresetSelected = (svg: string): boolean => {
		return designSendButtonIconUrl === svgToDataUrl(svg);
	};

	let sendIconInput: HTMLInputElement;

	const handleSendIconUpload = (e: Event) => {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;

		const reader = new FileReader();
		reader.onload = (ev) => {
			const img = new Image();
			img.src = ev.target?.result as string;
			img.onload = () => {
				const canvas = document.createElement('canvas');
				const ctx = canvas.getContext('2d');
				const SIZE = 64;
				canvas.width = SIZE;
				canvas.height = SIZE;
				const aspect = img.width / img.height;
				let dw, dh;
				if (aspect > 1) {
					dw = SIZE * aspect;
					dh = SIZE;
				} else {
					dw = SIZE;
					dh = SIZE / aspect;
				}
				const ox = (SIZE - dw) / 2;
				const oy = (SIZE - dh) / 2;
				ctx?.drawImage(img, ox, oy, dw, dh);
				designSendButtonIconUrl = canvas.toDataURL('image/png');
				input.value = '';
			};
		};
		reader.readAsDataURL(file);
	};

	const getInputValue = (e: Event): string => {
		return (e.currentTarget as HTMLInputElement).value || '';
	};

	const handleBubbleIconUpload = (e: Event) => {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;

		const reader = new FileReader();
		reader.onload = (ev) => {
			const img = new Image();
			img.src = ev.target?.result as string;
			img.onload = () => {
				const canvas = document.createElement('canvas');
				const ctx = canvas.getContext('2d');
				const SIZE = 128;
				canvas.width = SIZE;
				canvas.height = SIZE;
				const aspect = img.width / img.height;
				let dw, dh;
				if (aspect > 1) {
					dw = SIZE * aspect;
					dh = SIZE;
				} else {
					dw = SIZE;
					dh = SIZE / aspect;
				}
				const ox = (SIZE - dw) / 2;
				const oy = (SIZE - dh) / 2;
				ctx?.drawImage(img, ox, oy, dw, dh);
				designBubbleIconUrl = canvas.toDataURL('image/png');
				input.value = '';
			};
		};
		reader.readAsDataURL(file);
	};

	$: previewSize = (() => {
		const defaults: Record<string, { w: string; h: string }> = {
			bubble: { w: '400px', h: '600px' },
			'side-right': { w: '380px', h: '100%' },
			'side-left': { w: '380px', h: '100%' },
			'side-bottom': { w: '100%', h: '320px' },
			inline: { w: '100%', h: '500px' },
			fullscreen: { w: '100%', h: '100%' }
		};
		const def = defaults[designMode] || defaults.bubble;
		const w = designWidth || def.w;
		const h = designHeight || def.h;
		return { width: w, height: h, label: `${w} × ${h}` };
	})();

	$: designTabItems = [
		{ id: 'layout', labelKey: 'Layout', href: '#layout', state: designTab === 'layout' ? 'selected' : 'default' },
		{ id: 'icons', labelKey: 'Icons', href: '#icons', state: designTab === 'icons' ? 'selected' : 'default' },
		{ id: 'header', labelKey: 'Header', href: '#header', state: designTab === 'header' ? 'selected' : 'default' },
		{ id: 'colors', labelKey: 'Colors', href: '#colors', state: designTab === 'colors' ? 'selected' : 'default' },
		{ id: 'chat', labelKey: 'Chat', href: '#chat', state: designTab === 'chat' ? 'selected' : 'default' },
		{ id: 'features', labelKey: 'Features', href: '#features', state: designTab === 'features' ? 'selected' : 'default' },
		{ id: 'auth', labelKey: 'Auth', href: '#auth', state: designTab === 'auth' ? 'selected' : 'default' }
	];

	const loadPreview = () => {
		if (!designWidget) return;
		const params = new URLSearchParams({
			token: localStorage.token,
			theme: designTheme,
			showHeader: String(designShowHeader),
			showHeaderCloseButton: String(designShowHeaderCloseButton),
			headerText: designHeaderText || designWidget.name,
			showAvatar: String(designShowAvatar),
			fileUpload: String(designFileUpload),
			t: String(Date.now())
		});
		if (designHeaderColor) params.set('headerColor', designHeaderColor);
		if (designHeaderTextColor) params.set('headerTextColor', designHeaderTextColor);
		if (designMessageTextColor) params.set('messageTextColor', designMessageTextColor);
		if (designBackgroundColor) params.set('backgroundColor', designBackgroundColor);
		if (designSendButtonColor) params.set('sendButtonColor', designSendButtonColor);
		if (designSendButtonIconColor) params.set('sendButtonIconColor', designSendButtonIconColor);
		if (designSendButtonIconUrl) params.set('sendButtonIconUrl', designSendButtonIconUrl);
		designPreviewUrl = `${window.location.origin}/embed/${designWidget.id}?${params.toString()}`;
	};

	const copyEmbedCode = async () => {
		try {
			await navigator.clipboard.writeText(getEmbedSnippet(embedCodeWidgetId));
			toast.success($i18n.t('Copied to clipboard'));
		} catch {
			toast.error($i18n.t('Failed to copy'));
		}
	};

	onMount(async () => {
		await loadWidgets();
	});
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div class="space-y-3 overflow-y-scroll scrollbar-hidden h-full pr-1.5">
		<!-- Header -->
		<div class="flex items-center justify-between">
			<div>
				<div class="font-medium">{$i18n.t('Embed Widgets')}</div>
				<div class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
					{$i18n.t('Embed chat widgets on external websites')}
				</div>
			</div>
			<Tooltip content={$i18n.t('Create Widget')}>
				<Button kind="text" size="sm" type="button" on:click={openCreateModal}>
					<Plus className="size-4" />
				</Button>
			</Tooltip>
		</div>

		<!-- Widget List -->
		{#if loading}
			<div class="flex justify-center py-8">
				<Spinner />
			</div>
		{:else if widgets.length === 0}
			<div class="text-center py-8 text-[var(--cloo-text-muted)]">
				{$i18n.t('No embed widgets yet. Create one to get started.')}
			</div>
		{:else}
			<div class="space-y-2">
				{#each widgets as widget (widget.id)}
					<div
						class="flex items-center justify-between p-3 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)]"
					>
						<div class="flex-1 min-w-0">
							<div class="flex items-center gap-2">
								<span class="font-medium truncate">{widget.name}</span>
								{#if widget.is_active}
									<Badge status="success" size="sm">{$i18n.t('Active')}</Badge>
								{:else}
									<Badge status="default" size="sm">{$i18n.t('Inactive')}</Badge>
								{/if}
							</div>
							<div class="text-xs text-[var(--cloo-text-muted)] mt-0.5 truncate">
								{widget.model_id}
								{#if widget.description}
									&middot; {widget.description}
								{/if}
							</div>
						</div>
						<div class="flex items-center gap-1 ml-2 shrink-0">
							<Tooltip content={$i18n.t('Design')}>
								<Button kind="text" size="sm" type="button" on:click={() => openDesignModal(widget)}>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
										<path fill-rule="evenodd" d="M1 5.25A2.25 2.25 0 0 1 3.25 3h13.5A2.25 2.25 0 0 1 19 5.25v9.5A2.25 2.25 0 0 1 16.75 17H3.25A2.25 2.25 0 0 1 1 14.75v-9.5Zm1.5 5.81v3.69c0 .414.336.75.75.75h13.5a.75.75 0 0 0 .75-.75v-2.69l-2.22-2.219a.75.75 0 0 0-1.06 0l-1.91 1.909.47.47a.75.75 0 1 1-1.06 1.06L6.53 8.091a.75.75 0 0 0-1.06 0L2.5 11.06Z" clip-rule="evenodd" />
									</svg>
								</Button>
							</Tooltip>
							<Tooltip content={$i18n.t('Embed Code')}>
								<Button kind="text" size="sm" type="button" on:click={() => openEmbedCode(widget.id, widget.name)}>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="size-4"
									>
										<path
											fill-rule="evenodd"
											d="M6.28 5.22a.75.75 0 010 1.06L2.56 10l3.72 3.72a.75.75 0 01-1.06 1.06L.97 10.53a.75.75 0 010-1.06l4.25-4.25a.75.75 0 011.06 0zm7.44 0a.75.75 0 011.06 0l4.25 4.25a.75.75 0 010 1.06l-4.25 4.25a.75.75 0 01-1.06-1.06L17.44 10l-3.72-3.72a.75.75 0 010-1.06zM11.377 2.011a.75.75 0 01.612.867l-2.5 14.5a.75.75 0 01-1.478-.255l2.5-14.5a.75.75 0 01.866-.612z"
											clip-rule="evenodd"
										/>
									</svg>
								</Button>
							</Tooltip>
							<Tooltip content={$i18n.t('Edit')}>
								<Button kind="text" size="sm" type="button" on:click={() => openEditModal(widget)}>
									<PencilSquare className="size-4" />
								</Button>
							</Tooltip>
							<Tooltip content={$i18n.t('Delete')}>
								<Button kind="text" size="sm" status="error" type="button" on:click={() => confirmDelete(widget.id)}>
									<GarbageBin className="size-4" />
								</Button>
							</Tooltip>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<!-- Create/Edit Modal -->
<Modal bind:show={showModal} size="md">
	<div class="p-5">
		<div class="text-lg font-medium mb-4">
			{editingWidget ? $i18n.t('Edit Widget') : $i18n.t('Create Widget')}
		</div>

		<form
			class="flex flex-col gap-3"
			on:submit|preventDefault={submitHandler}
		>
			<Input bind:value={formName} label={$i18n.t('Widget Name')} size="md" required />

			<Textarea
				bind:value={formDescription}
				label={$i18n.t('Description')}
				placeholder={$i18n.t('Optional description')}
				size="md"
				rows={2}
			/>

			<div>
				<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Model')}</div>
				<DropdownMenu.Root
					bind:open={showModelDropdown}
					onOpenChange={() => { modelSearchValue = ''; }}
					positioning={{ strategy: 'fixed' }}
				>
					<DropdownMenu.Trigger
						class="flex items-center justify-between w-full px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-sm hover:bg-[var(--cloo-bg-neutral-hovered)] transition"
					>
						{#if selectedModelItem}
							<div class="flex items-center gap-2 min-w-0">
								{#if selectedModelItem.image}
									<img src={selectedModelItem.image} alt="" class="size-5 rounded-full shrink-0" />
								{:else}
									<div class="size-5 rounded-full bg-gray-200 dark:bg-gray-700 shrink-0" />
								{/if}
								<span class="shrink-0 text-[10px] font-semibold px-1 py-0.5 rounded {typeBadgeClass[selectedModelItem.type]}">{typeLabel[selectedModelItem.type]}</span>
								<span class="truncate">{selectedModelItem.name}</span>
							</div>
						{:else}
							<span class="text-[var(--cloo-text-muted)]">{$i18n.t('Select a model')}</span>
						{/if}
						<ChevronDown className="size-3.5 shrink-0 ml-2" strokeWidth="2.5" />
					</DropdownMenu.Trigger>

					<DropdownMenu.Content
						class="z-[10000] max-h-[280px] rounded-xl bg-white dark:bg-gray-850 shadow-lg border border-gray-100 dark:border-gray-800 outline-none overflow-hidden"
						style="width: var(--bits-dropdown-menu-trigger-width, 100%); min-width: 300px;"
						transition={flyAndScale}
						sideOffset={4}
						sameWidth={true}
					>
						<!-- Search -->
						<div class="flex items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800">
							<Search className="size-3.5 text-[var(--cloo-text-muted)]" strokeWidth="2" />
							<input
								bind:value={modelSearchValue}
								class="w-full bg-transparent text-sm outline-none placeholder-[var(--cloo-text-muted)]"
								placeholder={$i18n.t('Search models...')}
							/>
						</div>

						<!-- Model list -->
						<div class="overflow-y-auto max-h-[220px] py-1">
							{#each filteredModelList as item (item.id)}
								<button
									class="flex items-center gap-2 w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 transition {item.id === formModelId ? 'bg-gray-50 dark:bg-gray-800/60' : ''}"
									on:click={() => { formModelId = item.id; showModelDropdown = false; }}
								>
									{#if item.image}
										<img src={item.image} alt="" class="size-5 rounded-full shrink-0" />
									{:else}
										<div class="size-5 rounded-full bg-gray-200 dark:bg-gray-700 shrink-0" />
									{/if}
									<span class="shrink-0 text-[10px] font-semibold px-1 py-0.5 rounded {typeBadgeClass[item.type]}">{typeLabel[item.type]}</span>
									<span class="truncate flex-1">{item.name}</span>
									{#if item.id === formModelId}
										<Check className="size-4 text-[var(--cloo-color-primary)] shrink-0" />
									{/if}
								</button>
							{:else}
								<div class="px-3 py-4 text-center text-sm text-[var(--cloo-text-muted)]">
									{$i18n.t('No results found')}
								</div>
							{/each}
						</div>
					</DropdownMenu.Content>
				</DropdownMenu.Root>
			</div>

			<!-- Additional allowed agents for / slash command switching -->
			<div>
				<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">
					{$i18n.t('Additional agents (/ to switch)')}
				</div>
				<div class="text-xs text-[var(--cloo-text-muted)] mb-1.5">
					{$i18n.t('Users can switch to these agents by typing / in the chat input.')}
				</div>
				<div class="max-h-40 overflow-y-auto border border-[var(--cloo-border-default)] rounded-lg p-1 bg-[var(--cloo-bg-default)]">
					{#each modelListItems.filter((m) => m.id !== formModelId) as item (item.id)}
						<label
							class="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-[var(--cloo-bg-neutral-hovered)] cursor-pointer text-sm"
						>
							<input
								type="checkbox"
								class="size-4"
								checked={formAllowedAgents.includes(item.id)}
								on:change={(e) => toggleAllowedAgent(item.id, e.currentTarget.checked)}
							/>
							{#if item.image}
								<img src={item.image} alt="" class="size-5 rounded-full shrink-0" />
							{:else}
								<div class="size-5 rounded-full bg-gray-200 dark:bg-gray-700 shrink-0" />
							{/if}
							<span class="shrink-0 text-[10px] font-semibold px-1 py-0.5 rounded {typeBadgeClass[item.type]}">{typeLabel[item.type]}</span>
							<span class="truncate flex-1">{item.name}</span>
						</label>
					{:else}
						<div class="px-2 py-3 text-xs text-center text-[var(--cloo-text-muted)]">
							{$i18n.t('No other agents available')}
						</div>
					{/each}
				</div>
			</div>

			<Textarea
				bind:value={formSystemPrompt}
				label={$i18n.t('System Prompt')}
				placeholder={$i18n.t('Optional system prompt for the chat')}
				size="md"
				rows={3}
			/>

			<Input
				bind:value={formWelcomeMessage}
				label={$i18n.t('Welcome Message')}
				size="md"
				placeholder={$i18n.t('Hello! How can I help you?')}
			/>

			<Input
				bind:value={formAllowedDomains}
				label={$i18n.t('Allowed Domains')}
				size="md"
				caption={$i18n.t('Comma-separated. Leave empty to allow all domains.')}
				placeholder="*.example.com, app.mysite.com"
			/>

			<!-- Active Toggle -->
			<LabelBase label={$i18n.t('Active')} size="md">
				<svelte:fragment slot="right"><Switch bind:state={formIsActive} /></svelte:fragment>
			</LabelBase>

			<div class="flex justify-end gap-2 pt-3">
				<Button kind="outlined" size="md" on:click={() => (showModal = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" type="submit">
					{editingWidget ? $i18n.t('Save') : $i18n.t('Create')}
				</Button>
			</div>
		</form>
	</div>
</Modal>

<!-- Embed Code Modal -->
<Modal bind:show={showEmbedCode} size="sm">
	<div class="p-5">
		<div class="text-lg font-medium mb-2">{$i18n.t('Embed Code')}</div>
		<div class="text-xs text-[var(--cloo-text-muted)] mb-3">
			{$i18n.t('Add this code to your website to embed the chat widget.')}
		</div>

		<div
			class="bg-[var(--cloo-bg-surface)] rounded-lg p-3 font-mono text-xs break-all select-all"
		>
			{getEmbedSnippet(embedCodeWidgetId)}
		</div>

		<div class="text-xs text-[var(--cloo-text-muted)] mt-3">
			{$i18n.t('To pass user authentication, add data-token attribute:')}
		</div>
		<div
			class="bg-[var(--cloo-bg-surface)] rounded-lg p-3 font-mono text-xs break-all mt-1"
		>
			data-token="YOUR_JWT_TOKEN"
		</div>

		<div class="flex justify-end gap-2 mt-4">
			<Button kind="outlined" size="md" on:click={() => (showEmbedCode = false)}>
				{$i18n.t('Close')}
			</Button>
			<Button kind="filled" size="md" on:click={copyEmbedCode}>
				{$i18n.t('Copy Embed Code')}
			</Button>
		</div>
	</div>
</Modal>

<!-- Delete Confirm Modal -->
<Modal bind:show={showDeleteConfirm} size="xs">
	<div class="p-5">
		<div class="text-lg font-medium mb-2">{$i18n.t('Delete Widget')}</div>
		<div class="text-sm text-[var(--cloo-text-muted)] mb-4">
			{$i18n.t('Are you sure you want to delete this widget? This action cannot be undone.')}
		</div>
		<div class="flex justify-end gap-2">
			<Button kind="outlined" size="md" on:click={() => (showDeleteConfirm = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" status="error" on:click={deleteWidget}>
				{$i18n.t('Delete')}
			</Button>
		</div>
	</div>
</Modal>

<!-- Design Editor Modal -->
<Modal bind:show={showDesignModal} size="xl">
	<div class="p-5 h-[80vh] flex flex-col">
		<!-- Header -->
		<div class="flex items-center justify-between mb-4">
			<div>
				<div class="text-lg font-medium">{$i18n.t('Widget Design')}</div>
				{#if designWidget}
					<div class="text-xs text-[var(--cloo-text-muted)]">{designWidget.name}</div>
				{/if}
			</div>
			<div class="flex gap-2">
				<Button kind="outlined" size="sm" on:click={() => (showDesignModal = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="sm" on:click={saveDesign}>
					{$i18n.t('Save')}
				</Button>
			</div>
		</div>

		<div class="flex-1 flex gap-4 min-h-0">
			<!-- Left: Settings with tabs -->
			<div class="w-[480px] shrink-0 flex flex-col min-h-0">
				<div class="flex gap-1 mb-3 border-b border-[var(--cloo-border-default)] overflow-x-auto scrollbar-hidden">
					{#each designTabItems as tab (tab.id)}
						<button
							type="button"
							class="px-3 py-2 text-sm font-medium border-b-2 transition whitespace-nowrap {designTab === tab.id ? 'border-[var(--cloo-color-primary)] text-[var(--cloo-text-default)]' : 'border-transparent text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]'}"
							on:click={() => (designTab = tab.id)}
						>
							{$i18n.t(tab.labelKey)}
						</button>
					{/each}
				</div>

				<div class="flex-1 overflow-y-auto pr-1">
					<!-- Layout tab -->
					{#if designTab === 'layout'}
						<div class="space-y-3">
							<div>
								<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Display Mode')}</div>
								<Selector
									items={modeItems}
									value={designMode}
									size="md"
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => { designMode = e.detail.value; }}
								/>
							</div>

							<div>
								<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Theme')}</div>
								<Selector
									items={themeItems}
									value={designTheme}
									size="md"
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => { designTheme = e.detail.value; }}
								/>
							</div>

							{#if designMode === 'bubble'}
								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Position')}</div>
									<Selector
										items={positionItems}
										value={designPosition}
										size="md"
										portal="body"
										contentClassName="z-[10000]"
										on:change={(e) => { designPosition = e.detail.value; }}
									/>
								</div>

								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">
										{$i18n.t('Bubble Open Style')}
									</div>
									<Selector
										items={bubbleOpenStyleItems}
										value={designBubbleOpenStyle}
										size="md"
										portal="body"
										contentClassName="z-[10000]"
										on:change={(e) => {
											designBubbleOpenStyle = e.detail.value;
										}}
									/>
									<div class="text-xs text-[var(--cloo-text-muted)] mt-1">
										{$i18n.t('Popup: small panel above bubble. Side: full-height side panel that hides the bubble.')}
									</div>
								</div>

								<LabelBase label={$i18n.t('Draggable Bubble')} size="md">
									<svelte:fragment slot="right"
										><Switch bind:state={designBubbleDraggable} /></svelte:fragment
									>
								</LabelBase>

								<LabelBase
									label={$i18n.t('Resizable Panel')}
									caption={$i18n.t('Let users drag the panel edge to adjust chat size.')}
									size="md"
								>
									<svelte:fragment slot="right"
										><Switch bind:state={designBubbleResizable} /></svelte:fragment
									>
								</LabelBase>

								<div>
									<div class="flex items-center justify-between mb-1">
										<div class="text-xs font-medium text-[var(--cloo-text-default)]">
											{$i18n.t('Bubble Size')}
										</div>
										<div class="text-xs text-[var(--cloo-text-muted)] font-mono">
											{designBubbleSize}px
										</div>
									</div>
									<input
										type="range"
										min="40"
										max="96"
										step="2"
										bind:value={designBubbleSize}
										class="w-full accent-[var(--cloo-color-primary)]"
									/>
								</div>
							{/if}

							<div class="grid grid-cols-2 gap-2">
								<Input
									bind:value={designWidth}
									label={$i18n.t('Width')}
									size="md"
									placeholder="400px"
								/>
								<Input
									bind:value={designHeight}
									label={$i18n.t('Height')}
									size="md"
									placeholder="600px"
								/>
							</div>
							<div class="text-xs text-[var(--cloo-text-muted)] -mt-1">
								{$i18n.t('Examples: 400px, 100%, 80vh')}
							</div>
						</div>
					{/if}

					<!-- Icons tab -->
					{#if designTab === 'icons'}
						<div class="space-y-4">
							{#if designMode === 'bubble'}
								<div>
									<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mb-2">{$i18n.t('Bubble Icon')}</div>

									<!-- Preset icons -->
									<div class="grid grid-cols-7 gap-1.5 mb-2">
										{#each BUBBLE_ICON_PRESETS as preset (preset.id)}
											<button
												type="button"
												class="aspect-square rounded-lg border flex items-center justify-center transition {isPresetSelected(preset.svg) ? 'border-[var(--cloo-color-primary)] bg-[var(--cloo-color-info)]/10' : 'border-[var(--cloo-border-default)] hover:bg-[var(--cloo-bg-neutral-hovered)]'}"
												title={preset.label}
												on:click={() => selectPresetIcon(preset.svg)}
											>
												<div class="size-5 text-[var(--cloo-text-default)]">
													{@html preset.svg}
												</div>
											</button>
										{/each}
									</div>

									<!-- Custom upload + selected preview -->
									<div class="pt-2 border-t border-[var(--cloo-border-default)]">
										<div class="flex items-center gap-3">
											<div class="size-12 rounded-full overflow-hidden border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] flex items-center justify-center shrink-0">
												{#if designBubbleIconUrl}
													<img src={designBubbleIconUrl} alt="" class="w-full h-full object-cover" />
												{:else}
													<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-6 text-[var(--cloo-text-muted)]">
														<path fill-rule="evenodd" d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 0 1-3.476.383.39.39 0 0 0-.297.17l-2.755 4.133a.75.75 0 0 1-1.248 0l-2.755-4.133a.39.39 0 0 0-.297-.17 48.9 48.9 0 0 1-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97Z" clip-rule="evenodd"/>
													</svg>
												{/if}
											</div>
											<div class="flex flex-col gap-1">
												<Button kind="outlined" size="sm" on:click={() => bubbleIconInput?.click()}>
													{$i18n.t('Upload Custom')}
												</Button>
												{#if designBubbleIconUrl}
													<Button kind="text" size="sm" status="error" on:click={() => (designBubbleIconUrl = '')}>
														{$i18n.t('Reset to Default')}
													</Button>
												{/if}
											</div>
										</div>
									</div>
									<input
										bind:this={bubbleIconInput}
										type="file"
										accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif"
										class="hidden"
										on:change={handleBubbleIconUpload}
									/>
								</div>
							{/if}

							<!-- Send Button Icon -->
							<div class="pt-3 {designMode === 'bubble' ? 'border-t border-[var(--cloo-border-default)]' : ''}">
								<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mb-2">{$i18n.t('Send Button Icon')}</div>

								<!-- Preset icons -->
								<div class="grid grid-cols-7 gap-1.5 mb-2">
									{#each SEND_ICON_PRESETS as preset (preset.id)}
										<button
											type="button"
											class="aspect-square rounded-lg border flex items-center justify-center transition {isSendPresetSelected(preset.svg) ? 'border-[var(--cloo-color-primary)] bg-[var(--cloo-color-info)]/10' : 'border-[var(--cloo-border-default)] hover:bg-[var(--cloo-bg-neutral-hovered)]'}"
											title={preset.label}
											on:click={() => selectSendPreset(preset.svg)}
										>
											<div class="size-5 text-[var(--cloo-text-default)]">
												{@html preset.svg}
											</div>
										</button>
									{/each}
								</div>

								<div class="pt-2 border-t border-[var(--cloo-border-default)]">
									<div class="flex items-center gap-3">
										<div class="size-10 rounded-lg overflow-hidden border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] flex items-center justify-center shrink-0">
											{#if designSendButtonIconUrl}
												<img src={designSendButtonIconUrl} alt="" class="w-full h-full object-cover" />
											{:else}
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5 text-[var(--cloo-text-muted)]">
													<path d="M3.105 2.288a.75.75 0 0 0-.826.95l1.414 4.926A1.5 1.5 0 0 0 5.135 9.25h6.115a.75.75 0 0 1 0 1.5H5.135a1.5 1.5 0 0 0-1.442 1.086l-1.414 4.926a.75.75 0 0 0 .826.95 28.897 28.897 0 0 0 15.293-7.155.75.75 0 0 0 0-1.114A28.897 28.897 0 0 0 3.105 2.288Z"/>
												</svg>
											{/if}
										</div>
										<div class="flex flex-col gap-1">
											<Button kind="outlined" size="sm" on:click={() => sendIconInput?.click()}>
												{$i18n.t('Upload Custom')}
											</Button>
											{#if designSendButtonIconUrl}
												<Button kind="text" size="sm" status="error" on:click={() => (designSendButtonIconUrl = '')}>
													{$i18n.t('Reset to Default')}
												</Button>
											{/if}
										</div>
									</div>
								</div>
								<input
									bind:this={sendIconInput}
									type="file"
									accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif"
									class="hidden"
									on:change={handleSendIconUpload}
								/>
							</div>

							<!-- Shared tip -->
							<div class="flex items-start gap-1.5 text-xs text-[var(--cloo-text-muted)] pt-2 border-t border-[var(--cloo-border-default)]">
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3.5 mt-0.5 shrink-0">
									<path fill-rule="evenodd" d="M15 8A7 7 0 1 1 1 8a7 7 0 0 1 14 0ZM9 5a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM6.75 8a.75.75 0 0 0 0 1.5h.75v1.75a.75.75 0 0 0 1.5 0v-2.5A.75.75 0 0 0 8.25 8h-1.5Z" clip-rule="evenodd"/>
								</svg>
								<span>{$i18n.t('Tip: Use a preset icon if you want to customize the icon color. Uploaded images keep their original colors.')}</span>
							</div>
						</div>
					{/if}

					<!-- Header tab -->
					{#if designTab === 'header'}
						<div class="space-y-3">
							<LabelBase label={$i18n.t('Show Header')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designShowHeader} /></svelte:fragment>
							</LabelBase>

							{#if designShowHeader}
								<LabelBase label={$i18n.t('Show Close Button in Header')} size="md">
									<svelte:fragment slot="right"
										><Switch bind:state={designShowHeaderCloseButton} /></svelte:fragment
									>
								</LabelBase>

								<Input
									bind:value={designHeaderText}
									label={$i18n.t('Header Text')}
									size="md"
									placeholder={designWidget?.name || ''}
								/>

								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Header Background')}</div>
									<div class="flex items-center gap-2">
										<input
											type="color"
											value={designHeaderColor || COLOR_DEFAULTS.headerBg}
											on:input={(e) => (designHeaderColor = getInputValue(e))}
											class="w-9 h-9 rounded cursor-pointer border border-[var(--cloo-border-default)]"
										/>
										<input type="text" bind:value={designHeaderColor} class="flex-1 px-3 py-2 text-sm font-mono rounded border border-[var(--cloo-border-default)] bg-transparent" placeholder={COLOR_DEFAULTS.headerBg} />
										<button type="button" class="text-xs text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]" on:click={() => (designHeaderColor = '')}>{$i18n.t('Reset')}</button>
									</div>
								</div>

								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Header Text Color')}</div>
									<div class="flex items-center gap-2">
										<input
											type="color"
											value={designHeaderTextColor || COLOR_DEFAULTS.headerText}
											on:input={(e) => (designHeaderTextColor = getInputValue(e))}
											class="w-9 h-9 rounded cursor-pointer border border-[var(--cloo-border-default)]"
										/>
										<input type="text" bind:value={designHeaderTextColor} class="flex-1 px-3 py-2 text-sm font-mono rounded border border-[var(--cloo-border-default)] bg-transparent" placeholder={COLOR_DEFAULTS.headerText} />
										<button type="button" class="text-xs text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]" on:click={() => (designHeaderTextColor = '')}>{$i18n.t('Reset')}</button>
									</div>
								</div>
							{/if}
						</div>
					{/if}

					<!-- Colors tab -->
					{#if designTab === 'colors'}
						<div class="space-y-3">
							<!-- Theme Presets -->
							<div>
								<div class="flex items-center justify-between mb-2">
									<div class="text-xs font-medium text-[var(--cloo-text-default)]">
										{$i18n.t('Theme Presets')}
									</div>
									<div class="text-xs text-[var(--cloo-text-muted)]">
										{$i18n.t('Click to apply all colors at once')}
									</div>
								</div>
								<div class="grid grid-cols-3 gap-2">
									{#each THEME_PRESETS as preset (preset.id)}
										<button
											type="button"
											class="group relative flex flex-col items-stretch gap-1.5 p-2 rounded-lg border border-[var(--cloo-border-default)] hover:border-[var(--cloo-color-primary)] hover:shadow-sm transition text-left"
											on:click={() => applyThemePreset(preset)}
											title={preset.description}
										>
											<!-- Color swatches preview (mini bubble + chat bg) -->
											<div
												class="h-10 rounded-md flex items-center justify-between px-2 overflow-hidden"
												style="background-color: {preset.colors.background ||
													preset.swatch[0]};"
											>
												<div
													class="w-5 h-5 rounded-full shrink-0 shadow-sm flex items-center justify-center"
													style="background-color: {preset.colors.primary ||
														preset.swatch[1]}; color: {preset.colors.bubbleIcon ||
														preset.swatch[0]};"
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 24 24"
														fill="currentColor"
														class="w-3 h-3"
													>
														<path
															fill-rule="evenodd"
															d="M4.848 2.771A49.144 49.144 0 0 1 12 2.25c2.43 0 4.817.178 7.152.52 1.978.292 3.348 2.024 3.348 3.97v6.02c0 1.946-1.37 3.678-3.348 3.97a48.901 48.901 0 0 1-3.476.383.39.39 0 0 0-.297.17l-2.755 4.133a.75.75 0 0 1-1.248 0l-2.755-4.133a.39.39 0 0 0-.297-.17 48.9 48.9 0 0 1-3.476-.384c-1.978-.29-3.348-2.024-3.348-3.97V6.741c0-1.946 1.37-3.68 3.348-3.97Z"
															clip-rule="evenodd"
														/>
													</svg>
												</div>
												<div
													class="px-1.5 py-0.5 rounded text-[9px] font-medium truncate"
													style="background-color: {preset.colors.sendButton ||
														preset.swatch[1]}; color: {preset.colors.sendButtonIcon ||
														preset.swatch[0]};"
												>
													Aa
												</div>
											</div>
											<div class="flex items-center justify-between gap-1">
												<div class="flex items-center gap-1 min-w-0">
													<div
														class="text-[11px] font-medium text-[var(--cloo-text-default)] truncate"
													>
														{preset.name}
													</div>
													<span
														class="text-[9px] uppercase tracking-wide px-1 py-px rounded shrink-0 {preset.theme ===
														'dark'
															? 'bg-slate-800 text-slate-300'
															: 'bg-slate-100 text-slate-600'}"
													>
														{preset.theme}
													</span>
												</div>
												<div class="flex gap-0.5 shrink-0">
													<span
														class="w-2 h-2 rounded-full ring-1 ring-black/5"
														style="background-color: {preset.swatch[0]};"
													></span>
													<span
														class="w-2 h-2 rounded-full ring-1 ring-black/5"
														style="background-color: {preset.swatch[1]};"
													></span>
												</div>
											</div>
										</button>
									{/each}
								</div>
							</div>

							<div class="border-t border-[var(--cloo-border-subtle)] pt-3">
								<div class="text-xs font-medium text-[var(--cloo-text-muted)] mb-2">
									{$i18n.t('Or fine-tune individual colors')}
								</div>
							</div>

							{#if designMode === 'bubble'}
								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Bubble Background')}</div>
									<div class="flex items-center gap-2">
										<input type="color" bind:value={designPrimaryColor} class="w-9 h-9 rounded cursor-pointer border border-[var(--cloo-border-default)]" />
										<input type="text" bind:value={designPrimaryColor} class="flex-1 px-3 py-2 text-sm font-mono rounded border border-[var(--cloo-border-default)] bg-transparent" placeholder={COLOR_DEFAULTS.primary} />
										<button type="button" class="text-xs text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]" on:click={() => (designPrimaryColor = COLOR_DEFAULTS.primary)}>{$i18n.t('Reset')}</button>
									</div>
								</div>

								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{$i18n.t('Bubble Icon Color')}</div>
									<div class="flex items-center gap-2">
										<input
											type="color"
											value={designBubbleIconColor || COLOR_DEFAULTS.bubbleIcon}
											on:input={(e) => (designBubbleIconColor = getInputValue(e))}
											class="w-9 h-9 rounded cursor-pointer border border-[var(--cloo-border-default)]"
										/>
										<input type="text" bind:value={designBubbleIconColor} class="flex-1 px-3 py-2 text-sm font-mono rounded border border-[var(--cloo-border-default)] bg-transparent" placeholder={COLOR_DEFAULTS.bubbleIcon} />
										<button type="button" class="text-xs text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]" on:click={() => (designBubbleIconColor = '')}>{$i18n.t('Reset')}</button>
									</div>
								</div>
							{/if}

							{#each [
								{ label: $i18n.t('Background Color'), key: 'background', getter: () => designBackgroundColor, setter: (v) => (designBackgroundColor = v), def: COLOR_DEFAULTS.background },
								{ label: $i18n.t('Message Text Color'), key: 'messageText', getter: () => designMessageTextColor, setter: (v) => (designMessageTextColor = v), def: COLOR_DEFAULTS.messageText },
								{ label: $i18n.t('Send Button Background'), key: 'sendBtn', getter: () => designSendButtonColor, setter: (v) => (designSendButtonColor = v), def: COLOR_DEFAULTS.sendButton },
								{ label: $i18n.t('Send Button Icon'), key: 'sendBtnIcon', getter: () => designSendButtonIconColor, setter: (v) => (designSendButtonIconColor = v), def: COLOR_DEFAULTS.sendButtonIcon }
							] as field (field.key)}
								<div>
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">{field.label}</div>
									<div class="flex items-center gap-2">
										<input
											type="color"
											value={field.getter() || field.def}
											on:input={(e) => field.setter(getInputValue(e))}
											class="w-9 h-9 rounded cursor-pointer border border-[var(--cloo-border-default)]"
										/>
										<input
											type="text"
											value={field.getter()}
											on:input={(e) => field.setter(getInputValue(e))}
											class="flex-1 px-3 py-2 text-sm font-mono rounded border border-[var(--cloo-border-default)] bg-transparent"
											placeholder={field.def}
										/>
										<button type="button" class="text-xs text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)]" on:click={() => field.setter('')}>{$i18n.t('Reset')}</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}

					<!-- Chat tab -->
					{#if designTab === 'chat'}
						<div class="space-y-3">
							<Input
								bind:value={designWelcomeMessage}
								label={$i18n.t('Welcome Message')}
								size="md"
								placeholder={$i18n.t('Hello! How can I help you?')}
							/>

							<Input
								value={String(designMaxMessages)}
								on:input={(e) => {
									designMaxMessages = parseInt(e.detail?.value ?? e.target?.value) || 0;
								}}
								label={$i18n.t('Max Messages Per Session')}
								type="number"
								size="md"
								caption={$i18n.t('0 = unlimited')}
							/>

							<LabelBase label={$i18n.t('Show Bot Icon')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designShowAvatar} /></svelte:fragment>
							</LabelBase>
						</div>
					{/if}

					<!-- Features tab -->
					{#if designTab === 'features'}
						<div class="space-y-2">
							<LabelBase label={$i18n.t('File Upload')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designFileUpload} /></svelte:fragment>
							</LabelBase>
							<LabelBase label={$i18n.t('Markdown')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designMarkdown} /></svelte:fragment>
							</LabelBase>
							<LabelBase label={$i18n.t('Code Highlighting')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designCodeHighlight} /></svelte:fragment>
							</LabelBase>
							<LabelBase label={$i18n.t('Web Search')} size="md">
								<svelte:fragment slot="right"><Switch bind:state={designWebSearch} /></svelte:fragment>
							</LabelBase>
						</div>
					{/if}

					<!-- Auth tab (Login / SSO / Guest) -->
					{#if designTab === 'auth'}
						<div class="space-y-3">
							<!-- Auth Mode Selector -->
							<div>
								<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">
									{$i18n.t('Authentication Mode')}
								</div>
								<Selector
									items={[
										{ value: 'login', label: $i18n.t('Login (Email/Password + OAuth)') },
										{ value: 'sso', label: $i18n.t('SSO Token Exchange') },
										{ value: 'guest', label: $i18n.t('Guest (No Login Required)') }
									]}
									value={designAuthMode}
									size="md"
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => {
										const v = e.detail.value;
										if (v === 'login' || v === 'sso' || v === 'guest') {
											designAuthMode = v;
										}
									}}
								/>
								<div class="text-xs text-[var(--cloo-text-muted)] mt-1">
									{#if designAuthMode === 'login'}
										{$i18n.t('Users must sign in with email/password or OAuth to use the widget.')}
									{:else if designAuthMode === 'sso'}
										{$i18n.t('Allow host sites to log users in automatically using their existing SSO tokens.')}
									{:else}
										{$i18n.t('Allow non-logged-in users to chat without authentication.')}
									{/if}
								</div>
							</div>

							{#if designAuthMode === 'sso'}
								<!-- Auto signup + default role -->
								<LabelBase
									label={$i18n.t('Auto Sign-Up Unknown Users')}
									caption={$i18n.t('If a token belongs to a user not yet in Cloosphere, create the account automatically.')}
									size="md"
								>
									<svelte:fragment slot="right">
										<Switch bind:state={designSsoAutoSignup} />
									</svelte:fragment>
								</LabelBase>

								{#if designSsoAutoSignup}
									<div>
										<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-1">
											{$i18n.t('Default Role for New Users')}
										</div>
										<Selector
											items={[
												{ value: 'user', label: $i18n.t('User') },
												{ value: 'pending', label: $i18n.t('Pending (admin approval required)') },
												{ value: 'admin', label: $i18n.t('Admin') }
											]}
											value={designSsoDefaultRole}
											size="md"
											portal="body"
											contentClassName="z-[10000]"
											on:change={(e) => {
												const v = e.detail.value;
												if (v === 'user' || v === 'pending' || v === 'admin') {
													designSsoDefaultRole = v;
												}
											}}
										/>
									</div>
								{/if}

								<!-- Provider selection -->
								<div class="pt-2 border-t border-[var(--cloo-border-subtle)]">
									<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-2">
										{$i18n.t('Allowed Providers')}
									</div>
									<div class="grid grid-cols-2 gap-2">
										{#each SSO_PROVIDER_OPTIONS as p (p.key)}
											<button
												type="button"
												class="flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-xs transition {designSsoProviders.includes(p.key)
													? 'border-[var(--cloo-color-primary)] bg-[var(--cloo-color-primary)]/5'
													: 'border-[var(--cloo-border-default)] hover:border-[var(--cloo-border-strong)]'}"
												on:click={() => toggleSsoProvider(p.key)}
											>
												<span
													class="w-4 h-4 rounded border flex items-center justify-center shrink-0 {designSsoProviders.includes(p.key)
														? 'border-[var(--cloo-color-primary)] bg-[var(--cloo-color-primary)] text-white'
														: 'border-[var(--cloo-border-default)]'}"
												>
													{#if designSsoProviders.includes(p.key)}
														<svg
															xmlns="http://www.w3.org/2000/svg"
															viewBox="0 0 20 20"
															fill="currentColor"
															class="w-3 h-3"
														>
															<path
																fill-rule="evenodd"
																d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
																clip-rule="evenodd"
															/>
														</svg>
													{/if}
												</span>
												<span class="text-[var(--cloo-text-default)] font-medium">{p.label}</span>
											</button>
										{/each}
									</div>
									<div class="text-xs text-[var(--cloo-text-muted)] mt-2">
										{$i18n.t('Host sites must use one of the providers selected above.')}
									</div>
								</div>

								<!-- Microsoft options -->
								{#if designSsoProviders.includes('microsoft')}
									<div class="pt-2 border-t border-[var(--cloo-border-subtle)] space-y-2">
										<div class="text-xs font-semibold text-[var(--cloo-text-default)] uppercase tracking-wide">
											Microsoft Entra ID
										</div>
										<Input
											bind:value={designSsoMicrosoftTenantId}
											label={$i18n.t('Tenant ID')}
											size="md"
											placeholder={$i18n.t('common or GUID')}
										/>
										<div class="text-xs text-[var(--cloo-text-muted)] -mt-1">
											{$i18n.t("Specific tenant GUID locks login to that directory. Use 'common' for any Microsoft account.")}
										</div>
										<Input
											bind:value={designSsoMicrosoftAudiences}
											label={$i18n.t('Trusted Audiences (Client IDs)')}
											size="md"
											placeholder={$i18n.t('Leave empty to allow any app in the tenant')}
										/>
										<div class="text-xs text-[var(--cloo-text-muted)] -mt-1">
											{$i18n.t('Comma-separated list of allowed client IDs. Leave empty to accept tokens from any app registered in the tenant.')}
										</div>
									</div>
								{/if}

								<!-- Google options -->
								{#if designSsoProviders.includes('google')}
									<div class="pt-2 border-t border-[var(--cloo-border-subtle)] space-y-2">
										<div class="text-xs font-semibold text-[var(--cloo-text-default)] uppercase tracking-wide">
											Google
										</div>
										<Input
											bind:value={designSsoGoogleAudiences}
											label={$i18n.t('Trusted Audiences (Client IDs)')}
											size="md"
											placeholder={$i18n.t('Leave empty to skip audience check')}
										/>
									</div>
								{/if}

								<!-- GitHub: no options needed -->
								{#if designSsoProviders.includes('github')}
									<div class="pt-2 border-t border-[var(--cloo-border-subtle)]">
										<div class="text-xs font-semibold text-[var(--cloo-text-default)] uppercase tracking-wide mb-1">
											GitHub
										</div>
										<div class="text-xs text-[var(--cloo-text-muted)]">
											{$i18n.t('GitHub access tokens are verified against api.github.com. No additional configuration required.')}
										</div>
									</div>
								{/if}

								<!-- OIDC options -->
								{#if designSsoProviders.includes('oidc')}
									<div class="pt-2 border-t border-[var(--cloo-border-subtle)] space-y-2">
										<div class="text-xs font-semibold text-[var(--cloo-text-default)] uppercase tracking-wide">
											Generic OIDC
										</div>
										<Input
											bind:value={designSsoOidcIssuers}
											label={$i18n.t('Trusted Issuers')}
											size="md"
											placeholder="https://your-keycloak.example.com/realms/myrealm"
										/>
										<div class="text-xs text-[var(--cloo-text-muted)] -mt-1">
											{$i18n.t('Comma-separated issuer URLs. The provider must support OIDC discovery (.well-known/openid-configuration).')}
										</div>
										<Input
											bind:value={designSsoOidcAudiences}
											label={$i18n.t('Trusted Audiences (Client IDs)')}
											size="md"
											placeholder={$i18n.t('Leave empty to skip audience check')}
										/>
									</div>
								{/if}
							{/if}

							{#if designAuthMode === 'guest'}
								<LabelBase
									label={$i18n.t('Collect User Info')}
									caption={$i18n.t('Show a form to collect name and email before starting the conversation.')}
									size="md"
								>
									<svelte:fragment slot="right">
										<Switch bind:state={designGuestCollectInfo} />
									</svelte:fragment>
								</LabelBase>

								{#if designGuestCollectInfo}
									<div class="pt-2 border-t border-[var(--cloo-border-subtle)]">
										<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-2">
											{$i18n.t('Required Fields')}
										</div>
										<div class="flex gap-3">
											<label class="flex items-center gap-1.5 text-xs text-[var(--cloo-text-default)]">
												<input
													type="checkbox"
													checked={designGuestRequiredFields.includes('name')}
													on:change={(e) => {
														if (e.currentTarget.checked) {
															designGuestRequiredFields = [...designGuestRequiredFields.filter(f => f !== 'name'), 'name'];
															designGuestOptionalFields = designGuestOptionalFields.filter(f => f !== 'name');
														} else {
															designGuestRequiredFields = designGuestRequiredFields.filter(f => f !== 'name');
														}
													}}
													class="rounded"
												/>
												{$i18n.t('Name')}
											</label>
											<label class="flex items-center gap-1.5 text-xs text-[var(--cloo-text-default)]">
												<input
													type="checkbox"
													checked={designGuestRequiredFields.includes('email')}
													on:change={(e) => {
														if (e.currentTarget.checked) {
															designGuestRequiredFields = [...designGuestRequiredFields.filter(f => f !== 'email'), 'email'];
															designGuestOptionalFields = designGuestOptionalFields.filter(f => f !== 'email');
														} else {
															designGuestRequiredFields = designGuestRequiredFields.filter(f => f !== 'email');
														}
													}}
													class="rounded"
												/>
												{$i18n.t('Email')}
											</label>
										</div>
									</div>
									<div>
										<div class="text-xs font-medium text-[var(--cloo-text-default)] mb-2">
											{$i18n.t('Optional Fields')}
										</div>
										<div class="flex gap-3">
											<label class="flex items-center gap-1.5 text-xs text-[var(--cloo-text-default)]">
												<input
													type="checkbox"
													checked={designGuestOptionalFields.includes('name')}
													disabled={designGuestRequiredFields.includes('name')}
													on:change={(e) => {
														if (e.currentTarget.checked) {
															designGuestOptionalFields = [...designGuestOptionalFields.filter(f => f !== 'name'), 'name'];
														} else {
															designGuestOptionalFields = designGuestOptionalFields.filter(f => f !== 'name');
														}
													}}
													class="rounded"
												/>
												{$i18n.t('Name')}
											</label>
											<label class="flex items-center gap-1.5 text-xs text-[var(--cloo-text-default)]">
												<input
													type="checkbox"
													checked={designGuestOptionalFields.includes('email')}
													disabled={designGuestRequiredFields.includes('email')}
													on:change={(e) => {
														if (e.currentTarget.checked) {
															designGuestOptionalFields = [...designGuestOptionalFields.filter(f => f !== 'email'), 'email'];
														} else {
															designGuestOptionalFields = designGuestOptionalFields.filter(f => f !== 'email');
														}
													}}
													class="rounded"
												/>
												{$i18n.t('Email')}
											</label>
										</div>
									</div>
								{:else}
									<LabelBase
										label={$i18n.t('Auto Proceed')}
										caption={$i18n.t('Automatically create a guest session without any user interaction.')}
										size="md"
									>
										<svelte:fragment slot="right">
											<Switch bind:state={designGuestAutoProcceed} />
										</svelte:fragment>
									</LabelBase>
								{/if}

							{/if}
						</div>
					{/if}
				</div>
			</div>

			<!-- Right: Preview -->
			<div class="flex-1 flex flex-col min-w-0">
				<div class="flex items-center justify-between mb-2">
					<div class="flex items-center gap-2">
						<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide">
							{$i18n.t('Preview')}
						</div>
						<div class="text-xs text-[var(--cloo-text-muted)]">{previewSize.label}</div>
					</div>
					<Button kind="outlined" size="sm" on:click={loadPreview}>
						{$i18n.t('Refresh Preview')}
					</Button>
				</div>
				<div
					class="flex-1 rounded-xl bg-gray-100 dark:bg-gray-800 overflow-hidden relative flex p-4 {designMode === 'side-right' ? 'justify-end items-stretch' : designMode === 'side-left' ? 'justify-start items-stretch' : designMode === 'side-bottom' ? 'justify-stretch items-end' : 'items-center justify-center'}"
				>
					{#if designPreviewUrl}
						<div
							class="rounded-xl overflow-hidden shadow-2xl border border-[var(--cloo-border-default)] bg-white dark:bg-gray-900"
							style="width: {previewSize.width}; height: {previewSize.height}; max-width: 100%; max-height: 100%;"
						>
							<iframe
								src={designPreviewUrl}
								class="w-full h-full border-none"
								title="Widget Preview"
							/>
						</div>
					{:else}
						<div class="m-auto text-sm text-[var(--cloo-text-muted)]">
							{$i18n.t('Click Refresh Preview to load')}
						</div>
					{/if}
				</div>
			</div>
		</div>
	</div>
</Modal>
