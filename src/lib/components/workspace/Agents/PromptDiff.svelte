<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';

	const i18n: Writable<any> = getContext('i18n');

	export let before: string = ''; // This version (좌측)
	export let after: string = ''; // Current (우측)
	export let maxHeight: string = '300px';
	export let single = false; // 선택 버전이 현재(HEAD)일 때: 비교 없이 이 버전만 표시

	type Row = { l: string | null; r: string | null; changed: boolean };

	// 라인 단위 LCS diff (의존성 없는 자체 구현)
	function lineDiff(a: string, b: string): Row[] {
		const al = (a ?? '').split('\n');
		const bl = (b ?? '').split('\n');
		const m = al.length;
		const n = bl.length;
		const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
		for (let i = m - 1; i >= 0; i--) {
			for (let j = n - 1; j >= 0; j--) {
				dp[i][j] =
					al[i] === bl[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
			}
		}
		const rows: Row[] = [];
		let i = 0;
		let j = 0;
		while (i < m && j < n) {
			if (al[i] === bl[j]) {
				rows.push({ l: al[i], r: bl[j], changed: false });
				i++;
				j++;
			} else if (dp[i + 1][j] >= dp[i][j + 1]) {
				rows.push({ l: al[i], r: null, changed: true }); // 삭제 (좌측에만)
				i++;
			} else {
				rows.push({ l: null, r: bl[j], changed: true }); // 추가 (우측에만)
				j++;
			}
		}
		while (i < m) {
			rows.push({ l: al[i], r: null, changed: true });
			i++;
		}
		while (j < n) {
			rows.push({ l: null, r: bl[j], changed: true });
			j++;
		}
		return rows;
	}

	$: rows = lineDiff(before, after);
</script>

{#if single}
	<pre
		class="rounded-lg border border-gray-200 dark:border-gray-700 text-[13px] leading-relaxed font-mono whitespace-pre-wrap break-words p-3 bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-200 overflow-y-auto"
		style="max-height: {maxHeight};">{before || '—'}</pre>
{:else}
<div
	class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden text-[13px] leading-relaxed font-mono"
>
	<!-- 헤더 -->
	<div class="grid grid-cols-2 border-b border-gray-200 dark:border-gray-700">
		<div
			class="px-3 py-1.5 text-xs font-semibold font-sans text-gray-500 dark:text-gray-400 border-r border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800"
		>
			{$i18n.t('This version')}
		</div>
		<div
			class="px-3 py-1.5 text-xs font-semibold font-sans text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800"
		>
			{$i18n.t('Current')}
		</div>
	</div>
	<!-- 라인 행들 (좌=삭제 빨강 / 우=추가 초록) -->
	<div class="overflow-y-auto" style="max-height: {maxHeight};">
		{#each rows as row}
			<div class="grid grid-cols-2">
				<div
					class="px-3 py-0.5 whitespace-pre-wrap break-words border-r border-gray-100 dark:border-gray-800 {row.l ===
					null
						? 'bg-gray-50 dark:bg-gray-900/40'
						: row.changed
							? 'bg-red-50 dark:bg-red-900/25 text-red-700 dark:text-red-300'
							: 'text-gray-800 dark:text-gray-200'}"
				>{row.l ?? ''}</div>
				<div
					class="px-3 py-0.5 whitespace-pre-wrap break-words {row.r === null
						? 'bg-gray-50 dark:bg-gray-900/40'
						: row.changed
							? 'bg-green-50 dark:bg-green-900/25 text-green-700 dark:text-green-300'
							: 'text-gray-800 dark:text-gray-200'}"
				>{row.r ?? ''}</div>
			</div>
		{/each}
	</div>
</div>
{/if}
