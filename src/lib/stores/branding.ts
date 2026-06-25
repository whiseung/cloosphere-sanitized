import { derived, writable } from 'svelte/store';
import { config } from '$lib/stores';

// Incremented after each branding asset upload to force favicon URL change
export const brandingVersion = writable(Date.now());

export const brandingUrls = derived([config, brandingVersion], ([$config, $version]) => ({
	favicon: $config?.branding?.favicon_url ?? '/static/favicon.png',
	faviconDark: $config?.branding?.favicon_dark_url ?? '/static/favicon-dark.png',
	logo: $config?.branding?.logo_url ?? '/static/logo.png',
	splash: $config?.branding?.splash_url ?? '/static/splash.png',
	splashDark: $config?.branding?.splash_dark_url ?? '/static/splash-dark.png',
	browserFavicon: `${$config?.branding?.browser_favicon_url ?? '/static/favicon.png'}?v=${$version}`
}));
