<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import AccessControlModal from '$lib/components/workspace/common/AccessControlModal.svelte';
	import { shareDashboard, unshareDashboard } from '$lib/apis/bi-dashboards';
	import type { BiDashboardDetail } from '$lib/apis/bi-dashboards';
	import { copyToClipboard } from '$lib/utils';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	export let show = false;
	export let dashboard: BiDashboardDetail;

	let loading = false;
	let showAccessModal = false;
	let accessControl: Record<string, any> | null = dashboard?.access_control ?? null;
	let initialized = false;

	$: if (show && dashboard && !initialized) {
		accessControl = dashboard.access_control ?? null;
		initialized = true;
	}
	$: if (!show) {
		initialized = false;
	}

	$: shareUrl = dashboard?.share_id
		? `${typeof window !== 'undefined' ? window.location.origin : ''}/dashboard/${dashboard.share_id}`
		: '';

	$: accessLabel = accessControl === null
		? $i18n.t('Public')
		: (accessControl?.read?.group_ids?.length || accessControl?.read?.org_unit_ids?.length)
			? $i18n.t('Restricted')
			: $i18n.t('Private');

	async function handleShare() {
		loading = true;
		try {
			const result = await shareDashboard(localStorage.token, dashboard.id, {
				access_control: accessControl
			});
			dashboard.share_id = result.share_id;
			dashboard.access_control = accessControl;
			await copyToClipboard(
				`${window.location.origin}${result.share_url}`
			);
			toast.success($i18n.t('Copied shared dashboard URL to clipboard!'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to share dashboard'));
		} finally {
			loading = false;
		}
	}

	async function handleUnshare() {
		loading = true;
		try {
			await unshareDashboard(localStorage.token, dashboard.id);
			dashboard.share_id = undefined;
			dashboard.access_control = null;
			accessControl = null;
			toast.success($i18n.t('Shared link deleted'));
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to unshare dashboard'));
		} finally {
			loading = false;
		}
	}
</script>

<AccessControlModal
	bind:show={showAccessModal}
	bind:accessControl
	accessRoles={['read']}
	allowPublic={true}
/>

<Modal size="sm" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{$i18n.t('Share Dashboard')}
			</div>
			<button class="self-center" on:click={() => (show = false)}>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
				</svg>
			</button>
		</div>

		<div class="px-5 pb-4">
			{#if dashboard?.share_id}
				<div class="mb-3">
					<div class="text-sm text-gray-500 dark:text-gray-400 mb-2">
						{$i18n.t('This dashboard is currently shared')}
					</div>

					<div class="flex items-center gap-2">
						<Input value={shareUrl} size="sm" readOnly />
						<Button
							kind="outlined"
							size="sm"
							on:click={async () => {
								await copyToClipboard(shareUrl);
								toast.success($i18n.t('Copied to clipboard'));
							}}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-4">
								<path d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z" />
								<path d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z" />
							</svg>
						</Button>
					</div>
				</div>
			{:else}
				<div class="text-sm text-gray-500 dark:text-gray-400 mb-3">
					{$i18n.t('Create a share link for this dashboard')}
				</div>
			{/if}

			<div class="mb-3">
				<Button kind="outlined" size="sm" on:click={() => {
					// 공개 상태에서 접근 제어 모달을 열면 비공개로 전환
					if (accessControl === null) {
						accessControl = { read: { group_ids: [], user_ids: [], org_unit_ids: [] }, write: { group_ids: [], user_ids: [], org_unit_ids: [] } };
					}
					showAccessModal = true;
				}}>
					<svelte:fragment slot="prefix">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3.5">
							<path fill-rule="evenodd" d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z" clip-rule="evenodd" />
						</svg>
					</svelte:fragment>
					{accessLabel}
				</Button>
			</div>

			<div class="flex justify-between items-center pt-2">
				{#if dashboard?.share_id}
					<Button kind="text" size="sm" status="error" on:click={handleUnshare} {loading}>
						{$i18n.t('Delete shared link')}
					</Button>
				{:else}
					<div></div>
				{/if}

				<Button kind="filled" size="md" on:click={handleShare} {loading}>
					{#if dashboard?.share_id}
						{$i18n.t('Update Access & Copy Link')}
					{:else}
						{$i18n.t('Create & Copy Link')}
					{/if}
				</Button>
			</div>
		</div>
	</div>
</Modal>
