<script lang="ts">
	import { goto } from '$app/navigation';
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import { user } from '$lib/stores';
	import { createNewToolConnection } from '$lib/apis/tool-connections';
	import { getMarketplaceServices, type MarketplaceService } from '$lib/apis/marketplace';
	import WorkspaceCreateScaffold from '../common/WorkspaceCreateScaffold.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;
	const i18n = getContext<I18nStore>('i18n');

	// 카탈로그 노출 순서 (작을수록 앞). Microsoft 365 를 먼저 노출.
	const SERVICE_ORDER: Record<string, number> = {
		'microsoft-365': 0,
		'google-workspace': 1
	};

	// 카탈로그 아이콘/액센트 (admin 패널에서 이전). 신규 서비스는 매니페스트 icon 키 + 여기 추가.
	const ICON_DEFAULT = `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6"><path stroke-linecap="round" stroke-linejoin="round" d="m21 7.5-9-5.25L3 7.5m18 0-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"/></svg>`;
	const ICONS: Record<string, string> = {
		'google-workspace': `<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-6 h-6"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z"/></svg>`,
		'microsoft-365': `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-6 h-6"><path d="M3 3h8.4v8.4H3V3Zm9.6 0H21v8.4h-8.4V3ZM3 12.6h8.4V21H3v-8.4Zm9.6 0H21V21h-8.4v-8.4Z"/></svg>`
	};
	const iconFor = (key: string): string => ICONS[key] || ICON_DEFAULT;
	const ACCENT: Record<string, string> = {
		'google-workspace': 'bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400',
		'microsoft-365': 'bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400'
	};
	const accentFor = (key: string): string =>
		ACCENT[key] || 'bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400';

	// 카드 hover 시 보여줄 전체 상세(카드에선 description 이 잘리므로). tippy 가 DOMPurify 로 새니타이즈.
	const detailHtml = (svc: MarketplaceService): string => {
		let h = `<div class="text-left max-w-xs space-y-1">`;
		h += `<div class="font-semibold">${$i18n.t(svc.name)}</div>`;
		h += `<div class="text-xs leading-relaxed">${$i18n.t(svc.description)}</div>`;
		if (svc.tags?.length) {
			h += `<div class="text-[10px] opacity-70 pt-0.5">${svc.tags.join(' · ')}</div>`;
		}
		return h + `</div>`;
	};

	let services: MarketplaceService[] = [];
	let loadingCatalog = true;
	let selectedServiceId = '';
	let loading = false;
	let name = '';
	let description = '';

	$: selectedService = services.find((s) => s.id === selectedServiceId) ?? null;

	const selectService = (svc: MarketplaceService) => {
		selectedServiceId = svc.id;
	};

	onMount(async () => {
		try {
			const all = (await getMarketplaceServices(localStorage.token)) || [];
			// 워크스페이스 마켓플레이스는 mcp 서비스만 (rest-config 제외). M365 먼저 노출.
			services = all
				.filter((s) => s.connection_kind === 'mcp')
				.sort((a, b) => (SERVICE_ORDER[a.id] ?? 99) - (SERVICE_ORDER[b.id] ?? 99));
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			loadingCatalog = false;
		}
	});

	const handleSubmit = async (
		e: CustomEvent<{ name: string; description: string; accessControl: any }>
	) => {
		if (!selectedService) {
			toast.error($i18n.t('Please select a service.'));
			return;
		}
		loading = true;
		// Service URL 은 카탈로그 기본값으로 생성하고, 이후 상세 페이지에서 수정한다.
		const urlField = selectedService.fields?.find((f) => f.key === 'url');
		const url = (urlField?.default ?? '').trim();
		const { name: n, description: d, accessControl } = e.detail;
		const res = await createNewToolConnection(localStorage.token, {
			name: n.trim(),
			description: d.trim(),
			data: {
				connection: {
					type: 'mcp',
					url,
					auth_type: selectedService.auth_type ?? 'none',
					key: '',
					headers: {},
					enabled: true
				}
			},
			meta: { source: 'marketplace', service_id: selectedService.id },
			access_control: accessControl
		}).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});

		if (res) {
			toast.success($i18n.t('Connection created successfully'));
			goto(`/workspace/marketplace/${res.id}`);
		}
		loading = false;
	};
</script>

<WorkspaceCreateScaffold
	title={$i18n.t('Create a connection')}
	nameLabel={$i18n.t('What is this connection for?')}
	namePlaceholder={$i18n.t('Name your connection')}
	descriptionLabel={$i18n.t('How can this connection be used?')}
	descriptionPlaceholder={$i18n.t('Describe this connection')}
	backHref="/workspace/marketplace"
	allowPublic={$user?.role === 'admin'}
	bind:name
	bind:description
	bind:loading
	on:submit={handleSubmit}
>
	<!-- 카탈로그 picker (이름/설명과 권한 사이) -->
	<div class="flex flex-col gap-2">
		<LabelBase
			label={$i18n.t('Service')}
			caption={$i18n.t('Choose which marketplace service this connection uses.')}
			size="md"
			required
		/>
		{#if loadingCatalog}
			<div class="flex justify-center py-6"><Spinner /></div>
		{:else if services.length === 0}
			<div class="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
				{$i18n.t('No services available')}
			</div>
		{:else}
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{#each services as svc (svc.id)}
					<Tooltip content={detailHtml(svc)} placement="top" className="block h-full">
						<button
							type="button"
							class="w-full h-full flex items-start gap-3 text-left rounded-xl border p-4 transition-all
								{selectedServiceId === svc.id
								? 'border-[var(--cloo-color-primary)] ring-1 ring-[var(--cloo-color-primary)] bg-[var(--cloo-bg-surface)]'
								: 'border-gray-100 dark:border-gray-850 hover:border-gray-200 dark:hover:border-gray-700'}"
							on:click={() => selectService(svc)}
						>
							<div class="flex items-center justify-center w-10 h-10 rounded-lg shrink-0 {accentFor(svc.icon)}">
								{@html iconFor(svc.icon)}
							</div>
							<div class="flex flex-col min-w-0">
								<div class="font-semibold text-sm text-[var(--cloo-text-primary)]">
									{$i18n.t(svc.name)}
								</div>
								<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400 line-clamp-3">
									{$i18n.t(svc.description)}
								</div>
							</div>
						</button>
					</Tooltip>
				{/each}
			</div>
		{/if}
	</div>
</WorkspaceCreateScaffold>
