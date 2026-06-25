<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher<{ login: { token: string } }>();

	export let baseUrl: string = '';
	export let widgetName: string = '';

	type OAuthProviders = Record<string, string>;
	type Features = {
		auth?: boolean;
		enable_login_form?: boolean;
		enable_signup?: boolean;
	};

	let loaded = false;
	let oauthProviders: OAuthProviders = {};
	let features: Features = {};
	let email = '';
	let password = '';
	let submitting = false;

	$: hasOAuth = Object.keys(oauthProviders).length > 0;
	$: showLoginForm = features.enable_login_form !== false;

	const PROVIDER_LABELS: Record<string, string> = {
		google: 'Google',
		microsoft: 'Microsoft',
		github: 'GitHub',
		oidc: 'SSO'
	};

	const PROVIDER_ICONS: Record<string, string> = {
		google:
			'<svg viewBox="0 0 24 24" width="18" height="18"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A10.99 10.99 0 0 0 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>',
		microsoft:
			'<svg viewBox="0 0 24 24" width="18" height="18"><rect x="2" y="2" width="9" height="9" fill="#F25022"/><rect x="13" y="2" width="9" height="9" fill="#7FBA00"/><rect x="2" y="13" width="9" height="9" fill="#00A4EF"/><rect x="13" y="13" width="9" height="9" fill="#FFB900"/></svg>',
		github:
			'<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 .3a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.9 1.2 1.9 1.2 1.1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.2.5-2.3 1.3-3.1-.2-.4-.6-1.6 0-3.2 0 0 1-.3 3.4 1.2a11.5 11.5 0 0 1 6 0c2.3-1.5 3.3-1.2 3.3-1.2.7 1.6.2 2.8.1 3.2.7.8 1.3 1.9 1.3 3.1 0 4.6-2.8 5.6-5.5 5.9.5.4.9 1.2.9 2.4v3.5c0 .3.2.7.8.6A12 12 0 0 0 12 .3"/></svg>',
		oidc:
			'<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/></svg>'
	};

	const fetchConfig = async () => {
		try {
			const res = await fetch(`${baseUrl}/api/config`);
			if (!res.ok) throw new Error('Failed to fetch config');
			const data = await res.json();
			oauthProviders = data?.oauth?.providers ?? {};
			features = data?.features ?? {};
		} catch (err) {
			console.error('[EmbedLogin] config fetch failed', err);
		} finally {
			loaded = true;
		}
	};

	const loginWithEmail = async () => {
		if (!email.trim() || !password.trim()) {
			toast.error($i18n.t('Please enter email and password'));
			return;
		}
		submitting = true;
		try {
			const res = await fetch(`${baseUrl}/api/v1/auths/signin`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email: email.trim(), password })
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err?.detail || 'Login failed');
			}
			const data = await res.json();
			if (!data?.token) throw new Error('No token in response');
			dispatch('login', { token: data.token });
		} catch (err: any) {
			toast.error(err?.message || $i18n.t('Login failed'));
		} finally {
			submitting = false;
		}
	};

	let oauthPollTimer: ReturnType<typeof setInterval> | null = null;
	let oauthPopup: Window | null = null;

	const loginWithOAuth = (provider: string) => {
		const url = `${baseUrl}/oauth/${provider}/login`;
		const w = 500;
		const h = 650;
		const left = window.screenX + (window.outerWidth - w) / 2;
		const top = window.screenY + (window.outerHeight - h) / 2;
		oauthPopup = window.open(
			url,
			'cloosphere-oauth',
			`width=${w},height=${h},left=${left},top=${top},popup=yes`
		);
		if (!oauthPopup) {
			toast.error($i18n.t('Popup blocked. Please allow popups for this site.'));
			return;
		}

		// Poll for the popup URL until it's back on /auth#token=...
		oauthPollTimer = setInterval(() => {
			if (!oauthPopup || oauthPopup.closed) {
				if (oauthPollTimer) clearInterval(oauthPollTimer);
				oauthPollTimer = null;
				return;
			}
			try {
				const href = oauthPopup.location.href;
				// Same-origin reachable now
				const hash = oauthPopup.location.hash || '';
				const m = hash.match(/token=([^&]+)/);
				if (m) {
					const token = decodeURIComponent(m[1]);
					if (oauthPollTimer) clearInterval(oauthPollTimer);
					oauthPollTimer = null;
					oauthPopup.close();
					oauthPopup = null;
					dispatch('login', { token });
				} else if (href.includes('/auth') && !href.includes('/oauth/')) {
					// Reached auth page but no token yet — keep polling briefly
				}
			} catch {
				// Cross-origin during OAuth provider redirect — ignore
			}
		}, 500);
	};

	onMount(() => {
		fetchConfig();
	});

	onDestroy(() => {
		if (oauthPollTimer) clearInterval(oauthPollTimer);
		if (oauthPopup && !oauthPopup.closed) oauthPopup.close();
	});
</script>

<div class="flex flex-col items-center justify-center h-full p-6 bg-[var(--cloo-bg-default)]">
	{#if !loaded}
		<div class="text-sm text-[var(--cloo-text-muted)]">{$i18n.t('Loading...')}</div>
	{:else}
		<div class="w-full max-w-sm">
			<div class="text-center mb-6">
				<div class="text-lg font-semibold text-[var(--cloo-text-default)]">
					{widgetName || $i18n.t('Sign in')}
				</div>
				<div class="text-xs text-[var(--cloo-text-muted)] mt-1">
					{$i18n.t('Sign in to start chatting')}
				</div>
			</div>

			<!-- OAuth Buttons -->
			{#if hasOAuth}
				<div class="space-y-2 mb-4">
					{#each Object.entries(oauthProviders) as [provider, displayName]}
						<button
							type="button"
							class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] hover:bg-[var(--cloo-bg-neutral-hovered)] text-sm font-medium text-[var(--cloo-text-default)] transition"
							on:click={() => loginWithOAuth(provider)}
						>
							{#if PROVIDER_ICONS[provider]}
								{@html PROVIDER_ICONS[provider]}
							{/if}
							<span>
								{$i18n.t('Continue with')}
								{displayName || PROVIDER_LABELS[provider] || provider}
							</span>
						</button>
					{/each}
				</div>
			{/if}

			<!-- Divider if both OAuth and form -->
			{#if hasOAuth && showLoginForm}
				<div class="flex items-center gap-3 my-4">
					<div class="flex-1 h-px bg-[var(--cloo-border-default)]"></div>
					<div class="text-xs text-[var(--cloo-text-muted)]">{$i18n.t('or')}</div>
					<div class="flex-1 h-px bg-[var(--cloo-border-default)]"></div>
				</div>
			{/if}

			<!-- Email/Password Form -->
			{#if showLoginForm}
				<form
					class="space-y-2"
					on:submit|preventDefault={loginWithEmail}
				>
					<input
						type="email"
						bind:value={email}
						placeholder={$i18n.t('Email')}
						required
						class="w-full px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-sm text-[var(--cloo-text-default)] outline-none focus:border-[var(--cloo-color-primary)]"
					/>
					<input
						type="password"
						bind:value={password}
						placeholder={$i18n.t('Password')}
						required
						class="w-full px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] bg-[var(--cloo-bg-surface)] text-sm text-[var(--cloo-text-default)] outline-none focus:border-[var(--cloo-color-primary)]"
					/>
					<button
						type="submit"
						disabled={submitting}
						class="w-full px-4 py-2.5 rounded-lg bg-[var(--cloo-color-primary)] text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition"
					>
						{submitting ? $i18n.t('Signing in...') : $i18n.t('Sign in')}
					</button>
				</form>
			{/if}

			{#if !hasOAuth && !showLoginForm}
				<div class="text-center text-sm text-[var(--cloo-text-muted)]">
					{$i18n.t('No login method available')}
				</div>
			{/if}
		</div>
	{/if}
</div>
