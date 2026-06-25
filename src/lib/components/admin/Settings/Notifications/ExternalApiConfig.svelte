<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		listTrustedAudiences,
		createTrustedAudience,
		updateTrustedAudience,
		deleteTrustedAudience,
		type TrustedAudience,
		type TrustedAudienceForm,
		type IdpType
	} from '$lib/apis/trusted_audiences';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import FieldLabel from '$lib/components/common/FieldLabel.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Cog6 from '$lib/components/icons/Cog6.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';

	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext<Writable<i18nType>>('i18n');

	export let saveHandler: () => void = () => {};

	let loaded = false;
	let items: TrustedAudience[] = [];

	// 편집/생성 모달 상태
	let showEditor = false;
	let editingId: string | null = null;
	let form: TrustedAudienceForm = emptyForm();
	let saving = false;

	function emptyForm(): TrustedAudienceForm {
		return {
			idp_type: 'entra',
			audience: '',
			tenant_id: '',
			issuer: '',
			name: '',
			enabled: true,
			auto_provision: false,
			default_role: 'user',
			default_group_ids: null
		};
	}

	const idpItems = [
		{ value: 'entra', label: 'Microsoft Entra' },
		{ value: 'google', label: 'Google' }
	];
	const roleItems = [
		{ value: 'user', label: 'user' },
		{ value: 'admin', label: 'admin' }
	];

	const reload = async () => {
		try {
			items = await listTrustedAudiences(localStorage.token);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load trusted audiences'));
		}
	};

	onMount(async () => {
		await reload();
		loaded = true;
	});

	const openAdd = () => {
		editingId = null;
		form = emptyForm();
		showEditor = true;
	};

	const openEdit = (row: TrustedAudience) => {
		editingId = row.id;
		form = {
			idp_type: row.idp_type,
			audience: row.audience,
			tenant_id: row.tenant_id || '',
			issuer: row.issuer || '',
			name: row.name || '',
			enabled: row.enabled,
			auto_provision: row.auto_provision,
			default_role: row.default_role,
			default_group_ids: row.default_group_ids || null
		};
		showEditor = true;
	};

	const cancel = () => {
		showEditor = false;
	};

	const save = async () => {
		if (!form.audience?.trim()) {
			toast.error($i18n.t('Audience is required'));
			return;
		}
		saving = true;
		try {
			if (editingId) {
				await updateTrustedAudience(localStorage.token, editingId, form);
			} else {
				await createTrustedAudience(localStorage.token, form);
			}
			toast.success($i18n.t('Saved'));
			showEditor = false;
			await reload();
			saveHandler();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Save failed'));
		} finally {
			saving = false;
		}
	};

	const remove = async (row: TrustedAudience) => {
		const label = row.name || row.audience.slice(0, 12);
		if (!confirm($i18n.t('Remove trusted audience "{{name}}"?', { name: label }))) return;
		try {
			await deleteTrustedAudience(localStorage.token, row.id);
			toast.success($i18n.t('Deleted'));
			await reload();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Delete failed'));
		}
	};

	const idpLabel = (t: IdpType) => (t === 'entra' ? 'Microsoft Entra' : 'Google');
</script>

{#if !loaded}
	<div class="flex items-center justify-center py-6">
		<Spinner />
	</div>
{:else}
	<!-- 헤더: 타이틀 + 추가 버튼 -->
	<div class="flex justify-between items-center">
		<div class="font-medium">{$i18n.t('Trusted Audiences')}</div>
		<Tooltip content={$i18n.t('Add Trusted Audience')}>
			<button
				class="px-1"
				type="button"
				aria-label={$i18n.t('Add Trusted Audience')}
				data-testid="add-trusted-audience"
				on:click={openAdd}
			>
				<Plus />
			</button>
		</Tooltip>
	</div>

	<hr class="border-gray-100 dark:border-gray-850 my-2" />

	<p class="text-xs text-[var(--cloo-text-muted)] mb-3">
		{$i18n.t(
			'Register Entra / Google OAuth audiences whose ID tokens can be passed to Cloosphere API via Authorization: Bearer <id_token>. Unregistered audiences are rejected.'
		)}
	</p>

	<div class="flex flex-col gap-1.5">
		{#each items as row (row.id)}
			<div class="flex w-full gap-2 items-center">
				<div class="flex-1 flex items-center gap-2 min-w-0">
					<span class="text-sm truncate">
						{row.name || $i18n.t('(unnamed)')}
					</span>
					<span class="text-xs text-gray-400 dark:text-gray-500 shrink-0">
						{idpLabel(row.idp_type)}
					</span>
					<span
						class="text-xs font-mono text-[var(--cloo-text-muted)] truncate"
						title={row.audience}
					>
						{row.audience.slice(0, 20)}…
					</span>
					{#if !row.enabled}
						<span class="text-xs text-red-500 shrink-0">{$i18n.t('disabled')}</span>
					{/if}
					{#if row.auto_provision}
						<span class="text-xs text-[var(--cloo-color-info)] shrink-0"
							>{$i18n.t('auto-provision')}</span
						>
					{/if}
				</div>
				<Tooltip content={$i18n.t('Configure')} className="self-center">
					<button
						class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition"
						type="button"
						aria-label={$i18n.t('Configure')}
						data-testid="edit-trusted-audience"
						on:click={() => openEdit(row)}
					>
						<Cog6 />
					</button>
				</Tooltip>
				<Tooltip content={$i18n.t('Delete')} className="self-center">
					<button
						class="p-1 bg-transparent hover:bg-gray-100 dark:bg-gray-900 dark:hover:bg-gray-850 rounded-lg transition text-red-500"
						type="button"
						aria-label={$i18n.t('Delete')}
						data-testid="delete-trusted-audience"
						on:click={() => remove(row)}
					>
						<GarbageBin />
					</button>
				</Tooltip>
			</div>
		{:else}
			<div class="text-xs text-gray-400 dark:text-gray-500 text-center py-3">
				{$i18n.t('No trusted audiences configured.')}
			</div>
		{/each}
	</div>
{/if}

{#if showEditor}
	<!-- 인라인 에디터 (모달 대신) — 다른 섹션 스타일과 맞춤 -->
	<div
		class="mt-4 p-4 border border-[var(--cloo-border-default)] rounded-lg flex flex-col gap-3"
	>
		<div class="text-sm font-medium">
			{editingId ? $i18n.t('Edit Trusted Audience') : $i18n.t('New Trusted Audience')}
		</div>

		<div class="grid grid-cols-1 md:grid-cols-2 gap-3">
			<!-- IDP -->
			<div class="flex flex-col gap-1.5 w-full">
				<FieldLabel label={$i18n.t('IDP')} hint={$i18n.t('Identity provider issuing the ID tokens.')} size="md" />
				<Selector
					value={form.idp_type}
					items={idpItems}
					size="md"
					on:change={(e) => (form.idp_type = e.detail.value)}
				/>
				</div>

			<!-- Label -->
			<div class="flex flex-col gap-1.5 w-full">
				<FieldLabel label={$i18n.t('Label')} hint={$i18n.t('Admin-friendly name for this audience.')} size="md" />
				<Input bind:value={form.name} placeholder="Customer App Prod" size="md" />
				</div>

			<!-- Audience -->
			<div class="flex flex-col gap-1.5 w-full">
				<FieldLabel label={$i18n.t('Audience (aud)')} hint={$i18n.t('Entra application (client) ID or Google OAuth client ID.')} size="md" />
				<Input
					bind:value={form.audience}
					placeholder="00000000-0000-0000-0000-000000000000"
					size="md"
				/>
				</div>

			{#if form.idp_type === 'entra'}
				<!-- Tenant ID -->
				<div class="flex flex-col gap-1.5 w-full">
					<FieldLabel label={$i18n.t('Tenant ID')} hint={$i18n.t('Entra tenant GUID. Leave empty to allow any tenant.')} size="md" />
					<Input
						bind:value={form.tenant_id}
						placeholder="00000000-0000-0000-0000-000000000000"
						size="md"
					/>
				</div>
			{/if}

			<!-- Issuer -->
			<div class="flex flex-col gap-1.5 w-full">
				<FieldLabel label={$i18n.t('Issuer (optional override)')} hint={$i18n.t('Custom issuer URL. Leave empty to auto-compute from IDP + tenant.')} size="md" />
				<Input bind:value={form.issuer} placeholder="" size="md" />
				</div>

			<!-- Default Role -->
			<div class="flex flex-col gap-1.5 w-full">
				<FieldLabel label={$i18n.t('Default Role (auto-provision)')} hint={$i18n.t('Role assigned to auto-provisioned users.')} size="md" />
				<Selector
					value={form.default_role}
					items={roleItems}
					size="md"
					on:change={(e) => (form.default_role = e.detail.value)}
				/>
				</div>
		</div>

		<div class="flex flex-wrap gap-6 pt-2">
			<div class="flex items-center gap-2 text-sm">
				<Switch bind:state={form.enabled} />
				<span>{$i18n.t('Enabled')}</span>
			</div>
			<div class="flex items-center gap-2 text-sm">
				<Switch bind:state={form.auto_provision} />
				<span>{$i18n.t('Auto-provision unknown users')}</span>
			</div>
		</div>

		<p class="text-xs text-[var(--cloo-text-muted)]">
			{$i18n.t(
				'Auto-provision: if a valid token is received for a user not yet in Cloosphere, create them automatically with the default role.'
			)}
		</p>

		<div class="flex justify-end gap-2 pt-1">
			<Button kind="outlined" size="md" on:click={cancel}>{$i18n.t('Cancel')}</Button>
			<Button kind="filled" size="md" disabled={saving} on:click={save}>
				{$i18n.t('Save')}
			</Button>
		</div>
	</div>
{/if}
