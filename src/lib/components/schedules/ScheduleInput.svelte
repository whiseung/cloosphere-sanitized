<script lang="ts">
	import { getContext } from 'svelte';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Selector from '$lib/components/common/Selector.svelte';

	const i18n = getContext('i18n');

	export let cronExpression: string = '0 9 * * *';
	export let timezone: string = 'UTC';
	export let startAt: number | null = null;
	export let endAt: number | null = null;

	type Frequency = 'interval' | 'hourly' | 'daily' | 'weekly' | 'monthly' | 'custom';

	let frequency: Frequency = 'daily';
	let hour = 9;
	let minute = 0;
	let intervalMinutes = 30;
	let selectedWeekdays: Set<number> = new Set([1]); // 1=Mon
	let monthDay = 1;
	let startDateStr = '';
	let endDateStr = '';
	let useEndDate = false;
	let customCron = '';

	// Weekday labels
	const weekdays = [
		{ value: 1, label: 'Mon' },
		{ value: 2, label: 'Tue' },
		{ value: 3, label: 'Wed' },
		{ value: 4, label: 'Thu' },
		{ value: 5, label: 'Fri' },
		{ value: 6, label: 'Sat' },
		{ value: 0, label: 'Sun' }
	];

	// Parse initial cron on mount
	parseCron(cronExpression);
	if (startAt) startDateStr = toLocalDateStr(startAt);
	if (endAt) {
		endDateStr = toLocalDateStr(endAt);
		useEndDate = true;
	}

	function parseCron(cron: string) {
		const parts = cron.split(' ');
		if (parts.length !== 5) {
			frequency = 'custom';
			customCron = cron;
			return;
		}
		const [m, h, dom, , dow] = parts;

		// Detect interval pattern: */N * * * *
		if (m.startsWith('*/') && h === '*' && dom === '*' && dow === '*') {
			frequency = 'interval';
			intervalMinutes = parseInt(m.slice(2)) || 30;
		} else if (m !== '*' && h === '*' && dom === '*' && dow === '*') {
			frequency = 'hourly';
			minute = isNaN(parseInt(m)) ? 0 : parseInt(m);
		} else if (m !== '*' && h !== '*' && dom === '*' && dow === '*') {
			frequency = 'daily';
			minute = isNaN(parseInt(m)) ? 0 : parseInt(m);
			hour = isNaN(parseInt(h)) ? 9 : parseInt(h);
		} else if (m !== '*' && h !== '*' && dom === '*' && dow !== '*') {
			frequency = 'weekly';
			minute = isNaN(parseInt(m)) ? 0 : parseInt(m);
			hour = isNaN(parseInt(h)) ? 9 : parseInt(h);
			selectedWeekdays = new Set(
				dow.includes('-')
					? expandRange(dow)
					: dow
							.split(',')
							.map((d) => parseInt(d))
							.filter((d) => !isNaN(d))
			);
			if (selectedWeekdays.size === 0) selectedWeekdays = new Set([1]);
		} else if (m !== '*' && h !== '*' && dom !== '*' && dow === '*') {
			frequency = 'monthly';
			minute = isNaN(parseInt(m)) ? 0 : parseInt(m);
			hour = isNaN(parseInt(h)) ? 9 : parseInt(h);
			monthDay = parseInt(dom) || 1;
		} else {
			frequency = 'custom';
			customCron = cron;
		}
	}

	function expandRange(rangeStr: string): number[] {
		const [start, end] = rangeStr.split('-').map((n) => parseInt(n));
		if (isNaN(start) || isNaN(end)) return [1];
		const result: number[] = [];
		for (let i = start; i <= end; i++) result.push(i);
		return result;
	}

	function toggleWeekday(day: number) {
		const next = new Set(selectedWeekdays);
		if (next.has(day)) {
			if (next.size > 1) next.delete(day);
		} else {
			next.add(day);
		}
		selectedWeekdays = next;
	}

	function buildCron(): string {
		switch (frequency) {
			case 'interval':
				return `*/${intervalMinutes} * * * *`;
			case 'hourly':
				return `${minute} * * * *`;
			case 'daily':
				return `${minute} ${hour} * * *`;
			case 'weekly': {
				const days = [...selectedWeekdays].sort((a, b) => a - b).join(',');
				return `${minute} ${hour} * * ${days}`;
			}
			case 'monthly':
				return `${minute} ${hour} ${monthDay} * *`;
			case 'custom':
				return customCron || '0 9 * * *';
		}
	}

	function toLocalDateStr(ts: number): string {
		const d = new Date(ts * 1000);
		return d.toISOString().slice(0, 10);
	}

	function toUnix(dateStr: string): number | null {
		if (!dateStr) return null;
		return Math.floor(new Date(dateStr).getTime() / 1000);
	}

	// Reactive: sync internal state → exported props
	// All dependencies must be listed explicitly — Svelte doesn't track variables inside function calls
	$: frequency,
		hour,
		minute,
		intervalMinutes,
		selectedWeekdays,
		monthDay,
		customCron,
		(cronExpression = buildCron());
	$: startAt = toUnix(startDateStr);
	$: endAt = useEndDate ? toUnix(endDateStr) : null;

	// Hour/minute options
	const hours = Array.from({ length: 24 }, (_, i) => i);
	const allMinutes = Array.from({ length: 60 }, (_, i) => i);
	const intervalOptions = [
		{ value: 1, label: '1' },
		{ value: 2, label: '2' },
		{ value: 3, label: '3' },
		{ value: 5, label: '5' },
		{ value: 10, label: '10' },
		{ value: 15, label: '15' },
		{ value: 20, label: '20' },
		{ value: 30, label: '30' }
	];
	const monthDays = Array.from({ length: 31 }, (_, i) => i + 1);
	$: intervalItems = intervalOptions.map((opt) => ({ value: String(opt.value), label: opt.label }));
	$: minuteItems = allMinutes.map((m) => ({ value: String(m), label: String(m).padStart(2, '0') }));
	$: hourItems = hours.map((h) => ({ value: String(h), label: String(h).padStart(2, '0') }));
	$: monthDayItems = monthDays.map((d) => ({ value: String(d), label: String(d) }));
</script>

<div class="flex flex-col gap-3">
	<!-- Frequency -->
	<div>
		<div class="text-sm mb-2">{$i18n.t('Repeat')}</div>
		<div class="flex flex-wrap gap-1.5">
			{#each [{ value: 'interval', label: 'Every N minutes' }, { value: 'hourly', label: 'Every hour' }, { value: 'daily', label: 'Every day' }, { value: 'weekly', label: 'Every week' }, { value: 'monthly', label: 'Every month' }, { value: 'custom', label: 'Custom' }] as opt}
				<button
					type="button"
					class="px-3 py-1.5 text-sm rounded-lg transition {frequency === opt.value
						? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
						: 'bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
					on:click={() => {
						frequency = opt.value;
					}}
				>
					{$i18n.t(opt.label)}
				</button>
			{/each}
		</div>
	</div>

	<!-- Time selectors based on frequency -->
	{#if frequency === 'interval'}
		<div class="flex items-center gap-2">
			<span class="text-sm dark:text-gray-300">{$i18n.t('Every')}</span>
			<div class="w-[110px]">
				<Selector
					items={intervalItems}
					value={String(intervalMinutes)}
					searchEnabled={false}
					size="md"
					on:change={(e) => {
						intervalMinutes = Number(e.detail.value);
					}}
				/>
			</div>
			<span class="text-sm dark:text-gray-300">{$i18n.t('minutes')}</span>
		</div>
	{:else if frequency === 'hourly'}
		<div class="flex items-center gap-2">
			<span class="text-sm dark:text-gray-300">{$i18n.t('At minute')}</span>
			<div class="w-[110px]">
				<Selector
					items={minuteItems}
					value={String(minute)}
					searchEnabled={false}
					size="md"
					on:change={(e) => {
						minute = Number(e.detail.value);
					}}
				/>
			</div>
		</div>
	{:else if frequency === 'daily'}
		<div class="flex items-center gap-2">
			<span class="text-sm dark:text-gray-300">{$i18n.t('At')}</span>
			<div class="w-[110px]">
				<Selector
					items={hourItems}
					value={String(hour)}
					searchEnabled={false}
					size="md"
					on:change={(e) => {
						hour = Number(e.detail.value);
					}}
				/>
			</div>
			<span class="text-sm dark:text-gray-300">:</span>
			<div class="w-[110px]">
				<Selector
					items={minuteItems}
					value={String(minute)}
					searchEnabled={false}
					size="md"
					on:change={(e) => {
						minute = Number(e.detail.value);
					}}
				/>
			</div>
		</div>
	{:else if frequency === 'weekly'}
		<div class="flex flex-col gap-2">
			<div class="flex flex-wrap gap-1.5">
				{#each weekdays as wd}
					<button
						type="button"
						class="px-3 py-1.5 text-sm rounded-lg transition {selectedWeekdays.has(wd.value)
							? 'bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900'
							: 'bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
						on:click={() => {
							toggleWeekday(wd.value);
						}}
					>
						{$i18n.t(wd.label)}
					</button>
				{/each}
			</div>
			<div class="flex items-center gap-2">
				<span class="text-sm dark:text-gray-300">{$i18n.t('At')}</span>
				<div class="w-[110px]">
					<Selector
						items={hourItems}
						value={String(hour)}
						searchEnabled={false}
						size="md"
						on:change={(e) => {
							hour = Number(e.detail.value);
						}}
					/>
				</div>
				<span class="text-sm dark:text-gray-300">:</span>
				<div class="w-[110px]">
					<Selector
						items={minuteItems}
						value={String(minute)}
						searchEnabled={false}
						size="md"
						on:change={(e) => {
							minute = Number(e.detail.value);
						}}
					/>
				</div>
			</div>
		</div>
	{:else if frequency === 'monthly'}
		<div class="flex flex-col gap-2">
			<div class="flex items-center gap-2">
				<span class="text-sm dark:text-gray-300">{$i18n.t('Day')}</span>
				<div class="w-[110px]">
					<Selector
						items={monthDayItems}
						value={String(monthDay)}
						searchEnabled={false}
						size="md"
						on:change={(e) => {
							monthDay = Number(e.detail.value);
						}}
					/>
				</div>
			</div>
			<div class="flex items-center gap-2">
				<span class="text-sm dark:text-gray-300">{$i18n.t('At')}</span>
				<div class="w-[110px]">
					<Selector
						items={hourItems}
						value={String(hour)}
						searchEnabled={false}
						size="md"
						on:change={(e) => {
							hour = Number(e.detail.value);
						}}
					/>
				</div>
				<span class="text-sm dark:text-gray-300">:</span>
				<div class="w-[110px]">
					<Selector
						items={minuteItems}
						value={String(minute)}
						searchEnabled={false}
						size="md"
						on:change={(e) => {
							minute = Number(e.detail.value);
						}}
					/>
				</div>
			</div>
		</div>
	{:else if frequency === 'custom'}
		<div>
			<input
				type="text"
				class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
				bind:value={customCron}
				placeholder="0 9 * * 1-5"
			/>
			<div class="text-xs text-gray-400 dark:text-gray-500 mt-1.5 space-y-1">
				<p class="font-mono">
					{$i18n.t('Format: minute(0-59) hour(0-23) day(1-31) month(1-12) weekday(0-6, 0=Sun)')}
				</p>
				<p>{$i18n.t('Special characters: * (any) , (list) - (range) / (step)')}</p>
				<p>
					{$i18n.t(
						'Examples: 0 9 * * 1-5 (weekdays 9AM), */30 * * * * (every 30min), 0 9,18 * * * (9AM & 6PM)'
					)}
				</p>
			</div>
		</div>
	{/if}

	<!-- Timezone -->
	<div class="flex items-center gap-2">
		<span class="text-sm dark:text-gray-300">{$i18n.t('Timezone')}</span>
		<input
			type="text"
			class="flex-1 rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
			bind:value={timezone}
		/>
	</div>

	<!-- Period: Start / End -->
	<div class="flex flex-col gap-2">
		<div class="flex items-center gap-2">
			<span class="text-sm dark:text-gray-300 shrink-0">{$i18n.t('Start date')}</span>
			<input
				type="date"
				class="flex-1 rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
				bind:value={startDateStr}
			/>
		</div>

		<div class="flex items-center gap-2">
			<div class="flex items-center gap-1.5 text-sm dark:text-gray-300 shrink-0">
				<Checkbox
					state={useEndDate ? 'checked' : 'unchecked'}
					on:change={(e) => {
						useEndDate = e.detail === 'checked';
					}}
				/>
				<span>{$i18n.t('End date')}</span>
			</div>
			{#if useEndDate}
				<input
					type="date"
					class="flex-1 rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					bind:value={endDateStr}
				/>
			{/if}
		</div>
	</div>

	<!-- Generated cron preview -->
	<div class="text-xs text-gray-400 dark:text-gray-500 font-mono">
		cron: {cronExpression}
	</div>
</div>
