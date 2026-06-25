<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Modal from '$lib/components/common/Modal.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let selectedRange: string = 'yesterday';
	export let customFrom: string = '';
	export let customTo: string = '';

	let showCustomDateModal = false;
	let customDateLabel = '';

	// 초기 로드 시 선택된 기간으로 change 이벤트 발생
	onMount(() => {
		if (selectedRange && selectedRange !== 'custom') {
			selectRange(selectedRange);
		}
	});

	const toDateTimeLocal = (date: Date) => {
		const pad = (n: number) => n.toString().padStart(2, '0');
		return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
	};

	const formatDateTimeLabel = (dateStr: string) => {
		if (!dateStr) return '';
		const date = new Date(dateStr);
		const month = (date.getMonth() + 1).toString().padStart(2, '0');
		const day = date.getDate().toString().padStart(2, '0');
		const hours = date.getHours().toString().padStart(2, '0');
		const minutes = date.getMinutes().toString().padStart(2, '0');
		return `${month}/${day} ${hours}:${minutes}`;
	};

	function selectRange(range: string) {
		if (range === 'custom') {
			const now = new Date();
			const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
			customFrom = toDateTimeLocal(weekAgo);
			customTo = toDateTimeLocal(now);
			customDateLabel = `${formatDateTimeLabel(customFrom)} ~ ${formatDateTimeLabel(customTo)}`;
			showCustomDateModal = true;
			return;
		}

		selectedRange = range;
		const now = new Date();
		let fromStr = '';
		let toStr = '';

		const fmt = (d: Date) => d.toISOString().split('T')[0];

		// $st = 시작일(포함), $ed = 종료일(포함)
		// LLM이 컬럼 타입에 맞게 SQL 템플릿을 생성 (DATE vs TIMESTAMP 처리)
		if (range === 'today') {
			fromStr = fmt(now);
			toStr = fmt(now);
		} else if (range === 'yesterday') {
			const d = new Date(now); d.setDate(d.getDate() - 1);
			fromStr = fmt(d);
			toStr = fmt(d);
		} else if (range === 'this_week') {
			const d = new Date(now); d.setDate(d.getDate() - d.getDay());
			fromStr = fmt(d);
			toStr = fmt(now);
		} else if (range === 'last_week') {
			const d = new Date(now); d.setDate(d.getDate() - d.getDay() - 7);
			fromStr = fmt(d);
			const e = new Date(d); e.setDate(e.getDate() + 6);
			toStr = fmt(e);
		} else if (range === 'this_month') {
			fromStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
			toStr = fmt(now);
		} else if (range === 'last_month') {
			const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
			fromStr = fmt(d);
			const e = new Date(now.getFullYear(), now.getMonth(), 0);
			toStr = fmt(e);
		} else if (range === '7d') {
			const d = new Date(now); d.setDate(d.getDate() - 7);
			fromStr = fmt(d);
			toStr = fmt(now);
		} else if (range === '30d') {
			const d = new Date(now); d.setDate(d.getDate() - 30);
			fromStr = fmt(d);
			toStr = fmt(now);
		}

		if (range === 'all') {
			dispatch('change', { from_value: '', to_value: '' });
		} else {
			dispatch('change', { from_value: fromStr, to_value: toStr });
		}
	}

	function applyCustomDateRange() {
		if (customFrom && customTo) {
			const fromDate = customFrom.split('T')[0];
			const toDate = customTo.split('T')[0];
			customDateLabel = `${formatDateTimeLabel(customFrom)} ~ ${formatDateTimeLabel(customTo)}`;
			selectedRange = 'custom';
			showCustomDateModal = false;
			dispatch('change', { from_value: fromDate, to_value: toDate });
		}
	}
</script>

<div class="flex items-center rounded-lg bg-gray-50 dark:bg-gray-950 p-0.5 gap-0.5">
	{#each [
		{ value: 'today', label: $i18n.t('Today') },
		{ value: 'yesterday', label: $i18n.t('Yesterday') },
		{ value: 'this_week', label: $i18n.t('This Week') },
		{ value: 'last_week', label: $i18n.t('Last Week') },
		{ value: 'this_month', label: $i18n.t('This Month') },
		{ value: 'last_month', label: $i18n.t('Last Month') },
		{ value: '7d', label: '7d' },
		{ value: '30d', label: '30d' },
		{ value: 'all', label: $i18n.t('All') }
	] as opt}
		<button
			class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {selectedRange === opt.value
				? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
				: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
			on:click={() => selectRange(opt.value)}
		>
			{opt.label}
		</button>
	{/each}
	<button
		class="px-3 py-1.5 text-sm font-medium rounded-md transition-all {selectedRange === 'custom'
			? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm'
			: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
		on:click={() => selectRange('custom')}
	>
		{selectedRange === 'custom' && customDateLabel ? customDateLabel : $i18n.t('Custom')}
	</button>
</div>

<!-- Custom Date Modal -->
<Modal bind:show={showCustomDateModal} size="sm">
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 mb-2">
			<div class="text-lg font-medium self-center">
				{$i18n.t('Custom Date Range')}
			</div>
			<button
				class="self-center"
				on:click={() => {
					showCustomDateModal = false;
					if (selectedRange !== 'custom') {
						selectedRange = '7d';
					}
				}}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
				</svg>
			</button>
		</div>

		<div class="px-5 pb-4">
			<div class="flex flex-col gap-3">
				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('From')}</div>
					<input
						type="datetime-local"
						bind:value={customFrom}
						class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none dark:text-gray-200"
					/>
				</div>
				<div class="flex flex-col w-full">
					<div class="mb-0.5 text-xs text-gray-500">{$i18n.t('To')}</div>
					<input
						type="datetime-local"
						bind:value={customTo}
						class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-none dark:text-gray-200"
					/>
				</div>
			</div>

			<div class="flex justify-end gap-2 mt-4 pt-3 border-t border-gray-50 dark:border-gray-850">
				<Button
					kind="outlined"
					size="md"
					on:click={() => {
						showCustomDateModal = false;
						if (selectedRange !== 'custom') selectedRange = '7d';
					}}
				>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" on:click={applyCustomDateRange}>
					{$i18n.t('Apply')}
				</Button>
			</div>
		</div>
	</div>
</Modal>
