<script lang="ts">
	import { onMount, onDestroy, setContext } from 'svelte';
	import { page } from '$app/stores';
	import { writable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { getEmbedWidgetConfig, requestGuestToken, type EmbedWidgetConfig } from '$lib/apis/embed-widgets';

	import EmbedChat from '$lib/components/embed/EmbedChat.svelte';
	import EmbedLogin from '$lib/components/embed/EmbedLogin.svelte';
	import EmbedGuestForm from '$lib/components/embed/EmbedGuestForm.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	let loaded = false;
	let error = '';
	let widgetConfig: EmbedWidgetConfig | null = null;
	let token = '';
	let theme = 'auto';
	let baseUrl = '';
	let headerColor = '';
	let headerTextColor = '';
	let messageTextColor = '';
	let backgroundColor = '';
	let sendButtonColor = '';
	let sendButtonIconColor = '';
	let sendButtonIconUrl = '';
	let showHeader = true;
	let showHeaderCloseButton = true;
	let headerText = '';
	let showAvatar = true;
	let avatarUrl = '';
	let botName = '';
	let fileUploadOverride: boolean | null = null;

	// Determine base URL for API calls
	$: baseUrl = WEBUI_BASE_URL || window.location.origin;

	// Guest mode
	$: guestConfig = ((widgetConfig?.config || {}) as Record<string, any>).guest || {};
	$: guestEnabled = guestConfig.enabled === true;
	$: guestCollectInfo = guestConfig.collect_info !== false;

	const applyTheme = (t: string) => {
		const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
		const isDark = t === 'dark' || (t === 'auto' && prefersDark);

		document.documentElement.classList.toggle('dark', isDark);
		document.documentElement.classList.toggle('light', !isDark);
	};

	// Listen for postMessage from parent window
	const handleMessage = (event: MessageEvent) => {
		const data = event.data;
		if (!data || typeof data !== 'object') return;

		if (data.type === 'token-update' && data.token) {
			token = data.token;
		} else if (data.type === 'theme-change' && data.theme) {
			theme = data.theme;
			applyTheme(theme);
		}
	};

	const handleLoginSuccess = (e: CustomEvent<{ token: string }>) => {
		token = e.detail.token;
		try {
			const widgetId = $page.params.id;
			sessionStorage.setItem(`cloosphere_embed_token_${widgetId}`, token);
		} catch {
			// sessionStorage may be blocked (private mode, etc.)
		}
	};

	onMount(async () => {
		// Immediately hide splash screen in embed iframe
		const splash = document.getElementById('splash-screen');
		if (splash) splash.style.display = 'none';

		const widgetId = $page.params.id;

		// Token resolution priority:
		// 1. URL query param (passed by embed.js from data-token attribute)
		// 2. sessionStorage (saved from previous EmbedLogin)
		const urlToken = $page.url.searchParams.get('token') || '';
		const storageKey = `cloosphere_embed_token_${widgetId}`;
		const storedToken =
			typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(storageKey) || '' : '';
		token = urlToken || storedToken;

		// Load widget config (no auth required for public config endpoint)
		try {
			widgetConfig = await getEmbedWidgetConfig(baseUrl, widgetId);
		} catch (e) {
			error = 'Widget not found or inactive';
			return;
		}

		if (!widgetConfig || !widgetConfig.is_active) {
			error = 'Widget not found or inactive';
			return;
		}

		// Apply settings from URL params (design preview) or widget config
		const cfg = (widgetConfig.config || {}) as Record<string, any>;
		const urlTheme = $page.url.searchParams.get('theme');
		theme = urlTheme || cfg.theme || 'auto';
		applyTheme(theme);

		headerColor = $page.url.searchParams.get('headerColor') || cfg.header_color || '';
		headerTextColor = $page.url.searchParams.get('headerTextColor') || cfg.header_text_color || '';
		messageTextColor = $page.url.searchParams.get('messageTextColor') || cfg.message_text_color || '';
		backgroundColor = $page.url.searchParams.get('backgroundColor') || cfg.background_color || '';
		sendButtonColor = $page.url.searchParams.get('sendButtonColor') || cfg.send_button_color || '';
		sendButtonIconColor = $page.url.searchParams.get('sendButtonIconColor') || cfg.send_button_icon_color || '';
		sendButtonIconUrl = $page.url.searchParams.get('sendButtonIconUrl') || cfg.send_button_icon_url || '';
		showHeader = ($page.url.searchParams.get('showHeader') ?? String(cfg.show_header !== false)) !== 'false';
		showHeaderCloseButton =
			($page.url.searchParams.get('showHeaderCloseButton') ??
				String(cfg.show_header_close_button !== false)) !== 'false';
		headerText = $page.url.searchParams.get('headerText') || cfg.header_text || widgetConfig.name;
		showAvatar = ($page.url.searchParams.get('showAvatar') ?? String(cfg.show_avatar !== false)) !== 'false';
		avatarUrl = $page.url.searchParams.get('avatarUrl') || cfg.avatar_url || '';
		botName = $page.url.searchParams.get('botName') || cfg.bot_name || '';

		const fileUploadParam = $page.url.searchParams.get('fileUpload');
		fileUploadOverride = fileUploadParam !== null ? fileUploadParam === 'true' : null;

		// Guest 자동 진행: 토큰 없고 guest 활성화 + 정보 수집 안 함 → 자동 발급
		if (!token) {
			const gCfg = cfg.guest || {};
			if (gCfg.enabled && !gCfg.collect_info) {
				try {
					const resp = await requestGuestToken(baseUrl, widgetId, {
						origin_url: window.location.href,
						referrer: document.referrer || undefined
					});
					if (resp?.token) {
						token = resp.token;
						try {
							sessionStorage.setItem(storageKey, token);
						} catch {}
					}
				} catch (e) {
					console.warn('[EmbedGuest] Auto-proceed failed:', e);
				}
			}
		}

		window.addEventListener('message', handleMessage);
		loaded = true;
	});

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('message', handleMessage);
		}
	});
</script>

<svelte:head>
	<style>
		html, body {
			margin: 0;
			padding: 0;
			height: 100%;
			overflow: hidden;
		}
		/* Hide splash screen in embed iframe */
		#splash-screen {
			display: none !important;
		}
	</style>
</svelte:head>

<div class="h-screen w-full overflow-hidden">
	{#if error}
		<div class="flex items-center justify-center h-full text-[var(--cloo-text-muted)] text-sm p-4 text-center">
			{error}
		</div>
	{:else if !loaded}
		<div class="flex items-center justify-center h-full">
			<Spinner />
		</div>
	{:else if !token && widgetConfig}
		{#if guestEnabled && guestCollectInfo}
			<!-- Guest mode: collect user info -->
			<EmbedGuestForm
				{baseUrl}
				widgetId={$page.params.id}
				widgetName={headerText || widgetConfig.name}
				{guestConfig}
				on:login={handleLoginSuccess}
			/>
		{:else}
			<!-- No token: show login UI (OAuth or email/password) -->
			<EmbedLogin
				{baseUrl}
				widgetName={headerText || widgetConfig.name}
				on:login={handleLoginSuccess}
			/>
		{/if}
	{:else if widgetConfig}
		<EmbedChat
			{widgetConfig}
			{token}
			{baseUrl}
			{headerColor}
			{headerTextColor}
			{messageTextColor}
			{backgroundColor}
			{sendButtonColor}
			{sendButtonIconColor}
			{sendButtonIconUrl}
			{showHeader}
			{showHeaderCloseButton}
			{headerText}
			{showAvatar}
			{avatarUrl}
			{botName}
			{fileUploadOverride}
		/>
	{/if}
</div>
