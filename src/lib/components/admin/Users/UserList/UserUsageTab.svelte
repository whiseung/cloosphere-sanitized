<script lang="ts">
	import { getContext, onMount } from 'svelte';
	const i18n: any = getContext('i18n');

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import { getUserUsageByModel, type UsageByModelEntry } from '$lib/apis/users';

	export let userId: string = '';

	type Period = 'today' | 'week' | 'month';
	const PERIODS: Period[] = ['today', 'week', 'month'];

	let period: Period = 'today';
	let entries: UsageByModelEntry[] = [];
	let loading = false;
	let initialLoadDone = false;

	const periodLabels: Record<Period, string> = {
		today: $i18n.t('Today'),
		week: $i18n.t('Last 7 days'),
		month: $i18n.t('Last 30 days')
	};

	const load = async () => {
		if (!userId) return;
		loading = true;
		try {
			entries = await getUserUsageByModel(localStorage.token, userId, period);
		} catch {
			entries = [];
		}
		loading = false;
		initialLoadDone = true;
	};

	const setPeriod = async (p: Period) => {
		if (p === period) return;
		period = p;
		await load();
	};

	const formatPct = (used: number, limit: number): string => {
		if (!limit) return '';
		return `${Math.min(999, Math.round((used / limit) * 100))}%`;
	};

	const formatLimit = (limit: number): string => {
		if (limit === 0) return $i18n.t('Unlimited');
		return limit.toLocaleString();
	};

	$: if (userId) {
		void load();
	}

	onMount(() => {
		if (userId) void load();
	});
</script>

<div class="flex flex-col gap-3 text-sm">
	<div class="flex items-center gap-1">
		{#each PERIODS as p (p)}
			<Button
				kind={period === p ? 'filled' : 'text'}
				size="sm"
				disabled={loading}
				on:click={() => void setPeriod(p)}
			>
				{periodLabels[p]}
			</Button>
		{/each}
	</div>

	<div class="relative min-h-[16rem]">
		{#if !initialLoadDone}
			<div class="flex justify-center py-10">
				<Spinner />
			</div>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-xs">
					<thead
						class="text-center text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-850"
					>
						<tr>
							<th class="py-1.5 px-2 font-medium w-36">{$i18n.t('Model')}</th>
							<th class="py-1.5 px-2 font-medium whitespace-nowrap w-28">{$i18n.t('Used')}</th>
							<th class="py-1.5 px-2 font-medium whitespace-nowrap w-28">
								{$i18n.t('Daily limit')}
							</th>
							<th class="py-1.5 px-2 font-medium w-40">{$i18n.t('Usage rate')}</th>
						</tr>
					</thead>
					<tbody>
						{#if entries.length === 0}
							<tr>
								<td colspan="4" class="text-center text-gray-500 dark:text-gray-400 py-6">
									{$i18n.t('No usage recorded for this period.')}
								</td>
							</tr>
						{:else}
							{#each entries as e (e.model_id)}
								{@const pct = e.limit > 0 ? Math.min(100, (e.used / e.limit) * 100) : 0}
								<tr class="border-b border-gray-50 dark:border-gray-850/50">
									<td class="py-1.5 px-2 w-36 max-w-36">
										<div class="flex flex-col min-w-0">
											<span class="font-medium truncate" title={e.name}>{e.name}</span>
											<span class="text-gray-400 dark:text-gray-500 truncate" title={e.model_id}>
												{e.model_id}{e.is_agent ? ' · ' + $i18n.t('agent') : ''}
											</span>
										</div>
									</td>
									<td class="py-1.5 px-2 text-right tabular-nums whitespace-nowrap w-28">
										{e.used.toLocaleString()}
									</td>
									<td class="py-1.5 px-2 text-right tabular-nums whitespace-nowrap w-28">
										{#if period === 'today'}
											{formatLimit(e.limit)}
										{:else}
											<span class="text-gray-400 dark:text-gray-500">—</span>
										{/if}
									</td>
									<td class="py-1.5 px-2 text-right w-40">
										{#if period === 'today' && e.limit > 0}
											<div class="flex items-center justify-between gap-1.5 whitespace-nowrap">
												<div
													class="w-20 h-1.5 rounded bg-gray-100 dark:bg-gray-850 overflow-hidden flex-shrink-0"
												>
													<div
														class="h-full {pct >= 95
															? 'bg-red-500'
															: pct >= 80
																? 'bg-yellow-500'
																: 'bg-blue-500'}"
														style="width: {pct}%"
													></div>
												</div>
												<span
													class="text-gray-500 dark:text-gray-400 tabular-nums flex-shrink-0"
												>
													{formatPct(e.used, e.limit)}
												</span>
											</div>
										{:else}
											<span class="text-gray-400 dark:text-gray-500">—</span>
										{/if}
									</td>
								</tr>
							{/each}
						{/if}
					</tbody>
				</table>
			</div>

			{#if loading}
				<div
					class="absolute inset-0 flex justify-center items-start pt-10 bg-white/60 dark:bg-gray-900/60 pointer-events-none"
				>
					<Spinner />
				</div>
			{/if}
		{/if}
	</div>
</div>
