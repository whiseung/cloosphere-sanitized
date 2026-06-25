<script lang="ts">
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let value: string = '0 9 * * *';

	const presets = [
		{ cron: '0 9 * * *', label: 'Daily at 9 AM' },
		{ cron: '0 9 * * 1-5', label: 'Weekdays at 9 AM' },
		{ cron: '0 9 * * 1', label: 'Weekly on Monday' },
		{ cron: '0 9 1 * *', label: 'Monthly on 1st' },
		{ cron: '0 * * * *', label: 'Every hour' }
	];

	let isCustom = !presets.some((p) => p.cron === value);
	let selectedPreset = isCustom ? 'custom' : value;

	function handlePresetChange() {
		if (selectedPreset === 'custom') {
			isCustom = true;
		} else {
			isCustom = false;
			value = selectedPreset;
		}
	}
</script>

<div class="flex flex-col gap-2">
	<select
		class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
		bind:value={selectedPreset}
		on:change={handlePresetChange}
	>
		{#each presets as preset}
			<option value={preset.cron}>{$i18n.t(preset.label)} ({preset.cron})</option>
		{/each}
		<option value="custom">{$i18n.t('Custom')}</option>
	</select>

	{#if isCustom}
		<input
			type="text"
			class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
			bind:value
			placeholder="* * * * *"
		/>
		<p class="text-xs text-gray-500 dark:text-gray-400">
			{$i18n.t('Format: minute hour day month weekday')}
		</p>
	{/if}
</div>
