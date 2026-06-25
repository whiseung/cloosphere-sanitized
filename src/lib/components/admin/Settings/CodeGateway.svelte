<script lang="ts">
	import { getContext, createEventDispatcher, onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import { copyToClipboard } from '$lib/utils';
	import { getCodeGatewayConfig, setCodeGatewayConfig } from '$lib/apis/code-gateway';
	import type { CodeGatewayProviderConfig } from '$lib/apis/code-gateway';
	import { getGuardrails } from '$lib/apis/guardrails';
	import { guardrails } from '$lib/stores';

	import Badge from '$lib/components/common/Badge.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Minus from '$lib/components/icons/Minus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	let loading = true;
	let saving = false;

	let config = {
		enable: false,
		providers: {} as Record<string, CodeGatewayProviderConfig>,
		guardrail_ids: [] as string[],
		follow_global_guardrail: true,
		rate_limit: 0,
		allowed_models: [] as string[],
		blocked_file_patterns: [] as string[],
		blocked_file_action: 'block' as 'block' | 'warn',
		blocked_repos: [] as string[],
		require_repo_metadata: false
	};

	let modelInput = '';
	let filePatternInput = '';
	let repoPatternInput = '';
	let securityEnabled = false;

	// Provider presets — single dropdown that determines type + defaults + compatible tools
	type ProviderPreset = {
		id: string;
		label: string;
		type: string;
		defaultUrl: string;
		defaultName: string;
		group: string;
		tools: string[];
	};

	const PROVIDER_PRESETS: ProviderPreset[] = [
		// Azure
		{ id: 'azure_openai', label: 'Azure OpenAI', type: 'azure_openai', defaultUrl: '', defaultName: 'Azure OpenAI', group: 'Azure', tools: ['Cursor', 'Codex CLI', 'GitHub Copilot'] },
		{ id: 'azure_ai_foundry_openai', label: 'Azure AI Foundry - OpenAI', type: 'openai', defaultUrl: '', defaultName: 'AI Foundry OpenAI', group: 'Azure', tools: ['Cursor', 'Codex CLI', 'GitHub Copilot'] },
		{ id: 'azure_ai_foundry_claude', label: 'Azure AI Foundry - Claude', type: 'azure_ai_foundry', defaultUrl: '', defaultName: 'AI Foundry Claude', group: 'Azure', tools: ['Claude Code', 'Cursor'] },
		// Google Cloud
		{ id: 'vertex_ai', label: 'Vertex AI - Gemini', type: 'vertex_ai', defaultUrl: '', defaultName: 'Vertex AI', group: 'Google Cloud', tools: ['Gemini CLI', 'Cursor', 'Codex CLI'] },
		{ id: 'gemini', label: 'Google AI (Gemini)', type: 'gemini', defaultUrl: 'https://generativelanguage.googleapis.com', defaultName: 'Google AI', group: 'Google Cloud', tools: ['Gemini CLI', 'Cursor', 'Codex CLI'] },
		// Direct API
		{ id: 'openai', label: 'OpenAI', type: 'openai', defaultUrl: 'https://api.openai.com/v1', defaultName: 'OpenAI', group: 'Direct API', tools: ['Cursor', 'Codex CLI', 'GitHub Copilot'] },
		{ id: 'anthropic', label: 'Anthropic', type: 'anthropic', defaultUrl: 'https://api.anthropic.com', defaultName: 'Anthropic', group: 'Direct API', tools: ['Claude Code', 'Cursor'] },
	];

	const PRESET_GROUPS = [...new Set(PROVIDER_PRESETS.map((p) => p.group))];

	// Selector doesn't support optgroup — flatten with "Group: Label" prefix.
	$: presetOptions = PROVIDER_PRESETS.map((p) => ({
		value: p.id,
		label: `${p.group}: ${p.label}`
	}));

	$: selectedPresetTools = PROVIDER_PRESETS.find((p) => p.id === modalPreset)?.tools ?? [];

	let providerExpanded: Record<string, boolean> = {};
	let providerOrder: string[] = [];

	// Modal state
	let showProviderModal = false;
	let editingProviderId: string | null = null;
	let modalPreset = 'azure_openai';
	let modalProviderType = 'azure_openai';
	let modalName = '';
	let modalApiUrl = '';
	let modalApiKey = '';
	let modalApiVersion = '2024-12-01-preview';
	let modalEnable = true;
	let modalModelIds: string[] = [];
	let modalModelId = '';

	// Deployment map (Azure OpenAI only)
	let modalDeploymentMap: { model: string; deployment: string }[] = [];
	let modalDeploymentMapModel = '';
	let modalDeploymentMapDeployment = '';

	// Provider ID (user-defined, unique)
	let modalProviderId = '';

	// Vertex AI fields
	let modalProjectId = '';
	let modalLocation = 'us-central1';
	let modalServiceAccountKey = '';
	let modalUseGlobalGcpKey = false;

	const sanitizeProviderId = (value: string): string => {
		return value
			.toLowerCase()
			.replace(/[^a-z0-9_-]/g, '_')
			.replace(/^_+|_+$/g, '')
			.substring(0, 50);
	};

	const openAddModal = () => {
		editingProviderId = null;
		modalProviderId = '';
		modalPreset = 'azure_openai';
		modalProviderType = 'azure_openai';
		modalName = 'Azure OpenAI';
		modalApiUrl = '';
		modalApiKey = '';
		modalApiVersion = '2024-12-01-preview';
		modalEnable = true;
		modalModelIds = [];
		modalModelId = '';
		modalDeploymentMap = [];
		modalDeploymentMapModel = '';
		modalDeploymentMapDeployment = '';
		modalProjectId = '';
		modalLocation = 'us-central1';
		modalServiceAccountKey = '';
		modalUseGlobalGcpKey = false;
		showProviderModal = true;
	};

	const openEditModal = (providerId: string) => {
		const p = config.providers[providerId];
		if (!p) return;
		editingProviderId = providerId;
		// Resolve preset from saved config or fallback by type
		if (p.preset && PROVIDER_PRESETS.find((pr) => pr.id === p.preset)) {
			modalPreset = p.preset;
		} else {
			const exactMatch = PROVIDER_PRESETS.find((pr) => pr.id === p.type);
			modalPreset = exactMatch?.id ?? PROVIDER_PRESETS.find((pr) => pr.type === p.type)?.id ?? 'openai';
		}
		modalProviderType = p.type || 'openai';
		modalName = p.name || '';
		modalApiUrl = p.api_url || '';
		modalApiKey = p.api_key || '';
		modalApiVersion = p.api_version || '2024-12-01-preview';
		modalEnable = p.enable;
		modalModelIds = p.model_ids ? [...p.model_ids] : [];
		modalModelId = '';
		const dmap = (p as any).deployment_map || {};
		modalDeploymentMap = Object.entries(dmap).map(([model, deployment]) => ({
			model,
			deployment: deployment as string
		}));
		modalDeploymentMapModel = '';
		modalDeploymentMapDeployment = '';
		modalProjectId = p.project_id || '';
		modalLocation = p.location || 'us-central1';
		modalServiceAccountKey = p.service_account_key || '';
		modalUseGlobalGcpKey = p.use_global_gcp_key || false;
		showProviderModal = true;
	};

	const handleProviderModalSubmit = () => {
		if (!modalName.trim()) {
			toast.error($i18n.t('Name is required'));
			return;
		}

		// Validate Provider ID for new providers
		if (!editingProviderId) {
			const sanitized = sanitizeProviderId(modalProviderId);
			if (!sanitized) {
				toast.error($i18n.t('Provider ID is required'));
				return;
			}
			if (config.providers[sanitized]) {
				toast.error($i18n.t('Provider ID already exists'));
				return;
			}
			modalProviderId = sanitized;
		}

		if (modalProviderType === 'vertex_ai' && !modalProjectId.trim()) {
			toast.error($i18n.t('Project ID is required'));
			return;
		}

		if (
			modalProviderType === 'vertex_ai' &&
			!modalUseGlobalGcpKey &&
			!modalServiceAccountKey.trim()
		) {
			toast.error($i18n.t('Service Account Key is required'));
			return;
		}

		const preset = PROVIDER_PRESETS.find((p) => p.id === modalPreset);

		const providerData: CodeGatewayProviderConfig = {
			enable: modalEnable,
			type: modalProviderType,
			preset: modalPreset,
			name: modalName.trim(),
			api_url: modalProviderType === 'vertex_ai'
				? ''
				: modalApiUrl.trim().replace(/\/$/, '') || preset?.defaultUrl || '',
			api_key: modalProviderType === 'vertex_ai' ? '' : modalApiKey,
			model_ids: modalModelIds,
			...(modalProviderType === 'azure_openai'
				? {
						api_version: modalApiVersion,
						deployment_map: Object.fromEntries(
							modalDeploymentMap.map((e) => [e.model, e.deployment])
						)
					}
				: {}),
			...(modalProviderType === 'vertex_ai'
				? {
						project_id: modalProjectId.trim(),
						location: modalLocation.trim() || 'us-central1',
						service_account_key: modalUseGlobalGcpKey ? '' : modalServiceAccountKey,
						use_global_gcp_key: modalUseGlobalGcpKey
					}
				: {})
		};

		if (editingProviderId) {
			config.providers[editingProviderId] = providerData;
		} else {
			config.providers[modalProviderId] = providerData;
			providerOrder = [...providerOrder, modalProviderId];
		}
		config.providers = config.providers;
		showProviderModal = false;
	};

	const removeProvider = (providerId: string) => {
		delete config.providers[providerId];
		config.providers = config.providers;
		providerOrder = providerOrder.filter((id) => id !== providerId);
		delete providerExpanded[providerId];
	};

	const addModalModel = () => {
		if (modalModelId && !modalModelIds.includes(modalModelId)) {
			modalModelIds = [...modalModelIds, modalModelId];
			modalModelId = '';
		}
	};

	// Auto-fill defaults when preset changes in modal
	const onPresetChange = () => {
		const preset = PROVIDER_PRESETS.find((p) => p.id === modalPreset);
		if (preset) {
			modalProviderType = preset.type;
			if (!editingProviderId) {
				modalName = preset.defaultName;
				modalApiUrl = preset.defaultUrl;
			}
		}
		// Reset Vertex AI fields
		modalProjectId = '';
		modalLocation = 'us-central1';
		modalServiceAccountKey = '';
		modalUseGlobalGcpKey = false;
	};

	const addModel = () => {
		const model = modelInput.trim();
		if (model && !config.allowed_models.includes(model)) {
			config.allowed_models = [...config.allowed_models, model];
		}
		modelInput = '';
	};

	const removeModel = (model: string) => {
		config.allowed_models = config.allowed_models.filter((m) => m !== model);
	};

	const addFilePattern = () => {
		const pattern = filePatternInput.trim();
		if (pattern && !config.blocked_file_patterns.includes(pattern)) {
			config.blocked_file_patterns = [...config.blocked_file_patterns, pattern];
		}
		filePatternInput = '';
	};

	const removeFilePattern = (pattern: string) => {
		config.blocked_file_patterns = config.blocked_file_patterns.filter((p) => p !== pattern);
	};

	const handleFilePatternKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			addFilePattern();
		}
	};

	const addRepoPattern = () => {
		const pattern = repoPatternInput.trim();
		if (pattern && !config.blocked_repos.includes(pattern)) {
			config.blocked_repos = [...config.blocked_repos, pattern];
		}
		repoPatternInput = '';
	};

	const removeRepoPattern = (pattern: string) => {
		config.blocked_repos = config.blocked_repos.filter((p) => p !== pattern);
	};

	const handleRepoPatternKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			addRepoPattern();
		}
	};

	const handleModelKeydown = (e: KeyboardEvent) => {
		if (e.key === 'Enter') {
			e.preventDefault();
			addModel();
		}
	};

	const toggleGuardrail = (id: string) => {
		if (config.guardrail_ids.includes(id)) {
			config.guardrail_ids = config.guardrail_ids.filter((gid) => gid !== id);
		} else {
			config.guardrail_ids = [...config.guardrail_ids, id];
		}
	};

	const submitHandler = async () => {
		saving = true;
		try {
			await setCodeGatewayConfig(localStorage.token, config);
			dispatch('save');
		} catch (err) {
			toast.error($i18n.t(`${err}`));
		} finally {
			saving = false;
		}
	};

	const getBaseUrl = () => {
		return `${window.location.origin}/api/v1/code-gateway`;
	};

	const API_KEY_PLACEHOLDER = '<Cloosphere API Key>';

	let guideSelectedTool = '';
	let copiedEntryIndex: number | null = null;
	let guideAction: 'install' | 'uninstall' = 'install';
	let helperScriptOS: 'bash' | 'powershell' = 'bash';

	const getAvailableTools = (): string[] => {
		const tools = new Set<string>();
		for (const id of providerOrder) {
			const p = config.providers[id];
			if (!p?.enable) continue;
			const preset =
				PROVIDER_PRESETS.find((pr) => pr.id === p.preset) ??
				PROVIDER_PRESETS.find((pr) => pr.type === p.type);
			if (preset) preset.tools.forEach((t) => tools.add(t));
		}
		return [...tools];
	};

	const getToolLines = (
		tool: string,
		providerId: string,
		pType: string,
		baseUrl: string,
		os: 'bash' | 'powershell'
	): string[] => {
		const key = API_KEY_PLACEHOLDER;
		const isGeminiType = pType === 'gemini' || pType === 'vertex_ai';

		if (tool === 'Claude Code') {
			if (os === 'powershell') {
				return [
					`# Set environment variables`,
					`$env:CLOOSPHERE_API_KEY = "${key}"`,
					`$env:CLOOSPHERE_GATEWAY_URL = "${baseUrl}/${providerId}"`,
					``,
					`# Install (helper script + settings.json)`,
					`irm "${baseUrl}/setup-script?os=powershell" | iex`,
					``,
					`# Start Claude Code`,
					`claude`
				];
			}
			return [
				`# Set environment variables`,
				`export CLOOSPHERE_API_KEY=${key}`,
				`export CLOOSPHERE_GATEWAY_URL=${baseUrl}/${providerId}`,
				``,
				`# Install (helper script + settings.json)`,
				`source <(curl -s ${baseUrl}/setup-script)`,
				``,
				`# Start Claude Code`,
				`claude`
			];
		}
		if (tool === 'Codex CLI') {
			if (os === 'powershell') {
				return [
					`# Set environment variables`,
					`$env:CLOOSPHERE_API_KEY = "${key}"`,
					`$env:CLOOSPHERE_GATEWAY_URL = "${baseUrl}/${providerId}"`,
					``,
					`# Install (config.toml + metadata script)`,
					`irm "${baseUrl}/codex-setup-script?os=powershell" | iex`,
					``,
					`# Start Codex CLI`,
					`codex`
				];
			}
			return [
				`# Set environment variables`,
				`export CLOOSPHERE_API_KEY=${key}`,
				`export CLOOSPHERE_GATEWAY_URL=${baseUrl}/${providerId}`,
				``,
				`# Install (config.toml + metadata script + codex wrapper)`,
				`source <(curl -s ${baseUrl}/codex-setup-script)`,
				``,
				`# Start Codex CLI`,
				`codex`
			];
		}
		if (tool === 'Cursor') {
			const isAnthropicType = pType === 'anthropic' || pType === 'azure_ai_foundry';
			let lines: string[];
			if (isAnthropicType) {
				lines = [
					`# Cursor Settings > Models > Anthropic API Key`,
					`API Key: ${key}`,
					`Base URL: ${baseUrl}/${providerId}`
				];
			} else {
				const url = isGeminiType
					? `${baseUrl}/${providerId}/v1beta/openai`
					: `${baseUrl}/${providerId}/v1`;
				lines = [
					`# Cursor Settings > Models > OpenAI API Key`,
					`API Key: ${key}`,
					`Base URL: ${url}`
				];
			}
			if (os === 'powershell') {
				lines.push(
					``,
					`# Repository metadata hook 설치 (1회)`,
					`irm "${baseUrl}/cursor-setup-script?os=powershell" | iex`
				);
			} else {
				lines.push(
					``,
					`# Repository metadata hook 설치 (1회)`,
					`source <(curl -s ${baseUrl}/cursor-setup-script)`
				);
			}
			return lines;
		}
		if (tool === 'Gemini CLI') {
			if (os === 'powershell') {
				return [
					`# Set environment variables`,
					`$env:CLOOSPHERE_API_KEY = "${key}"`,
					`$env:CLOOSPHERE_GATEWAY_URL = "${baseUrl}/${providerId}"`,
					``,
					`# Install (hook script + settings.json)`,
					`irm "${baseUrl}/gemini-setup-script?os=powershell" | iex`,
					``,
					`# Start Gemini CLI`,
					`gemini`
				];
			}
			return [
				`# Set environment variables`,
				`export CLOOSPHERE_API_KEY=${key}`,
				`export CLOOSPHERE_GATEWAY_URL=${baseUrl}/${providerId}`,
				``,
				`# Install (hook script + settings.json)`,
				`source <(curl -s ${baseUrl}/gemini-setup-script)`,
				``,
				`# Start Gemini CLI`,
				`gemini`
			];
		}
		if (tool === 'GitHub Copilot') {
			return [
				`# Set environment variables`,
				`export OPENAI_BASE_URL=${baseUrl}/${providerId}/v1`,
				`export OPENAI_API_KEY=${key}`,
				``,
				`# Start GitHub Copilot CLI`,
				`gh copilot`
			];
		}
		return [];
	};

	const getUninstallLines = (tool: string, baseUrl: string, os: 'bash' | 'powershell'): string[] => {
		if (tool === 'Cursor') {
			if (os === 'powershell') {
				return [
					`# Cloosphere Cursor Hook 제거`,
					`irm "${baseUrl}/cursor-uninstall-script?os=powershell" | iex`
				];
			}
			return [
				`# Cloosphere Cursor Hook 제거`,
				`source <(curl -s ${baseUrl}/cursor-uninstall-script)`
			];
		}
		if (tool === 'Codex CLI') {
			if (os === 'powershell') {
				return [
					`# Cloosphere Codex CLI 설정 제거`,
					`irm "${baseUrl}/codex-uninstall-script?os=powershell" | iex`
				];
			}
			return [
				`# Cloosphere Codex CLI 설정 제거`,
				`source <(curl -s ${baseUrl}/codex-uninstall-script)`
			];
		}
		if (tool === 'Claude Code') {
			if (os === 'powershell') {
				return [
					`# Cloosphere Claude Code 설정 제거`,
					`irm "${baseUrl}/claude-uninstall-script?os=powershell" | iex`
				];
			}
			return [
				`# Cloosphere Claude Code 설정 제거`,
				`source <(curl -s ${baseUrl}/claude-uninstall-script)`
			];
		}
		if (tool === 'Gemini CLI') {
			if (os === 'powershell') {
				return [
					`# Cloosphere Gemini CLI 설정 제거`,
					`irm "${baseUrl}/gemini-uninstall-script?os=powershell" | iex`
				];
			}
			return [
				`# Cloosphere Gemini CLI 설정 제거`,
				`source <(curl -s ${baseUrl}/gemini-uninstall-script)`
			];
		}
		return [];
	};

	const getGuideEntries = (
		tool: string,
		action: 'install' | 'uninstall' = 'install',
		os: 'bash' | 'powershell' = 'bash'
	): { providerId: string; providerName: string; lines: string[] }[] => {
		const baseUrl = getBaseUrl();

		if (action === 'uninstall') {
			const lines = getUninstallLines(tool, baseUrl, os);
			if (lines.length > 0) {
				return [{ providerId: '', providerName: $i18n.t('Uninstall'), lines }];
			}
			return [];
		}

		const entries: { providerId: string; providerName: string; lines: string[] }[] = [];
		for (const id of providerOrder) {
			const p = config.providers[id];
			if (!p?.enable) continue;
			const preset =
				PROVIDER_PRESETS.find((pr) => pr.id === p.preset) ??
				PROVIDER_PRESETS.find((pr) => pr.type === p.type);
			if (!preset || !preset.tools.includes(tool)) continue;

			const lines = getToolLines(tool, id, p.type, baseUrl, os);
			if (lines.length > 0) {
				entries.push({ providerId: id, providerName: p.name || id, lines });
			}
		}
		return entries;
	};

	$: availableGuideTools = config.enable ? getAvailableTools() : [];
	$: if (availableGuideTools.length > 0 && !availableGuideTools.includes(guideSelectedTool)) {
		guideSelectedTool = availableGuideTools[0];
	}
	$: guideEntries = guideSelectedTool
		? getGuideEntries(guideSelectedTool, guideAction, helperScriptOS)
		: [];
	$: needsRepoMetadata = config.blocked_repos.length > 0 || config.require_repo_metadata;

	const copyEntryLines = async (lines: string[], index: number) => {
		await copyToClipboard(lines.join('\n'));
		copiedEntryIndex = index;
		setTimeout(() => (copiedEntryIndex = null), 2000);
	};

	const getPresetLabel = (provider: CodeGatewayProviderConfig): string => {
		if (provider.preset) {
			const preset = PROVIDER_PRESETS.find((p) => p.id === provider.preset);
			if (preset) return preset.label;
		}
		// Fallback for old configs without preset field
		const exactMatch = PROVIDER_PRESETS.find((p) => p.id === provider.type);
		if (exactMatch) return exactMatch.label;
		const typeMatch = PROVIDER_PRESETS.find((p) => p.type === provider.type);
		return typeMatch?.label ?? provider.type;
	};

	onMount(async () => {
		try {
			const res = await getCodeGatewayConfig(localStorage.token);
			if (res) {
				config = res;
				providerOrder = Object.keys(config.providers);
				securityEnabled = config.guardrail_ids.length > 0 || config.blocked_file_patterns.length > 0 || config.rate_limit > 0 || config.allowed_models.length > 0 || config.blocked_repos.length > 0 || config.require_repo_metadata;
			}
		} catch (err) {
			toast.error($i18n.t(`${err}`));
		}

		// Load guardrails
		if ($guardrails === null) {
			try {
				const res = await getGuardrails(localStorage.token);
				if (res) {
					guardrails.set(res);
				}
			} catch {
				// ignore
			}
		}

		loading = false;
	});
</script>

<!-- Add / Edit Provider Modal -->
<Modal size="sm" bind:show={showProviderModal}>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{#if editingProviderId}
					{$i18n.t('Edit Provider')}
				{:else}
					{$i18n.t('Add Provider')}
				{/if}
			</div>
			<button
				class="self-center"
				on:click={() => {
					showProviderModal = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<div class="flex flex-col w-full px-4 pb-4 dark:text-gray-200">
			<form
				class="flex flex-col w-full"
				on:submit|preventDefault={handleProviderModalSubmit}
			>
				<div class="px-1">
					<!-- Provider Preset -->
					<div class="flex flex-col w-full mb-2">
						<LabelBase label={$i18n.t('Provider')} size="md">
							<svelte:fragment slot="right">
								<div class="min-w-[16rem]">
									<Selector
										value={modalPreset}
										items={presetOptions}
										size="sm"
										searchEnabled={false}
										disabled={editingProviderId !== null}
										on:change={(event) => {
											modalPreset = event.detail.value;
											onPresetChange();
										}}
									/>
								</div>
							</svelte:fragment>
						</LabelBase>
						{#if selectedPresetTools.length > 0}
							<div class="flex items-center gap-1.5 mt-1.5 flex-wrap justify-end">
								{#each selectedPresetTools as tool}
									<span class="text-[11px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400">{tool}</span>
								{/each}
							</div>
						{/if}
					</div>

					<!-- Provider ID -->
					<div class="mb-2">
						<Input
							bind:value={modalProviderId}
							label={$i18n.t('Provider ID')}
							caption={$i18n.t('Unique identifier used in API URL path. Lowercase, numbers, hyphens, underscores only.')}
							placeholder={$i18n.t('e.g., my-azure-gpt4, prod-openai')}
							size="md"
							autocomplete="off"
							disabled={editingProviderId !== null}
							on:input={() => {
								modalProviderId = sanitizeProviderId(modalProviderId);
							}}
						/>
					</div>

					{#if modalProviderType === 'vertex_ai'}
						<!-- Vertex AI: Project ID + Location + Enable -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={modalProjectId}
									label={$i18n.t('Project ID')}
									placeholder={$i18n.t('Project ID')}
									size="md"
									autocomplete="off"
								/>
							</div>

							<div class="flex-1">
								<Input
									bind:value={modalLocation}
									label={$i18n.t('Location')}
									placeholder={$i18n.t('Location (e.g. us-central1)')}
									size="md"
									autocomplete="off"
								/>
							</div>

							<div class="flex flex-col shrink-0 self-end pb-1.5">
								<Tooltip
									content={modalEnable ? $i18n.t('Enabled') : $i18n.t('Disabled')}
								>
									<Switch bind:state={modalEnable} />
								</Tooltip>
							</div>
						</div>

						<!-- Name -->
						<div class="mt-2">
							<Input
								bind:value={modalName}
								label={$i18n.t('Name')}
								placeholder={$i18n.t('Provider name')}
								size="md"
								autocomplete="off"
							/>
						</div>

						<div class="flex items-center gap-2 mt-2">
							<Checkbox
								state={modalUseGlobalGcpKey ? 'checked' : 'unchecked'}
								on:change={(e) => { modalUseGlobalGcpKey = e.detail === 'checked'; }}
							/>
							<span class="text-xs text-gray-600 dark:text-gray-400">
								{$i18n.t('Use Global Google Cloud Key')}
							</span>
						</div>

						<!-- Service Account Key (hidden when using global key) -->
						{#if !modalUseGlobalGcpKey}
							<div class="flex flex-col w-full mt-2">
								<LabelBase label={$i18n.t('Service Account Key')} size="md" />
								<SensitiveInput
									className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
									bind:value={modalServiceAccountKey}
									placeholder={$i18n.t('Service Account Key JSON')}
									required={false}
								/>
							</div>
						{:else}
							<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
								{$i18n.t('Using global Google Cloud key from Cloud Accounts')}
							</div>
						{/if}
					{:else}
						<!-- URL + Enable -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={modalApiUrl}
									label={$i18n.t('URL')}
									placeholder={$i18n.t('API Base URL')}
									size="md"
									autocomplete="off"
								/>
							</div>

							<div class="flex flex-col shrink-0 self-end pb-1.5">
								<Tooltip
									content={modalEnable ? $i18n.t('Enabled') : $i18n.t('Disabled')}
								>
									<Switch bind:state={modalEnable} />
								</Tooltip>
							</div>
						</div>

						<!-- Key + Name -->
						<div class="flex gap-2 mt-2">
							<div class="flex flex-col w-full">
								<LabelBase label={$i18n.t('Key')} size="md" />
								<SensitiveInput
									className="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none"
									bind:value={modalApiKey}
									placeholder={$i18n.t('API Key')}
									required={false}
								/>
							</div>

							<div class="flex-1">
								<Input
									bind:value={modalName}
									label={$i18n.t('Name')}
									placeholder={$i18n.t('Provider name')}
									size="md"
									autocomplete="off"
								/>
							</div>
						</div>

						<!-- API Version (Azure only) -->
						{#if modalProviderType === 'azure_openai'}
							<div class="mt-2">
								<Input
									bind:value={modalApiVersion}
									label={$i18n.t('API Version')}
									placeholder={$i18n.t('e.g., 2024-02-15-preview')}
									size="md"
									autocomplete="off"
								/>
							</div>

							<!-- Deployment Map -->
							<div class="flex flex-col w-full mt-2">
								<div class="mb-0.5 text-xs text-gray-500">
									{$i18n.t('Deployment Map')}
								</div>
								<div class="text-xs text-gray-400 dark:text-gray-500 mb-1">
									{$i18n.t('Maps model names to Azure deployment names. Leave empty if deployment name equals model name.')}
								</div>

								{#if modalDeploymentMap.length > 0}
									<div class="flex flex-col gap-1 mb-1.5">
										{#each modalDeploymentMap as entry, idx}
											<div class="flex items-center gap-1.5 text-xs">
												<span class="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{entry.model}</span>
												<span class="text-gray-400">&rarr;</span>
												<span class="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{entry.deployment}</span>
												<button
													type="button"
													class="ml-auto text-gray-400 hover:text-red-500"
													on:click={() => {
														modalDeploymentMap = modalDeploymentMap.filter((_, i) => i !== idx);
													}}
												>
													<Minus strokeWidth="2" className="size-3" />
												</button>
											</div>
										{/each}
									</div>
								{/if}

								<div class="flex items-center gap-1.5">
									<input
										class="flex-1 text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
										type="text"
										bind:value={modalDeploymentMapModel}
										placeholder={$i18n.t('Model name')}
									/>
									<span class="text-gray-400 text-xs">&rarr;</span>
									<input
										class="flex-1 text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
										type="text"
										bind:value={modalDeploymentMapDeployment}
										placeholder={$i18n.t('Deployment name')}
									/>
									<button
										type="button"
										on:click={() => {
											if (modalDeploymentMapModel.trim() && modalDeploymentMapDeployment.trim()) {
												modalDeploymentMap = [
													...modalDeploymentMap,
													{
														model: modalDeploymentMapModel.trim(),
														deployment: modalDeploymentMapDeployment.trim()
													}
												];
												modalDeploymentMapModel = '';
												modalDeploymentMapDeployment = '';
											}
										}}
									>
										<Plus className="size-3.5" strokeWidth="2" />
									</button>
								</div>
							</div>
						{/if}
					{/if}

					<hr class="border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

					<!-- Model IDs -->
					<div class="flex flex-col w-full">
						<div class="mb-1 flex justify-between">
							<div class="text-xs text-gray-500">{$i18n.t('Model IDs')}</div>
						</div>

						{#if modalModelIds.length > 0}
							<div class="flex flex-col">
								{#each modalModelIds as mid, midIdx}
									<div
										class="flex gap-2 w-full justify-between items-center"
									>
										<div class="text-sm flex-1 py-1 rounded-lg">
											{mid}
										</div>
										<div class="shrink-0">
											<button
												type="button"
												on:click={() => {
													modalModelIds = modalModelIds.filter(
														(_, idx) => idx !== midIdx
													);
												}}
											>
												<Minus
													strokeWidth="2"
													className="size-3.5"
												/>
											</button>
										</div>
									</div>
								{/each}
							</div>
						{:else}
							<div
								class="text-gray-500 text-xs text-center py-2 px-10"
							>
								{$i18n.t(
									'Leave empty to allow all models for this provider.'
								)}
							</div>
						{/if}
					</div>

					<hr class="border-gray-100 dark:border-gray-700/10 my-2.5 w-full" />

					<div class="flex items-center">
						<input
							class="w-full py-1 text-sm rounded-lg bg-transparent {modalModelId
								? ''
								: 'text-gray-500'} placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
							bind:value={modalModelId}
							placeholder={$i18n.t('Add a model ID')}
						/>

						<div>
							<button
								type="button"
								on:click={() => {
									addModalModel();
								}}
							>
								<Plus className="size-3.5" strokeWidth="2" />
							</button>
						</div>
					</div>
				</div>

			<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
				{#if editingProviderId}
					<!-- [BREAKING] rounded-full → rounded (Figma design token) -->
					<Button
						kind="outlined"
						size="md"
						on:click={() => {
							if (editingProviderId) {
								removeProvider(editingProviderId);
							}
							showProviderModal = false;
						}}
					>
						{$i18n.t('Delete')}
					</Button>
				{/if}

				<Button kind="filled" size="md" type="submit">
					{$i18n.t('Save')}
				</Button>
			</div>
			</form>
		</div>
	</div>
</Modal>

{#if loading}
	<div class="flex justify-center py-8">
		<Spinner className="size-6" />
	</div>
{:else}
	<form
		class="flex flex-col h-full justify-between text-sm"
		on:submit|preventDefault={submitHandler}
	>
		<div class="overflow-y-scroll scrollbar-hidden h-full pr-1.5">
			<div class="my-2">
				<!-- Master Switch -->
				<div class="mb-2.5 flex w-full items-center justify-between">
					<div class="text-base font-medium">{$i18n.t('Code Gateway')}</div>
					<Switch bind:state={config.enable} />
				</div>

				<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t(
						'Proxy AI coding tools (Claude Code, Codex CLI, Gemini CLI, Cursor) through Cloosphere for guardrails, usage tracking, and audit logging.'
					)}
				</div>

				<hr class="border-gray-100 dark:border-gray-850 my-2" />

				{#if config.enable}
					<!-- Providers -->
					<div class="mb-4">
						<div class="flex items-center justify-between mb-2">
							<div class="text-sm font-medium">{$i18n.t('Providers')}</div>
							<Tooltip content={$i18n.t('Add Provider')}>
								<button
									class="px-1"
									type="button"
									on:click={openAddModal}
								>
									<Plus />
								</button>
							</Tooltip>
						</div>

						{#if providerOrder.length === 0}
							<div class="text-xs text-gray-400 dark:text-gray-500 py-2">
								{$i18n.t('No providers configured. Click + to add one.')}
							</div>
						{:else}
							<div class="flex flex-col gap-1.5">
								{#each providerOrder as providerId}
									{#if config.providers[providerId]}
										<div
											class="border border-gray-200 dark:border-gray-700 rounded-lg"
										>
											<div class="flex items-center justify-between px-3 py-2">
												<!-- svelte-ignore a11y-click-events-have-key-events -->
												<button
													class="flex items-center gap-2 flex-1 text-left"
													type="button"
													on:click={() => openEditModal(providerId)}
												>
													<span class="text-sm font-medium">
														{config.providers[providerId].name ||
															providerId}
													</span>
													<span
														class="text-xs font-mono text-gray-400 dark:text-gray-500"
													>
														{providerId}
													</span>
													<span
														class="text-xs text-gray-400 dark:text-gray-500"
													>
														{getPresetLabel(
															config.providers[providerId]
														)}
													</span>
												</button>
												<div class="flex items-center gap-1.5">
													{#if config.providers[providerId].enable && (config.providers[providerId].api_key || config.providers[providerId].type === 'vertex_ai')}
														<span
															class="text-xs text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20 px-1.5 py-0.5 rounded"
														>
															configured
														</span>
													{/if}
													{#if !config.providers[providerId].enable}
														<span
															class="text-xs text-gray-400 dark:text-gray-500 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded"
														>
															disabled
														</span>
													{/if}
													<Tooltip content={$i18n.t('Delete')}>
														<button
															class="p-0.5 text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition"
															type="button"
															on:click|stopPropagation={() =>
																removeProvider(providerId)}
														>
															<XMark className="size-3.5" />
														</button>
													</Tooltip>
												</div>
											</div>
										</div>
									{/if}
								{/each}
							</div>
						{/if}
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- Security -->
					<div class="mb-4">
						<div class="flex items-center justify-between mb-2">
							<div class="text-sm font-medium">{$i18n.t('Security')}</div>
							<Switch
								bind:state={securityEnabled}
							/>
						</div>

						{#if securityEnabled}
						<div transition:slide={{ duration: 200 }}>
						<!-- Follow Global Toggle -->
						<LabelBase
							label={$i18n.t('Follow global guardrail settings')}
							size="sm"
						>
							<svelte:fragment slot="right">
								<Switch bind:state={config.follow_global_guardrail} />
							</svelte:fragment>
						</LabelBase>

						<!-- Guardrails -->
						<div class="mb-2.5">
							<div class="mb-1 text-xs font-medium">
								<Tooltip
									content={$i18n.t(
										'Apply PII detection and blocked word filters to Code Gateway requests.'
									)}
									placement="top-start"
								>
									{$i18n.t('Guardrails')}
								</Tooltip>
							</div>

							<!-- Selected guardrails list -->
							{#if config.guardrail_ids.length > 0}
								<div class="mb-1.5 flex flex-wrap gap-1.5">
									{#each config.guardrail_ids as gid}
										{@const guardrail = $guardrails?.find((g) => g.id === gid)}
										<Badge status={guardrail?.llm_judge_enabled ? 'info' : 'default'} size="sm">
											<span class="inline-flex items-center gap-1">
												{guardrail?.name ?? gid}
												<button
													type="button"
													class="hover:text-[var(--cloo-danger-solid)] transition"
													on:click={() => {
														config.guardrail_ids = config.guardrail_ids.filter((id) => id !== gid);
													}}
												>
													<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
														<path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
													</svg>
												</button>
											</span>
										</Badge>
									{/each}
								</div>
							{/if}

							<Selector
								value=""
								items={($guardrails ?? [])
									.filter((g) => !config.guardrail_ids.includes(g.id))
									.map((g) => ({ value: g.id, label: g.name }))}
								placeholder={$i18n.t('Add guardrail...')}
								size="sm"
								searchEnabled
								on:change={(e) => {
									const val = e.detail.value;
									if (val && !config.guardrail_ids.includes(val)) {
										config.guardrail_ids = [...config.guardrail_ids, val];
									}
								}}
							/>
						</div>

						<!-- Allowed Models -->
						<div class="mb-3">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Allowed Models')}</div>
							<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
								{$i18n.t('Leave empty to allow all models.')}
							</div>
							<div class="flex gap-1.5 mb-1.5">
								<input
									class="flex-1 rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
									placeholder={$i18n.t('Enter model name and press Enter')}
									bind:value={modelInput}
									on:keydown={handleModelKeydown}
								/>
								<button
									type="button"
									class="px-3 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
									on:click={addModel}
								>
									{$i18n.t('Add')}
								</button>
							</div>
							{#if config.allowed_models.length > 0}
								<div class="flex flex-wrap gap-1.5">
									{#each config.allowed_models as model}
										<span
											class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300"
										>
											{model}
											<button
												type="button"
												class="text-gray-400 hover:text-red-500 transition"
												on:click={() => removeModel(model)}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 16 16"
													fill="currentColor"
													class="size-3"
												>
													<path
														d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
													/>
												</svg>
											</button>
										</span>
									{/each}
								</div>
							{/if}
						</div>

						<!-- Rate Limit -->
						<div class="mb-3">
							<div class="flex items-center justify-between">
								<div class="text-xs font-medium">
									<Tooltip
										content={$i18n.t(
											'Maximum requests per minute per user. Set 0 for unlimited.'
										)}
									>
										{$i18n.t('Rate Limit (requests/min, 0=unlimited)')}
									</Tooltip>
								</div>
								<input
									type="number"
									class="w-24 rounded-lg text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden text-center py-1"
									min="0"
									bind:value={config.rate_limit}
								/>
							</div>
						</div>

						<!-- Blocked File Patterns -->
						<div class="mb-3">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Blocked File Patterns')}</div>
							<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
								{$i18n.t('Block access to sensitive files. Supports exact names (.env) and glob patterns (*.pem).')}
							</div>
							<div class="flex gap-1.5 mb-1.5">
								<input
									class="flex-1 rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden font-mono"
									placeholder={$i18n.t('e.g., .env, *.pem, id_rsa, credentials.json')}
									bind:value={filePatternInput}
									on:keydown={handleFilePatternKeydown}
								/>
								<button
									type="button"
									class="px-3 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
									on:click={addFilePattern}
								>
									{$i18n.t('Add')}
								</button>
							</div>
							{#if config.blocked_file_patterns.length > 0}
								<div class="flex flex-wrap gap-1.5">
									{#each config.blocked_file_patterns as pattern}
										<span
											class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 font-mono"
										>
											{pattern}
											<button
												type="button"
												class="text-red-400 hover:text-red-600 transition"
												on:click={() => removeFilePattern(pattern)}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 16 16"
													fill="currentColor"
													class="size-3"
												>
													<path
														d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
													/>
												</svg>
											</button>
										</span>
									{/each}
								</div>
							{/if}

							<!-- Action selector -->
							{#if config.blocked_file_patterns.length > 0}
								<div class="flex items-center gap-2 mt-2">
									<span class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Action')}:</span>
									<div class="flex gap-1">
										<button
											type="button"
											class="px-2.5 py-1 text-xs rounded-lg transition {config.blocked_file_action === 'block'
												? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 font-medium'
												: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'}"
											on:click={() => (config.blocked_file_action = 'block')}
										>
											{$i18n.t('Block')}
										</button>
										<button
											type="button"
											class="px-2.5 py-1 text-xs rounded-lg transition {config.blocked_file_action === 'warn'
												? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 font-medium'
												: 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'}"
											on:click={() => (config.blocked_file_action = 'warn')}
										>
											{$i18n.t('Warn (Log Only)')}
										</button>
									</div>
								</div>
							{/if}
						</div>

						<!-- Blocked Repositories -->
						<div class="mb-3">
							<div class="mb-1 text-xs font-medium">{$i18n.t('Blocked Repositories')}</div>
							<div class="text-xs text-gray-500 dark:text-gray-400 mb-1.5">
								{$i18n.t('Block AI coding tool usage on specific repositories. Enter repository URL patterns (e.g., github.com/org/repo).')}
							</div>
							<div class="flex gap-1.5 mb-1.5">
								<input
									class="flex-1 rounded-lg py-1.5 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden font-mono"
									placeholder={$i18n.t('e.g., github.com/company/secret-repo')}
									bind:value={repoPatternInput}
									on:keydown={handleRepoPatternKeydown}
								/>
								<button
									type="button"
									class="px-3 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
									on:click={addRepoPattern}
								>
									{$i18n.t('Add')}
								</button>
							</div>
							{#if config.blocked_repos.length > 0}
								<div class="flex flex-wrap gap-1.5">
									{#each config.blocked_repos as pattern}
										<span
											class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 font-mono"
										>
											{pattern}
											<button
												type="button"
												class="text-red-400 hover:text-red-600 transition"
												on:click={() => removeRepoPattern(pattern)}
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 16 16"
													fill="currentColor"
													class="size-3"
												>
													<path
														d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
													/>
												</svg>
											</button>
										</span>
									{/each}
								</div>
							{/if}
							<div class="text-xs text-gray-400 dark:text-gray-500 mt-1.5">
								{$i18n.t('Requires helper script setup. Developers must configure their coding tool to send repository metadata.')}
							</div>
						</div>

						<!-- Require Repository Metadata -->
						<div class="mb-3">
							<LabelBase
								label={$i18n.t('Require Repository Metadata')}
								caption={$i18n.t('When enabled, requests without repository metadata will be rejected. Developers must use the helper script.')}
								size="md"
							>
								<svelte:fragment slot="right">
									<Switch bind:state={config.require_repo_metadata} />
								</svelte:fragment>
							</LabelBase>
						</div>

						</div>
						{/if}
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-3" />

					<!-- Developer Setup Guide -->
					<div class="mb-4">
						<div class="text-sm font-medium mb-2">{$i18n.t('Developer Setup Guide')}</div>

						<div class="rounded-lg bg-gray-50 dark:bg-gray-850 px-3 py-2 text-xs text-gray-600 dark:text-gray-400 mb-3">
							API Key: {$i18n.t('Settings')} &gt; {$i18n.t('Account')} &gt; API Keys &gt; {$i18n.t('Create new secret key')} (sk-...)
						</div>

						{#if availableGuideTools.length === 0}
							<div class="text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('Enable at least one provider to see connection info.')}
							</div>
						{:else}
							<div class="flex items-center gap-2 mb-3">
								<span class="text-xs font-medium text-gray-500 dark:text-gray-400">{$i18n.t('Tool')}:</span>
								<div class="min-w-[10rem]">
									<Selector
										value={guideSelectedTool}
										items={availableGuideTools.map((tool) => ({ value: tool, label: tool }))}
										size="sm"
										searchEnabled={false}
										on:change={(event) => { guideSelectedTool = event.detail.value; }}
									/>
								</div>

								<div class="min-w-[8rem]">
									<Selector
										value={guideAction}
										items={[
											{ value: 'install', label: $i18n.t('Install') },
											{ value: 'uninstall', label: $i18n.t('Uninstall') }
										]}
										size="sm"
										searchEnabled={false}
										on:change={(event) => { guideAction = event.detail.value === 'uninstall' ? 'uninstall' : 'install'; }}
									/>
								</div>

								<div class="flex gap-0.5 bg-gray-100 dark:bg-gray-800 rounded-lg p-0.5 ml-auto">
									<button
										type="button"
										class="px-2.5 py-1 text-[11px] rounded-md transition {helperScriptOS === 'bash'
											? 'bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 font-medium shadow-sm'
											: 'text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'}"
										on:click={() => (helperScriptOS = 'bash')}
									>
										Linux / WSL / macOS
									</button>
									<button
										type="button"
										class="px-2.5 py-1 text-[11px] rounded-md transition {helperScriptOS === 'powershell'
											? 'bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 font-medium shadow-sm'
											: 'text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'}"
										on:click={() => (helperScriptOS = 'powershell')}
									>
										Windows
									</button>
								</div>
							</div>

							{#each guideEntries as entry, i}
								<div class="mb-2">
									<div class="text-[11px] text-gray-400 dark:text-gray-500 mb-1">{entry.providerName}</div>
									<div class="relative group rounded-lg bg-gray-900 dark:bg-gray-950 p-2.5 font-mono text-xs text-green-400 leading-relaxed overflow-x-auto">
										{#each entry.lines as line}
											<div>{line}</div>
										{/each}
										<button
											type="button"
											class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 hover:text-white"
											title={$i18n.t('Copy')}
											on:click={() => copyEntryLines(entry.lines, i)}
										>
											{#if copiedEntryIndex === i}
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
													<path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
												</svg>
											{:else}
												<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
													<path d="M7 3.5A1.5 1.5 0 0 1 8.5 2h3.879a1.5 1.5 0 0 1 1.06.44l3.122 3.12A1.5 1.5 0 0 1 17 6.622V12.5a1.5 1.5 0 0 1-1.5 1.5h-1v-3.379a3 3 0 0 0-.879-2.121L10.5 5.379A3 3 0 0 0 8.379 4.5H7v-1Z" />
													<path d="M4.5 6A1.5 1.5 0 0 0 3 7.5v9A1.5 1.5 0 0 0 4.5 18h7a1.5 1.5 0 0 0 1.5-1.5v-5.879a1.5 1.5 0 0 0-.44-1.06L9.44 6.439A1.5 1.5 0 0 0 8.378 6H4.5Z" />
												</svg>
											{/if}
										</button>
									</div>
								</div>
							{/each}
						{/if}
					</div>
				{/if}
			</div>
		</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit" loading={saving}>
			{$i18n.t('Save')}
		</Button>
	</div>
	</form>
{/if}
