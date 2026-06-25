<script lang="ts">
	import { getContext, onMount } from 'svelte';
	const i18n = getContext('i18n');

	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	export let connection: {
		type: string;
		url: string;
		auth_type: string;
		key: string;
		headers: Record<string, string>;
		enabled: boolean;
		enabled_tools?: string[];
	};

	let headersText = '';

	// UI 분리 상태 — 저장 형태(connection.auth_type)는 그대로 유지하되 노출은 단순화.
	//   저장 형태: none / bearer / api_key / oauth_microsoft / oauth_google
	//   UI 형태:  uiAuthType ∈ {none, bearer, api_key, oauth} + oauthProvider ∈ {microsoft, google}
	let uiAuthType: string = 'none';
	let oauthProvider: 'microsoft' | 'google' = 'microsoft';
	let initialized = false;

	onMount(() => {
		const at = connection.auth_type ?? 'none';
		if (at === 'oauth_microsoft') {
			uiAuthType = 'oauth';
			oauthProvider = 'microsoft';
		} else if (at === 'oauth_google') {
			uiAuthType = 'oauth';
			oauthProvider = 'google';
		} else {
			uiAuthType = at;
		}
		initialized = true;
	});

	// UI 변경 → connection.auth_type 갱신
	$: if (initialized) {
		const next = uiAuthType === 'oauth' ? `oauth_${oauthProvider}` : uiAuthType;
		if (connection.auth_type !== next) {
			connection.auth_type = next;
		}
	}

	// Initialize headers text from connection data
	$: if (connection.headers && Object.keys(connection.headers).length > 0 && !headersText) {
		headersText = Object.entries(connection.headers)
			.map(([k, v]) => `${k}: ${v}`)
			.join('\n');
	}

	const parseHeaders = (text: string): Record<string, string> => {
		const result: Record<string, string> = {};
		text.split('\n').forEach((line) => {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes(':')) {
				const colonIndex = trimmed.indexOf(':');
				const key = trimmed.substring(0, colonIndex).trim();
				const value = trimmed.substring(colonIndex + 1).trim();
				if (key) result[key] = value;
			}
		});
		return result;
	};

	const updateHeaders = () => {
		connection.headers = parseHeaders(headersText);
	};
</script>

<!-- MCP Server URL -->
<div class="flex w-full justify-between items-center">
	<div class="self-center text-xs font-medium">{$i18n.t('MCP Server URL')}</div>
	<input
		type="url"
		class="w-56 px-2 py-1 rounded-sm text-xs text-right bg-transparent dark:bg-gray-900 outline-hidden"
		bind:value={connection.url}
		placeholder="https://mcp.example.com/sse"
	/>
</div>

<!-- Auth Type -->
<div class="flex w-full justify-between items-center">
	<div class="self-center text-xs font-medium">{$i18n.t('Auth Type')}</div>
	<div class="flex items-center relative">
		<select
			class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right"
			bind:value={uiAuthType}
		>
			<option value="none">{$i18n.t('None')}</option>
			<option value="bearer">Bearer Token</option>
			<option value="api_key">API Key</option>
			<option value="oauth">{$i18n.t('OAuth 2.0 (User SSO)')}</option>
		</select>
	</div>
</div>

<!-- OAuth Provider — auth_type=oauth 일 때만 -->
{#if uiAuthType === 'oauth'}
	<div class="flex w-full justify-between items-center">
		<div class="self-center text-xs font-medium">{$i18n.t('Provider')}</div>
		<div class="flex items-center relative">
			<select
				class="dark:bg-gray-900 w-fit pr-8 rounded-sm px-2 py-1 text-xs bg-transparent outline-hidden text-right"
				bind:value={oauthProvider}
			>
				<option value="microsoft">Microsoft</option>
				<option value="google">Google</option>
			</select>
		</div>
	</div>

	<div class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
		{$i18n.t(
			"This connection injects each user's own SSO access token into the Authorization header on every call. No key needed here — users connect by signing in with the matching provider."
		)}
	</div>
{/if}

<!-- API Key / Token -->
{#if uiAuthType === 'bearer' || uiAuthType === 'api_key'}
	<div class="flex w-full justify-between items-center">
		<div class="self-center text-xs font-medium">
			{uiAuthType === 'bearer' ? $i18n.t('Token') : $i18n.t('API Key')}
		</div>
		<div class="w-48">
			<SensitiveInput
				inputClassName="w-full px-2 py-1 rounded-sm text-xs text-right bg-transparent dark:bg-gray-900 outline-hidden"
				bind:value={connection.key}
				placeholder={uiAuthType === 'bearer' ? 'Bearer token...' : 'API key...'}
				required={false}
			/>
		</div>
	</div>
{/if}

<!-- Additional Headers -->
<div class="space-y-1">
	<div class="text-xs font-medium">
		{$i18n.t('Additional Headers')}
		<span class="font-normal text-gray-500">({$i18n.t('optional')})</span>
	</div>
	<textarea
		class="w-full px-2 py-1.5 rounded-sm text-xs bg-transparent dark:bg-gray-900 outline-hidden font-mono resize-none"
		rows="2"
		bind:value={headersText}
		on:input={updateHeaders}
		placeholder={`X-Custom-Header: value`}
	/>
</div>
