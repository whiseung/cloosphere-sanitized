<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext, onMount, createEventDispatcher } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user } from '$lib/stores';
	import { getGroups } from '$lib/apis/groups';
	import {
		getOrganizations,
		getOrganizationalUnitsTree,
		type OrganizationalUnit
	} from '$lib/apis/organizations';

	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Card from '$lib/components/common/Card.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import ArrowLeft from '$lib/components/icons/ArrowLeft.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import Building from '$lib/components/icons/Building.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	type AccessGroup = { id: string; name: string };
	type AccessControlT = {
		read: { group_ids: string[]; user_ids: string[]; org_unit_ids: string[] };
		write: { group_ids: string[]; user_ids: string[]; org_unit_ids: string[] };
	} | null;

	// --- Config props ---
	export let title = '';
	export let nameLabel = '';
	export let namePlaceholder = '';
	export let descriptionLabel = '';
	export let descriptionPlaceholder = '';
	export let backHref = '';
	export let allowPublic = false;
	export let saveLabel = '';
	export let descriptionRequired = true;

	// --- Bindable state (parent may read/set, e.g. JSON import) ---
	export let loading = false;
	export let name = '';
	export let description = '';

	const emptyAcl = (): NonNullable<AccessControlT> => ({
		read: { group_ids: [], user_ids: [$user?.id ?? ''], org_unit_ids: [] },
		write: { group_ids: [], user_ids: [$user?.id ?? ''], org_unit_ids: [] }
	});

	export let accessControl: AccessControlT = emptyAcl();

	$: computedSaveLabel = saveLabel || $i18n.t('Save & Update');
	$: isPublic = accessControl === null;

	let groups: AccessGroup[] = [];
	let orgUnits: OrganizationalUnit[] = [];

	// Flatten the org unit tree so we can render and search them in a flat list.
	function flattenOrgUnits(units: OrganizationalUnit[], prefix = ''): OrganizationalUnit[] {
		let result: OrganizationalUnit[] = [];
		for (const u of units) {
			const displayName = prefix
				? `${prefix} / ${u.display_name ?? u.name}`
				: (u.display_name ?? u.name);
			result.push({ ...u, display_name: displayName });
			if (u.children?.length) {
				result = result.concat(flattenOrgUnits(u.children, displayName));
			}
		}
		return result;
	}

	onMount(async () => {
		try {
			groups = ((await getGroups(localStorage.token)) ?? []) as AccessGroup[];
			const orgs = (await getOrganizations(localStorage.token)) ?? [];
			let collected: OrganizationalUnit[] = [];
			for (const org of orgs) {
				const tree = await getOrganizationalUnitsTree(localStorage.token, org.id);
				collected = collected.concat(flattenOrgUnits((tree as OrganizationalUnit[]) ?? []));
			}
			orgUnits = collected;
		} catch (err) {
			console.warn('Failed to load groups/org units', err);
		}
	});

	// Permission Selector — "Private" (access_control set) or "Public" (null).
	const permissionItems = () =>
		[
			{ value: 'private', label: $i18n.t('Private') },
			...(allowPublic ? [{ value: 'public', label: $i18n.t('Public') }] : [])
		] as { value: string; label: string }[];

	const handlePermissionChange = (e: CustomEvent<{ value: string | number }>) => {
		const next = String(e.detail.value);
		if (next === 'public') {
			accessControl = null;
		} else if (accessControl === null) {
			accessControl = emptyAcl();
		}
	};

	// Role: 'view' means read-only, 'edit' means read + write.
	const roleOf = (id: string, kind: 'group' | 'orgUnit'): 'view' | 'edit' => {
		if (!accessControl) return 'view';
		const key = kind === 'group' ? 'group_ids' : 'org_unit_ids';
		return accessControl.write[key].includes(id) ? 'edit' : 'view';
	};

	const setRole = (id: string, kind: 'group' | 'orgUnit', role: 'view' | 'edit') => {
		if (!accessControl) return;
		const key = kind === 'group' ? 'group_ids' : 'org_unit_ids';
		const inRead = accessControl.read[key].includes(id);
		const inWrite = accessControl.write[key].includes(id);
		if (role === 'edit') {
			if (!inRead) accessControl.read[key] = [...accessControl.read[key], id];
			if (!inWrite) accessControl.write[key] = [...accessControl.write[key], id];
		} else {
			if (!inRead) accessControl.read[key] = [...accessControl.read[key], id];
			if (inWrite) accessControl.write[key] = accessControl.write[key].filter((x) => x !== id);
		}
		accessControl = accessControl; // trigger reactivity
	};

	const addEntity = (id: string, kind: 'group' | 'orgUnit') => {
		if (!id) return;
		if (!accessControl) accessControl = emptyAcl();
		const key = kind === 'group' ? 'group_ids' : 'org_unit_ids';
		if (!accessControl.read[key].includes(id)) {
			accessControl.read[key] = [...accessControl.read[key], id];
		}
		accessControl = accessControl;
	};

	const removeEntity = (id: string, kind: 'group' | 'orgUnit') => {
		if (!accessControl) return;
		const key = kind === 'group' ? 'group_ids' : 'org_unit_ids';
		accessControl.read[key] = accessControl.read[key].filter((x) => x !== id);
		accessControl.write[key] = accessControl.write[key].filter((x) => x !== id);
		accessControl = accessControl;
	};

	$: addedGroupIds = accessControl
		? Array.from(new Set([...accessControl.read.group_ids, ...accessControl.write.group_ids]))
		: [];
	$: addedOrgUnitIds = accessControl
		? Array.from(new Set([...accessControl.read.org_unit_ids, ...accessControl.write.org_unit_ids]))
		: [];

	$: availableGroups = groups.filter((g) => !addedGroupIds.includes(g.id));
	$: availableOrgUnits = orgUnits.filter((u) => !addedOrgUnitIds.includes(u.id));

	const handleAddGroup = (e: CustomEvent<{ value: string | number }>) => {
		addEntity(String(e.detail.value), 'group');
	};
	const handleAddOrgUnit = (e: CustomEvent<{ value: string | number }>) => {
		addEntity(String(e.detail.value), 'orgUnit');
	};

	const handleRoleChange =
		(id: string, kind: 'group' | 'orgUnit') => (e: CustomEvent<{ value: string | number }>) => {
			setRole(id, kind, String(e.detail.value) as 'view' | 'edit');
		};

	const roleItems = () => [
		{ value: 'view', label: $i18n.t('Read') },
		{ value: 'edit', label: $i18n.t('Write') }
	];

	const groupNameById = (id: string) => groups.find((g) => g.id === id)?.name ?? id;
	const orgUnitNameById = (id: string): string => {
		const u = orgUnits.find((x) => x.id === id);
		return String(u?.display_name ?? u?.name ?? id);
	};
	const orgUnitLabel = (u: OrganizationalUnit): string => String(u.display_name ?? u.name);

	const goBack = () => {
		dispatch('cancel');
		if (backHref) goto(backHref);
	};

	const submit = () => {
		if (loading) return;
		if (name.trim() === '' || (descriptionRequired && description.trim() === '')) {
			toast.error($i18n.t('Please fill in all fields.'));
			return;
		}
		dispatch('submit', { name, description, accessControl });
	};
</script>

<div class="cloo-create-scaffold w-full max-w-[860px] mx-auto px-8 py-8 flex flex-col gap-4">
	<!-- Header: back + title + (actions-prefix) + Cancel + Save & Update -->
	<div class="flex items-center justify-between gap-2">
		<div class="flex flex-1 items-center gap-2.5 min-w-0">
			<button
				type="button"
				class="p-1 rounded hover:bg-[var(--cloo-surface-hover)]"
				aria-label={$i18n.t('Back')}
				on:click={goBack}
			>
				<ArrowLeft className="size-5" strokeWidth="2" />
			</button>
			<h1 class="text-3xl font-semibold text-[var(--cloo-text-primary)] truncate">
				{title}
			</h1>
		</div>
		<div class="flex items-center gap-2 shrink-0">
			<slot name="actions-prefix" />
			<Button kind="outlined" size="md" type="button" on:click={goBack}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" type="button" {loading} disabled={loading} on:click={submit}>
				{computedSaveLabel}
			</Button>
		</div>
	</div>

	<div class="h-px bg-[var(--cloo-border-subtle)] w-full" />

	<!-- Inputs -->
	<div class="flex flex-col gap-4">
		<Input label={nameLabel} required size="sm" placeholder={namePlaceholder} bind:value={name} />
		<Textarea
			label={descriptionLabel}
			required={descriptionRequired}
			size="sm"
			rows={4}
			placeholder={descriptionPlaceholder}
			bind:value={description}
		/>
	</div>

	<!-- Optional resource-specific fields -->
	<slot />

	<div class="h-px bg-[var(--cloo-border-default)] w-full my-2" />

	<!-- Permission card -->
	<Card padding="none">
		<div class="px-6 py-3">
			<LabelBase
				label={$i18n.t('Permission')}
				caption={$i18n.t('Only users and groups with permission can access')}
				size="md"
			>
				<svelte:fragment slot="right">
					<div class="w-[140px]">
						<Selector
							value={isPublic ? 'public' : 'private'}
							items={permissionItems()}
							size="sm"
							on:change={handlePermissionChange}
						/>
					</div>
				</svelte:fragment>
			</LabelBase>
		</div>
	</Card>

	{#if !isPublic && accessControl}
		<!-- Groups card -->
		<Card padding="none">
			<div class="px-6 py-3">
				<LabelBase label={$i18n.t('Groups')} size="md">
					<svelte:fragment slot="right">
						<div class="w-[200px]">
							<Selector
								value=""
								items={availableGroups.map((g) => ({ value: g.id, label: g.name }))}
								size="sm"
								placeholder={$i18n.t('Add groups')}
								on:change={handleAddGroup}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>

			{#if addedGroupIds.length > 0}
				<div class="border-t border-[var(--cloo-border-default)] py-2">
					{#each addedGroupIds as gid (gid)}
						<div class="flex items-center justify-between px-6 py-1">
							<div class="flex items-center gap-1 min-w-0">
								<UserCircleSolid className="size-5 shrink-0" />
								<span class="text-sm text-[var(--cloo-text-primary)] truncate">
									{groupNameById(gid)}
								</span>
							</div>
							<div class="flex items-center gap-3.5 shrink-0">
								<div class="w-[120px]">
									<Selector
										value={roleOf(gid, 'group')}
										items={roleItems()}
										size="sm"
										on:change={handleRoleChange(gid, 'group')}
									/>
								</div>
								<button
									type="button"
									class="p-1 rounded hover:bg-[var(--cloo-surface-hover)]"
									aria-label={$i18n.t('Remove')}
									on:click={() => removeEntity(gid, 'group')}
								>
									<XMark className="size-4" strokeWidth="2" />
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</Card>

		<!-- Organizational Units card -->
		<Card padding="none">
			<div class="px-6 py-3">
				<LabelBase label={$i18n.t('Organizational Units')} size="md">
					<svelte:fragment slot="right">
						<div class="w-[220px]">
							<Selector
								value=""
								items={availableOrgUnits.map((u) => ({ value: u.id, label: orgUnitLabel(u) }))}
								size="sm"
								placeholder={$i18n.t('Add organizational units')}
								on:change={handleAddOrgUnit}
							/>
						</div>
					</svelte:fragment>
				</LabelBase>
			</div>

			{#if addedOrgUnitIds.length > 0}
				<div class="border-t border-[var(--cloo-border-default)] py-2">
					{#each addedOrgUnitIds as oid (oid)}
						<div class="flex items-center justify-between px-6 py-1">
							<div class="flex items-center gap-1 min-w-0">
								<Building className="size-5 shrink-0" />
								<span class="text-sm text-[var(--cloo-text-primary)] truncate">
									{orgUnitNameById(oid)}
								</span>
							</div>
							<div class="flex items-center gap-3.5 shrink-0">
								<div class="w-[120px]">
									<Selector
										value={roleOf(oid, 'orgUnit')}
										items={roleItems()}
										size="sm"
										on:change={handleRoleChange(oid, 'orgUnit')}
									/>
								</div>
								<button
									type="button"
									class="p-1 rounded hover:bg-[var(--cloo-surface-hover)]"
									aria-label={$i18n.t('Remove')}
									on:click={() => removeEntity(oid, 'orgUnit')}
								>
									<XMark className="size-4" strokeWidth="2" />
								</button>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</Card>
	{/if}
</div>
