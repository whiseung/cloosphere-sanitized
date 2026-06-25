<script lang="ts">
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let value: number | null = null;
	export let placeholder: string = '';
	export let disabled: boolean = false;

	let displayValue = '';

	function formatNumber(num: number): string {
		if (!num) return '';
		return num.toLocaleString();
	}

	function parseNumber(str: string): number | null {
		const cleaned = str.replace(/[^0-9]/g, '');
		if (!cleaned) return null;
		const num = parseInt(cleaned, 10);
		return num;
	}

	function handleInput(e: Event) {
		const input = e.target as HTMLInputElement;
		const cursorPos = input.selectionStart ?? 0;
		const oldLen = displayValue.length;

		const num = parseNumber(input.value);
		value = num;
		displayValue = num !== null && num > 0 ? formatNumber(num) : num === 0 ? '0' : '';

		// 커서 위치 보정
		const newLen = displayValue.length;
		const diff = newLen - oldLen;
		const newPos = Math.max(0, cursorPos + diff);
		requestAnimationFrame(() => {
			input.setSelectionRange(newPos, newPos);
		});
	}

	function handleFocus() {
		if (value === null) {
			displayValue = '';
		}
	}

	function handleBlur() {
		if (!displayValue) {
			value = null;
			displayValue = '';
		}
	}

	$: {
		if (value !== null && value > 0) {
			displayValue = formatNumber(value);
		} else if (value === 0) {
			displayValue = '0';
		} else {
			displayValue = '';
		}
	}
</script>

<input
	class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden tabular-nums"
	type="text"
	inputmode="numeric"
	placeholder={placeholder || $i18n.t('Global default')}
	value={displayValue}
	on:input={handleInput}
	on:focus={handleFocus}
	on:blur={handleBlur}
	{disabled}
/>
