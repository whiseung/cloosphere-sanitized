<script>
	import { toast } from 'svelte-sonner';
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	import { deleteGroupById, updateGroupById } from '$lib/apis/groups';

	import Pencil from '$lib/components/icons/Pencil.svelte';
	import User from '$lib/components/icons/User.svelte';
	import Building from '$lib/components/icons/Building.svelte';
	import UserCircleSolid from '$lib/components/icons/UserCircleSolid.svelte';
	import GroupModal from './EditGroupModal.svelte';

	export let users = [];
	export let groups = [];
	export let orgUnits = [];
	export let group = {
		name: 'Admins',
		user_ids: [1, 2, 3]
	};

	export let setGroups = () => {};

	// 다른 그룹에 할당된 조직 단위 ID 계산 (현재 그룹 제외)
	$: assignedOrgUnitIds = groups
		.filter((g) => g.id !== group.id)
		.flatMap((g) => g.meta?.org_unit_ids ?? []);

	let showEdit = false;
	let initialTab = 'general';

	const openModal = (tab) => {
		initialTab = tab;
		showEdit = true;
	};

	const updateHandler = async (_group) => {
		const res = await updateGroupById(localStorage.token, group.id, _group).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Group updated successfully'));
			setGroups();
		}
	};

	const deleteHandler = async () => {
		const res = await deleteGroupById(localStorage.token, group.id).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Group deleted successfully'));
			setGroups();
		}
	};
</script>

<GroupModal
	bind:show={showEdit}
	bind:selectedTab={initialTab}
	edit
	{users}
	{group}
	{orgUnits}
	{assignedOrgUnitIds}
	onSubmit={updateHandler}
	onDelete={deleteHandler}
/>

<div class="flex items-center gap-3 px-1 text-xs transition">
	<button
		class="flex items-center gap-1.5 flex-[2] font-medium hover:text-gray-600 dark:hover:text-gray-300 transition"
		on:click={() => openModal('general')}
	>
		<div>
			<UserCircleSolid className="size-4" />
		</div>
		{group.name}
	</button>

	<button
		class="flex items-center gap-1.5 flex-1 font-medium hover:text-gray-600 dark:hover:text-gray-300 transition"
		on:click={() => openModal('organizations')}
	>
		{(group.meta?.org_unit_ids ?? []).length}
		<div>
			<Building className="size-3.5" />
		</div>
	</button>

	<button
		class="flex items-center gap-1.5 flex-1 font-medium hover:text-gray-600 dark:hover:text-gray-300 transition"
		on:click={() => openModal('users')}
	>
		{group.user_ids.length}
		<div>
			<User className="size-3.5" />
		</div>
	</button>

	<div class="w-8 flex justify-end">
		<button
			class="rounded-lg p-1 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			on:click={() => openModal('general')}
		>
			<Pencil className="size-3.5" />
		</button>
	</div>
</div>
