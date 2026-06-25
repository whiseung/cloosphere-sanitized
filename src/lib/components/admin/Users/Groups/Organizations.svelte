<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import Building from '$lib/components/icons/Building.svelte';

	import type { OrganizationalUnit } from '$lib/apis/organizations';

	export let orgUnits: OrganizationalUnit[] = [];
	export let orgUnitIds: string[] = [];

	/** 다른 그룹에 이미 할당된 org unit ID 목록 */
	export let assignedOrgUnitIds: string[] = [];

	let query = '';

	let filteredUnits: OrganizationalUnit[] = [];

	$: filteredUnits = orgUnits
		.filter((unit) => {
			// 다른 그룹에 이미 할당된 조직은 제외 (현재 그룹에 할당된 것은 표시)
			if (!orgUnitIds.includes(unit.id) && assignedOrgUnitIds.includes(unit.id)) {
				return false;
			}

			if (query === '') {
				return true;
			}

			const q = query.toLowerCase();
			return (
				unit.name.toLowerCase().includes(q) ||
				(unit.display_name ?? '').toLowerCase().includes(q) ||
				(unit.description ?? '').toLowerCase().includes(q)
			);
		})
		.sort((a, b) => {
			const aSelected = orgUnitIds.includes(a.id);
			const bSelected = orgUnitIds.includes(b.id);

			// 선택된 항목 우선 정렬
			if (aSelected && !bSelected) return -1;
			if (bSelected && !aSelected) return 1;

			// 같은 상태면 이름순
			return a.name.localeCompare(b.name);
		});
</script>

<div>
	<div class="flex w-full">
		<div class="flex flex-1">
			<div class="self-center mr-3">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-4 h-4"
				>
					<path
						fill-rule="evenodd"
						d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z"
						clip-rule="evenodd"
					/>
				</svg>
			</div>
			<input
				class="w-full text-sm pr-4 rounded-r-xl outline-hidden bg-transparent"
				bind:value={query}
				placeholder={$i18n.t('Search Organizations')}
			/>
		</div>
	</div>

	<div class="mt-3 max-h-[22rem] overflow-y-auto scrollbar-hidden">
		<div class="flex flex-col gap-2.5">
			{#if filteredUnits.length > 0}
				{#each filteredUnits as unit (unit.id)}
					<div class="flex flex-row items-center gap-3 w-full text-sm">
						<div class="flex items-center">
							<Checkbox
								state={orgUnitIds.includes(unit.id) ? 'checked' : 'unchecked'}
								on:change={(e) => {
									if (e.detail === 'checked') {
										orgUnitIds = [...orgUnitIds, unit.id];
									} else {
										orgUnitIds = orgUnitIds.filter((id) => id !== unit.id);
									}
								}}
							/>
						</div>

						<div class="flex w-full items-center justify-between">
							<div class="flex items-center gap-2">
								<Building className="size-4 flex-shrink-0" />
								<div>
									<div class="font-medium">{unit.display_name || unit.name}</div>
									{#if unit.display_name && unit.display_name !== unit.name}
										<div class="text-xs text-gray-500">{unit.name}</div>
									{/if}
								</div>
							</div>

							<div class="flex items-center gap-1.5">
								{#if unit.member_ids && unit.member_ids.length > 0}
									<span class="text-xs text-gray-500">
										{unit.member_ids.length} {$i18n.t('members')}
									</span>
								{/if}
								{#if orgUnitIds.includes(unit.id)}
									<Badge status="success" size="sm" content={$i18n.t('Assigned')} />
								{/if}
							</div>
						</div>
					</div>
				{/each}
			{:else}
				<div class="text-gray-500 text-xs text-center py-2 px-10">
					{$i18n.t('No organizational units found.')}
				</div>
			{/if}
		</div>
	</div>
</div>
