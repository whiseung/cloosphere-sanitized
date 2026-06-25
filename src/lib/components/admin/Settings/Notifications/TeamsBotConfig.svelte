<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { slide } from 'svelte/transition';
	import { toast } from 'svelte-sonner';

	import {
		getTeamsBotConfig,
		updateTeamsBotConfig,
		getTeamsMessagingEndpoint,
		downloadTeamsManifestUrl,
		iconPreviewUrl,
		uploadTeamsIcon,
		deleteTeamsIcon,
		type TeamsBotConfig,
		type IconKind
	} from '$lib/apis/teams_bot';
	import { models as modelsStore } from '$lib/stores';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import FieldLabel from '$lib/components/common/FieldLabel.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveHandler: () => void = () => {};

	let loaded = false;
	let saving = false;
	let form: TeamsBotConfig = {
		enabled: false,
		app_id: '',
		app_password: '',
		tenant_id: '',
		model_id: '',
		name: '',
		description_short: '',
		description_full: '',
		developer_name: '',
		developer_website: '',
		scopes: ['personal'],
		accent_color: '#171717',
		default_group_capability: ''
	};

	const toggleScope = (scope: 'personal' | 'team' | 'groupchat') => {
		const has = form.scopes?.includes(scope);
		let next = (form.scopes ?? []).filter((s) => s !== scope);
		if (!has) next = [...next, scope];
		if (next.length === 0) next = ['personal'];
		form.scopes = next as TeamsBotConfig['scopes'];
		// 단일 scope 면 defaultGroupCapability 무의미 → 초기화
		if (form.scopes.length <= 1) form.default_group_capability = '';
	};

	$: groupCapItems = [
		{ value: '', label: $i18n.t('Auto') },
		{ value: 'team', label: $i18n.t('Team (channel)') },
		{ value: 'groupchat', label: $i18n.t('Group chat') },
		{ value: 'meetings', label: $i18n.t('Meetings') }
	];
	let messagingEndpoint = '';
	// cache-bust 용 토큰 (업로드 후 증가시켜 미리보기 강제 refresh)
	let iconCacheToken = Date.now();

	$: modelItems = ($modelsStore ?? []).map((m: any) => ({
		value: m.id,
		label: m.name || m.id
	}));

	$: colorIconUrl = form.has_color_icon
		? `${iconPreviewUrl('color')}?t=${iconCacheToken}`
		: '';
	$: outlineIconUrl = form.has_outline_icon
		? `${iconPreviewUrl('outline')}?t=${iconCacheToken}`
		: '';

	const reloadConfig = async () => {
		const cfg = await getTeamsBotConfig(localStorage.token);
		form = { ...cfg };
	};

	onMount(async () => {
		try {
			const [cfg, ep] = await Promise.all([
				getTeamsBotConfig(localStorage.token),
				getTeamsMessagingEndpoint(localStorage.token)
			]);
			form = { ...cfg };
			messagingEndpoint = ep.messaging_endpoint;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load Teams bot config'));
		} finally {
			loaded = true;
		}
	});

	const copyEndpoint = async () => {
		try {
			await navigator.clipboard.writeText(messagingEndpoint);
			toast.success($i18n.t('Copied to clipboard'));
		} catch {
			toast.error($i18n.t('Copy failed'));
		}
	};

	const downloadManifest = async () => {
		if (!form.app_id?.trim()) {
			toast.error($i18n.t('App ID is required to generate the Teams manifest.'));
			return;
		}
		const token = localStorage.token;
		try {
			const res = await fetch(downloadTeamsManifestUrl(), {
				headers: { Authorization: `Bearer ${token}` }
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw err;
			}
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = 'cloosphere-teams.zip';
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Manifest download failed'));
		}
	};

	const onIconPicked = async (kind: IconKind, ev: Event) => {
		const input = ev.target as HTMLInputElement;
		const file = input.files?.[0];
		input.value = ''; // 같은 파일 다시 선택 가능하도록
		if (!file) return;
		try {
			await uploadTeamsIcon(localStorage.token, kind, file);
			toast.success($i18n.t('Icon uploaded'));
			iconCacheToken = Date.now();
			await reloadConfig();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Icon upload failed'));
		}
	};

	const clearIcon = async (kind: IconKind) => {
		try {
			await deleteTeamsIcon(localStorage.token, kind);
			toast.success($i18n.t('Icon cleared (using default)'));
			iconCacheToken = Date.now();
			await reloadConfig();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Icon delete failed'));
		}
	};

	const save = async () => {
		if (form.enabled && !(form.model_id || '').trim()) {
			toast.error($i18n.t('Default agent/model is required when Teams bot is enabled.'));
			return;
		}
		saving = true;
		try {
			const updated = await updateTeamsBotConfig(localStorage.token, form);
			form = { ...updated };
			toast.success($i18n.t('Teams bot config saved'));
			saveHandler();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Save failed'));
		} finally {
			saving = false;
		}
	};
</script>

{#if !loaded}
	<div class="flex items-center justify-center py-6">
		<Spinner />
	</div>
{:else}
	<div class="flex flex-col gap-3">
		<!-- Enable -->
		<LabelBase
			label={$i18n.t('Enable Teams Bot')}
			caption={$i18n.t('Accepts incoming Microsoft Teams activities at /api/v1/teams/messages.')}
			size="md"
		>
			<svelte:fragment slot="right">
				<Switch bind:state={form.enabled} />
			</svelte:fragment>
		</LabelBase>

		{#if form.enabled}
			<div transition:slide={{ duration: 200 }} class="flex flex-col gap-3">
				<!-- ── 인증 ── -->
				<div
					class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mt-2"
				>
					{$i18n.t('Authentication')}
				</div>

				<!-- App ID + Tenant ID 가로 2열 (md 이상) -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('App ID')} hint={$i18n.t('Azure Bot / Entra app client ID (GUID).')} size="md" />
						<Input bind:value={form.app_id} placeholder="00000000-0000-0000-0000-000000000000" size="md" />
				</div>

					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Tenant ID')} hint={$i18n.t('Azure AD tenant ID (GUID). Use "common" for multi-tenant.')} size="md" />
						<Input bind:value={form.tenant_id} placeholder="00000000-0000-0000-0000-000000000000" size="md" />
				</div>
				</div>

				<!-- App Password + Default Agent 가로 2열 -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('App Password')} hint={$i18n.t('Client secret from the Entra app registration.')} size="md" />
						<SensitiveInput
							placeholder={$i18n.t('App Password')}
							bind:value={form.app_password}
							required={false}
						/>
				</div>

					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Default Agent')} hint={$i18n.t('Users can override via /agent in Teams.')} size="md" />
						<Selector
							items={modelItems}
							value={form.model_id}
							size="md"
							searchEnabled={true}
							placeholder={$i18n.t('Select agent/model')}
							on:change={(e) => (form.model_id = e.detail.value)}
						/>
				</div>
				</div>

				<!-- ── 브랜딩 (매니페스트에 반영) ── -->
				<div
					class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mt-2"
				>
					{$i18n.t('Branding (Teams manifest)')}
				</div>

				<!-- Bot Name + Developer Name 가로 2열 -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Bot Name')} hint={$i18n.t('Shown in Teams. Max 30 characters.')} size="md" />
						<Input bind:value={form.name} placeholder="Cloosphere" size="md" />
				</div>

					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Developer / Company Name')} hint={$i18n.t('Publisher name on the Teams app detail page.')} size="md" />
						<Input bind:value={form.developer_name} placeholder="Cloocus" size="md" />
				</div>
				</div>

				<!-- Short Description + Developer Website 가로 2열 -->
				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Short Description')} hint={$i18n.t('One-line. Max 80 characters.')} size="md" />
						<Input bind:value={form.description_short} placeholder={$i18n.t('Chat with your Cloosphere agents inside Teams.')} size="md" />
				</div>

					<div class="flex flex-col gap-1.5 w-full">
						<FieldLabel label={$i18n.t('Developer Website URL')} hint={$i18n.t('Used to derive privacy & terms URLs.')} size="md" />
						<Input bind:value={form.developer_website} placeholder="https://www.example.com" size="md" />
				</div>
				</div>

				<div class="flex flex-col gap-1.5 w-full">
					<FieldLabel label={$i18n.t('Full Description')} hint={$i18n.t('Detailed description for the app detail page.')} size="md" />
					<Textarea bind:value={form.description_full} rows={3} size="md" />
				</div>

				<!-- ── 아이콘 ── -->
				<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mt-2">
					{$i18n.t('Icons')}
				</div>

				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<!-- Color icon -->
					<div class="flex flex-col gap-2 p-3 border border-[var(--cloo-border-default)] rounded-lg">
						<div class="flex items-center justify-between">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Color Icon')}</div>
								<div class="text-xs text-[var(--cloo-text-muted)]">
									{$i18n.t('192×192 PNG/JPEG recommended')}
								</div>
							</div>
							{#if form.has_color_icon}
								<Button
									kind="text"
									size="sm"
									on:click={() => clearIcon('color')}
								>
									{$i18n.t('Remove')}
								</Button>
							{/if}
						</div>
						<div
							class="flex items-center justify-center bg-gray-50 dark:bg-gray-900 rounded border border-[var(--cloo-border-subtle)] h-32"
						>
							{#if colorIconUrl}
								<img src={colorIconUrl} alt="color icon" class="max-h-28 max-w-28" />
							{:else}
								<span class="text-xs text-[var(--cloo-text-muted)]"
									>{$i18n.t('Using default')}</span
								>
							{/if}
						</div>
						<label class="inline-flex">
							<input
								type="file"
								accept="image/png,image/jpeg"
								class="hidden"
								on:change={(e) => onIconPicked('color', e)}
							/>
							<span
								class="w-full text-center text-xs px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] cursor-pointer hover:bg-[var(--cloo-bg-neutral-hovered)]"
							>
								{$i18n.t('Upload Color Icon')}
							</span>
						</label>
					</div>

					<!-- Outline icon -->
					<div class="flex flex-col gap-2 p-3 border border-[var(--cloo-border-default)] rounded-lg">
						<div class="flex items-center justify-between">
							<div>
								<div class="text-sm font-medium">{$i18n.t('Outline Icon')}</div>
								<div class="text-xs text-[var(--cloo-text-muted)]">
									{$i18n.t('32×32 transparent PNG (white silhouette)')}
								</div>
							</div>
							{#if form.has_outline_icon}
								<Button
									kind="text"
									size="sm"
									on:click={() => clearIcon('outline')}
								>
									{$i18n.t('Remove')}
								</Button>
							{/if}
						</div>
						<div
							class="flex items-center justify-center bg-gray-700 dark:bg-gray-900 rounded border border-[var(--cloo-border-subtle)] h-32"
						>
							{#if outlineIconUrl}
								<img src={outlineIconUrl} alt="outline icon" class="max-h-16 max-w-16" />
							{:else}
								<span class="text-xs text-gray-300">{$i18n.t('Using default')}</span>
							{/if}
						</div>
						<label class="inline-flex">
							<input
								type="file"
								accept="image/png,image/jpeg"
								class="hidden"
								on:change={(e) => onIconPicked('outline', e)}
							/>
							<span
								class="w-full text-center text-xs px-3 py-2 rounded-lg border border-[var(--cloo-border-default)] cursor-pointer hover:bg-[var(--cloo-bg-neutral-hovered)]"
							>
								{$i18n.t('Upload Outline Icon')}
							</span>
						</label>
					</div>
				</div>

				<!-- ── 배포 범위 (Deployment) ── -->
				<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mt-2">
					{$i18n.t('Deployment')}
				</div>

				<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
					<!-- Scope 체크박스 -->
					<div class="flex flex-col gap-2">
						<div class="text-sm font-medium text-[var(--cloo-text-primary)]">
							{$i18n.t('Bot Scopes')}
						</div>
						<div class="flex flex-wrap gap-3">
							<label class="inline-flex items-center gap-2 text-sm">
								<input
									type="checkbox"
									checked={form.scopes?.includes('personal')}
									on:change={() => toggleScope('personal')}
								/>
								<span>{$i18n.t('Personal (1:1 chat)')}</span>
							</label>
							<label class="inline-flex items-center gap-2 text-sm">
								<input
									type="checkbox"
									checked={form.scopes?.includes('team')}
									on:change={() => toggleScope('team')}
								/>
								<span>{$i18n.t('Team (channel @mention)')}</span>
							</label>
							<label class="inline-flex items-center gap-2 text-sm">
								<input
									type="checkbox"
									checked={form.scopes?.includes('groupchat')}
									on:change={() => toggleScope('groupchat')}
								/>
								<span>{$i18n.t('Group chat')}</span>
							</label>
						</div>
						<p class="text-xs text-[var(--cloo-text-muted)]">
							{$i18n.t(
								'Team/Group chat scopes automatically add required RSC permissions (admin consent at Teams Admin Center).'
							)}
						</p>
					</div>

					<!-- Accent color + default capability -->
					<div class="flex flex-col gap-3">
						<div class="flex flex-col gap-1">
							<div class="text-sm font-medium text-[var(--cloo-text-primary)]">
								{$i18n.t('Accent Color')}
							</div>
							<div class="flex gap-2 items-center">
								<input
									type="color"
									bind:value={form.accent_color}
									class="h-9 w-12 bg-transparent border border-[var(--cloo-border-default)] rounded-lg cursor-pointer"
								/>
								<input
									type="text"
									bind:value={form.accent_color}
									placeholder="#171717"
									class="flex-1 bg-transparent text-sm py-2 px-3 rounded-lg border border-[var(--cloo-border-default)]"
								/>
							</div>
							<p class="text-xs text-[var(--cloo-text-muted)]">
								{$i18n.t('Brand color shown in Teams cards and header.')}
							</p>
						</div>

						{#if (form.scopes?.length ?? 0) > 1}
							<div class="flex flex-col gap-1">
								<div class="text-sm font-medium text-[var(--cloo-text-primary)]">
									{$i18n.t('Default Group Capability')}
								</div>
								<Selector
									value={form.default_group_capability}
									items={groupCapItems}
									size="md"
									placeholder={$i18n.t('Auto')}
									on:change={(e) => (form.default_group_capability = e.detail.value)}
								/>
								<p class="text-xs text-[var(--cloo-text-muted)]">
									{$i18n.t(
										'When installed at team/org level, which surface is pinned by default.'
									)}
								</p>
							</div>
						{/if}
					</div>
				</div>

				<!-- ── 엔드포인트 + 매니페스트 ── -->
				<div class="text-xs font-semibold text-[var(--cloo-text-muted)] uppercase tracking-wide mt-2">
					{$i18n.t('Integration')}
				</div>

				<div class="flex flex-col gap-1">
					<FieldLabel
						label={$i18n.t('Messaging Endpoint')}
						hint={$i18n.t('Paste this URL into Azure Bot Configuration → Messaging endpoint.')}
						size="md"
					/>
					<div class="flex gap-2 items-center">
						<div class="flex-1">
							<Input value={messagingEndpoint} readOnly size="md" />
						</div>
						<Button kind="outlined" size="sm" type="button" on:click={copyEndpoint}>
							{$i18n.t('Copy')}
						</Button>
					</div>
				</div>

				<div class="flex justify-between items-center py-1">
					<div class="text-sm text-[var(--cloo-text-default)]">
						<div class="font-medium">{$i18n.t('Teams app package')}</div>
						<div class="text-xs text-[var(--cloo-text-muted)] mt-0.5">
							{$i18n.t(
								'Downloads manifest.zip with current App ID. Upload to Teams via Apps → Upload custom app.'
							)}
						</div>
					</div>
					<Button kind="outlined" size="sm" on:click={downloadManifest}>
						{$i18n.t('Download Teams Manifest')}
					</Button>
				</div>
			</div>
		{/if}

		<!-- Save -->
		<div class="flex justify-end pt-2">
			<Button kind="filled" size="md" type="button" disabled={saving} on:click={save}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
{/if}
