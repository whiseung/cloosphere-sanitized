<script lang="ts">
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let data: any;
	export let depth: number = 0;
	export let keyName: string | null = null;
	export let defaultExpanded: boolean = true;
	export let maxDepthExpanded: number = 2;
	export let searchQuery: string = '';

	// 펼침 상태 관리 (키별로)
	let expandedKeys: Set<string> = new Set();
	let showFullStrings: Set<string> = new Set();

	// 데이터에 검색어가 포함되어 있는지 재귀적으로 확인
	const containsSearchQuery = (value: any, query: string): boolean => {
		if (!query.trim()) return false;
		const lowerQuery = query.toLowerCase();

		if (value === null || value === undefined) return false;
		if (typeof value === 'string') {
			return value.toLowerCase().includes(lowerQuery);
		}
		if (typeof value === 'number' || typeof value === 'boolean') {
			return String(value).toLowerCase().includes(lowerQuery);
		}
		if (Array.isArray(value)) {
			return value.some(item => containsSearchQuery(item, query));
		}
		if (typeof value === 'object') {
			return Object.values(value).some(v => containsSearchQuery(v, query));
		}
		return false;
	};

	// 검색어 하이라이트 (query를 파라미터로 받아 동적 업데이트)
	const highlightSearch = (text: string, query: string): string => {
		if (!query || !query.trim()) return escapeHtml(text);
		const escaped = escapeHtml(text);
		const escapedQuery = escapeHtml(query);
		const regex = new RegExp(`(${escapedQuery.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
		return escaped.replace(regex, '<mark class="bg-yellow-300 dark:bg-yellow-600 text-black dark:text-white rounded px-0.5">$1</mark>');
	};

	const escapeHtml = (text: string): string => {
		return text
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;')
			.replace(/'/g, '&#039;');
	};

	// JSON 문자열인 경우 파싱 시도
	function parseIfJsonString(value: any): any {
		if (typeof value === 'string') {
			// JSON 배열이나 객체처럼 보이는 경우만 파싱 시도
			const trimmed = value.trim();
			if ((trimmed.startsWith('{') && trimmed.endsWith('}')) ||
				(trimmed.startsWith('[') && trimmed.endsWith(']'))) {
				try {
					return JSON.parse(value);
				} catch {
					return value;
				}
			}
		}
		return value;
	}

	// 데이터 정규화
	$: normalizedData = parseIfJsonString(data);
	$: isObject = normalizedData !== null && typeof normalizedData === 'object' && !Array.isArray(normalizedData);
	$: isArray = Array.isArray(normalizedData);
	$: isExpandable = isObject || isArray;
	$: isEmpty = isArray ? normalizedData.length === 0 : isObject ? Object.keys(normalizedData).length === 0 : false;
	$: itemCount = isArray ? normalizedData.length : isObject ? Object.keys(normalizedData).length : 0;
	$: isLongString = typeof normalizedData === 'string' && normalizedData.length > 150;

	// 검색어가 있고 매치되면 자동으로 펼침
	$: hasMatch = searchQuery.trim() && containsSearchQuery(normalizedData, searchQuery);

	// 초기 펼침 상태 설정
	$: if (depth < maxDepthExpanded && defaultExpanded) {
		expanded = true;
	}

	// 검색어 매치 시 자동 펼침
	$: if (hasMatch) {
		expanded = true;
	}

	let expanded = depth < maxDepthExpanded ? defaultExpanded : false;

	const getValueColor = (value: any): string => {
		if (value === null) return 'text-gray-400';
		if (value === undefined) return 'text-gray-400';
		if (typeof value === 'string') return 'text-green-600 dark:text-green-400';
		if (typeof value === 'number') return 'text-blue-600 dark:text-blue-400';
		if (typeof value === 'boolean') return 'text-purple-600 dark:text-purple-400';
		return 'text-gray-700 dark:text-gray-300';
	};

	const formatPrimitive = (value: any): string => {
		if (value === null) return 'null';
		if (value === undefined) return 'undefined';
		if (typeof value === 'string') return `"${value}"`;
		if (typeof value === 'boolean') return value ? 'true' : 'false';
		return String(value);
	};

	const truncateString = (str: string, maxLen: number = 150): string => {
		if (str.length <= maxLen) return str;
		return str.slice(0, maxLen) + '...';
	};

	const toggleExpand = () => {
		expanded = !expanded;
	};

	const toggleFullString = (key: string) => {
		if (showFullStrings.has(key)) {
			showFullStrings.delete(key);
		} else {
			showFullStrings.add(key);
		}
		showFullStrings = showFullStrings; // trigger reactivity
	};

	const copyValue = async (value: any) => {
		try {
			const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
			await navigator.clipboard.writeText(text);
		} catch (e) {
			console.error('Failed to copy:', e);
		}
	};

	// 값이 확장 가능한지 확인 (객체나 배열, 또는 JSON 문자열)
	const isExpandableValue = (value: any): boolean => {
		if (value === null || value === undefined) return false;
		if (typeof value === 'object') return true;
		if (typeof value === 'string') {
			const trimmed = value.trim();
			return (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
				   (trimmed.startsWith('[') && trimmed.endsWith(']'));
		}
		return false;
	};
</script>

<div class="font-mono text-xs leading-relaxed" style="margin-left: {depth > 0 ? '16px' : '0'}">
	{#if isExpandable}
		<!-- 객체 또는 배열 -->
		<div class="flex items-start gap-1 group/row py-0.5">
			<button
				class="flex items-center gap-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded px-1 -ml-1 transition"
				on:click={toggleExpand}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="size-3 text-gray-400 transition-transform shrink-0 {expanded ? 'rotate-90' : ''}"
				>
					<path fill-rule="evenodd" d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L8.94 8 6.22 5.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
				</svg>
				{#if keyName !== null}
					<span class="text-red-600 dark:text-red-400">{keyName}</span>
					<span class="text-gray-500">:</span>
				{/if}
				<span class="text-gray-500">
					{isArray ? `Array(${itemCount})` : `Object`}
					{#if !expanded}
						<span class="text-gray-400 ml-1">{isArray ? '[...]' : '{...}'}</span>
					{/if}
				</span>
			</button>
			<button
				class="opacity-0 group-hover/row:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
				on:click={() => copyValue(normalizedData)}
				title={$i18n.t('Copy')}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
					<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
					<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
				</svg>
			</button>
		</div>

		{#if expanded && !isEmpty}
			<div class="border-l-2 border-gray-200 dark:border-gray-700 ml-1">
				{#if isArray}
					{#each normalizedData as item, index}
						{@const itemKey = `${depth}-${index}`}
						{@const parsedItem = parseIfJsonString(item)}
						<div class="pl-3 py-0.5">
							{#if isExpandableValue(item)}
								<svelte:self data={parsedItem} depth={depth + 1} keyName={String(index)} maxDepthExpanded={maxDepthExpanded} {searchQuery} />
							{:else if typeof item === 'string' && item.length > 150}
								<!-- 긴 문자열 - 전체 표시 -->
								<div class="flex items-start gap-1 group/item">
									<span class="text-blue-600 dark:text-blue-400 shrink-0">{index}</span>
									<span class="text-gray-500 shrink-0">:</span>
									<span class="text-green-600 dark:text-green-400 whitespace-pre-wrap break-all flex-1">{@html '"' + highlightSearch(item, searchQuery) + '"'}</span>
									<button
										class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400 shrink-0"
										on:click={() => copyValue(item)}
										title={$i18n.t('Copy')}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
											<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
											<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
										</svg>
									</button>
								</div>
							{:else}
								<div class="flex items-start gap-1 group/item">
									<span class="text-blue-600 dark:text-blue-400 shrink-0">{index}</span>
									<span class="text-gray-500 shrink-0">:</span>
									<span class="{getValueColor(item)}">{#if typeof item === 'string'}{@html '"' + highlightSearch(item, searchQuery) + '"'}{:else}{formatPrimitive(item)}{/if}</span>
									<button
										class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400"
										on:click={() => copyValue(item)}
										title={$i18n.t('Copy')}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
											<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
											<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
										</svg>
									</button>
								</div>
							{/if}
						</div>
					{/each}
				{:else}
					{#each Object.entries(normalizedData) as [key, value]}
						{@const itemKey = `${depth}-${key}`}
						{@const parsedValue = parseIfJsonString(value)}
						<div class="pl-3 py-0.5">
							{#if isExpandableValue(value)}
								<svelte:self data={parsedValue} depth={depth + 1} keyName={key} maxDepthExpanded={maxDepthExpanded} {searchQuery} />
							{:else if typeof value === 'string' && value.length > 150}
								<!-- 긴 문자열 - 전체 표시 -->
								<div class="flex items-start gap-1 group/item">
									<span class="text-red-600 dark:text-red-400 shrink-0">{key}</span>
									<span class="text-gray-500 shrink-0">:</span>
									<span class="text-green-600 dark:text-green-400 whitespace-pre-wrap break-all flex-1">{@html '"' + highlightSearch(value, searchQuery) + '"'}</span>
									<button
										class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400 shrink-0"
										on:click={() => copyValue(value)}
										title={$i18n.t('Copy')}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
											<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
											<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
										</svg>
									</button>
								</div>
							{:else}
								<div class="flex items-start gap-1 group/item">
									<span class="text-red-600 dark:text-red-400 shrink-0">{key}</span>
									<span class="text-gray-500 shrink-0">:</span>
									<span class="{getValueColor(value)}">{#if typeof value === 'string'}{@html '"' + highlightSearch(value, searchQuery) + '"'}{:else}{formatPrimitive(value)}{/if}</span>
									<button
										class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400"
										on:click={() => copyValue(value)}
										title={$i18n.t('Copy')}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
											<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
											<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
										</svg>
									</button>
								</div>
							{/if}
						</div>
					{/each}
				{/if}
			</div>
		{/if}
	{:else if isLongString}
		<!-- 최상위 긴 문자열 - 전체 표시 -->
		<div class="flex items-start gap-1 group/item py-0.5">
			{#if keyName !== null}
				<span class="text-red-600 dark:text-red-400 shrink-0">{keyName}</span>
				<span class="text-gray-500 shrink-0">:</span>
			{/if}
			<span class="text-green-600 dark:text-green-400 whitespace-pre-wrap break-all flex-1">{@html '"' + highlightSearch(normalizedData, searchQuery) + '"'}</span>
			<button
				class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400 shrink-0"
				on:click={() => copyValue(normalizedData)}
				title={$i18n.t('Copy')}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
					<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
					<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
				</svg>
			</button>
		</div>
	{:else}
		<!-- 기본 값 -->
		<div class="flex items-start gap-1 group/item py-0.5">
			{#if keyName !== null}
				<span class="text-red-600 dark:text-red-400 shrink-0">{keyName}</span>
				<span class="text-gray-500 shrink-0">:</span>
			{/if}
			<span class="{getValueColor(normalizedData)}">{#if typeof normalizedData === 'string'}{@html '"' + highlightSearch(normalizedData, searchQuery) + '"'}{:else}{formatPrimitive(normalizedData)}{/if}</span>
			<button
				class="opacity-0 group-hover/item:opacity-100 p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded transition text-gray-400"
				on:click={() => copyValue(normalizedData)}
				title={$i18n.t('Copy')}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="size-3">
					<path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" />
					<path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" />
				</svg>
			</button>
		</div>
	{/if}
</div>
