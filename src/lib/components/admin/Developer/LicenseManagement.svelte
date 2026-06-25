<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getCloocusStatus,
		listCloocusCustomers,
		createCloocusCustomer,
		getCloocusCustomer,
		updateCloocusCustomer,
		deleteCloocusCustomer,
		recordLicenseKey,
		revokeLicense,
		deleteLicenseRecord,
		recordFeatureKey,
		revokeFeatureKey,
		deleteFeatureKeyRecord,
		listCloocusFeatures,
		createCloocusFeature,
		updateCloocusFeature,
		deleteCloocusFeature,
		generateLicenseKey,
		generateFeatureKey,
		createRegistryToken,
		updateRegistryToken,
		deleteRegistryToken,
		getCustomerCreditSummary,
		updateCustomerCredit
	} from '$lib/apis/cloocus';
	import { getNotificationChannelList } from '$lib/apis/notifications';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Badge from '$lib/components/common/Badge.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import MagnifyingGlass from '$lib/components/icons/MagnifyingGlass.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import { formatBackendError } from '$lib/utils/error';

	const i18n = getContext('i18n');

	let loading = true;
	let activeTab: 'customers' | 'features' = 'customers';
	let emailChannels: { name: string; engine: string }[] = [];

	let dbStatus: Record<string, any> | null = null;
	let keyGenAvailable = false;

	// 고객사
	let customers: any[] = [];
	let customerTotal = 0;
	let customerPage = 1;
	let customerSearch = '';
	let searchDebounce: ReturnType<typeof setTimeout>;

	// 고객사 상세
	let selectedCustomer: any | null = null;
	let detailLoading = false;
	let creditSummary: { total: number; used: number; pending: number; remaining: number } | null = null;

	// 기능 레지스트리
	let features: any[] = [];
	let featuresLoading = false;
	let featuresLoaded = false;

	// 고객사 편집 상태
	let editForm: {
		company_name: string;
		contact_name: string;
		contact_email: string;
		admin_contact_name: string;
		sales_contact_name: string;
		web_url: string;
		notes: string;
		license_type: string;
		start_date: string;
	} = { company_name: '', contact_name: '', contact_email: '', admin_contact_name: '', sales_contact_name: '', web_url: '', notes: '', license_type: '', start_date: '' };
	let editSaving = false;

	// 모달 - 고객사 추가
	let showAddCustomerModal = false;
	let addCustomerForm = { company_name: '', contact_email: '', contact_name: '', admin_contact_name: '', sales_contact_name: '', web_url: '', notes: '', license_type: '', start_date: '' };
	let addCustomerLoading = false;

	// 모달 - 라이선스 기록
	let showRecordLicenseModal = false;
	let recordLicenseForm = { tier: 'basic', max_users: 0, token: '', notes: '' };
	let recordLicenseLoading = false;

	// 모달 - 기능 키 기록
	let showRecordFeatureKeyModal = false;
	let recordFeatureKeyForm = { module: '', token: '', notes: '' };
	let recordFeatureKeyLoading = false;

	// 모달 - 라이선스 키 생성
	let showGenerateLicenseModal = false;
	let generateLicenseForm = { tier: 'basic', max_users: 0, expires: '', notes: '' };
	let generateLicenseLoading = false;
	let generatedLicenseToken = '';

	// 모달 - 기능 키 생성
	let showGenerateFeatureKeyModal = false;
	let generateFeatureKeyForm = { module: '', expires: '', notes: '' };
	let generateFeatureKeyLoading = false;
	let generatedFeatureKeyToken = '';

	// 크레딧 수정
	let showCreditEditModal = false;
	let creditEditForm = { credit: 0, approval_email: '', email_channel: '' };
	let creditEditSaving = false;

	// 레지스트리 토큰
	let showAddRegistryTokenModal = false;
	let addRegistryTokenForm = { token_name: '', token_key: '', notes: '' };
	let addRegistryTokenLoading = false;

	// 모달 - 기능 추가
	let showAddFeatureModal = false;
	let addFeatureForm = {
		module_id: '',
		display_name: '',
		description: '',
		tier_minimum: '',
		is_active: true
	};
	let addFeatureLoading = false;

	// 모달 - 기능 편집
	let showEditFeatureModal = false;
	let editFeatureForm = {
		module_id: '',
		display_name: '',
		description: '',
		tier_minimum: ''
	};
	let editFeatureLoading = false;

	onMount(async () => {
		await loadStatus();
		await loadCustomers();
		try {
			const channels = await getNotificationChannelList(localStorage.token);
			emailChannels = channels?.emails ?? [];
		} catch {
			emailChannels = [];
		}
		loading = false;
	});

	async function loadStatus() {
		try {
			dbStatus = await getCloocusStatus(localStorage.token);
			keyGenAvailable = dbStatus?.key_generation_available ?? false;
		} catch {
			dbStatus = null;
			keyGenAvailable = false;
		}
	}

	async function loadCustomers() {
		try {
			const res = await listCloocusCustomers(localStorage.token, customerPage, customerSearch);
			customers = res.items;
			customerTotal = res.total;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load customers'));
		}
	}

	async function loadFeatures() {
		featuresLoading = true;
		try {
			features = await listCloocusFeatures(localStorage.token);
			featuresLoaded = true;
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load features'));
			featuresLoaded = true;
		} finally {
			featuresLoading = false;
		}
	}

	function timestampToDateInput(ts: number | null): string {
		if (!ts) return '';
		return new Date(ts * 1000).toISOString().split('T')[0];
	}

	function dateInputToTimestamp(dateStr: string): number | null {
		if (!dateStr) return null;
		return Math.floor(new Date(dateStr + 'T00:00:00Z').getTime() / 1000);
	}

	function syncEditForm(customer: any) {
		editForm = {
			company_name: customer.company_name ?? '',
			contact_name: customer.contact_name ?? '',
			contact_email: customer.contact_email ?? '',
			admin_contact_name: customer.admin_contact_name ?? '',
			sales_contact_name: customer.sales_contact_name ?? '',
			web_url: customer.web_url ?? '',
			notes: customer.notes ?? '',
			license_type: customer.license_type ?? '',
			start_date: timestampToDateInput(customer.start_date)
		};
	}

	async function selectCustomer(customer: any) {
		detailLoading = true;
		selectedCustomer = null;
		creditSummary = null;
		try {
			selectedCustomer = await getCloocusCustomer(localStorage.token, customer.id);
			syncEditForm(selectedCustomer);
			try {
				creditSummary = await getCustomerCreditSummary(localStorage.token, customer.id);
			} catch {
				creditSummary = null;
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to load customer details'));
		} finally {
			detailLoading = false;
		}
	}

	async function handleSaveCustomer() {
		if (!selectedCustomer) return;
		if (!editForm.company_name.trim()) {
			toast.error($i18n.t('Company name is required'));
			return;
		}
		editSaving = true;
		try {
			await updateCloocusCustomer(localStorage.token, selectedCustomer.id, {
				company_name: editForm.company_name,
				contact_name: editForm.contact_name,
				contact_email: editForm.contact_email,
				admin_contact_name: editForm.admin_contact_name,
				sales_contact_name: editForm.sales_contact_name,
				web_url: editForm.web_url,
				notes: editForm.notes,
				license_type: editForm.license_type || null,
				start_date: dateInputToTimestamp(editForm.start_date)
			});
			toast.success($i18n.t('Customer updated'));
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			syncEditForm(selectedCustomer);
			await loadCustomers();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update customer'));
		} finally {
			editSaving = false;
		}
	}

	function handleSearchInput() {
		clearTimeout(searchDebounce);
		searchDebounce = setTimeout(() => {
			customerPage = 1;
			loadCustomers();
		}, 400);
	}

	async function handleAddCustomer() {
		if (!addCustomerForm.company_name.trim()) {
			toast.error($i18n.t('Company name is required'));
			return;
		}
		addCustomerLoading = true;
		try {
			const formData = {
				company_name: addCustomerForm.company_name,
				contact_email: addCustomerForm.contact_email,
				contact_name: addCustomerForm.contact_name,
				admin_contact_name: addCustomerForm.admin_contact_name,
				sales_contact_name: addCustomerForm.sales_contact_name,
				web_url: addCustomerForm.web_url,
				notes: addCustomerForm.notes,
				license_type: addCustomerForm.license_type || null,
				start_date: dateInputToTimestamp(addCustomerForm.start_date)
			};
			await createCloocusCustomer(localStorage.token, formData);
			toast.success($i18n.t('Customer created'));
			showAddCustomerModal = false;
			addCustomerForm = { company_name: '', contact_email: '', contact_name: '', admin_contact_name: '', sales_contact_name: '', web_url: '', notes: '', license_type: '', start_date: '' };
			await loadCustomers();
			await loadStatus();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to create customer'));
		} finally {
			addCustomerLoading = false;
		}
	}

	async function handleToggleCustomerActive(customer: any) {
		const nextIsActive = !customer.is_active;
		const confirmMessage = nextIsActive
			? $i18n.t('Activate this customer?')
			: $i18n.t('Deactivate this customer?');
		if (!confirm(confirmMessage)) return;

		try {
			await updateCloocusCustomer(localStorage.token, customer.id, { is_active: nextIsActive });
			toast.success(nextIsActive ? $i18n.t('Customer activated') : $i18n.t('Customer deactivated'));

			if (selectedCustomer?.id === customer.id) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, customer.id);
			}

			await loadCustomers();
			await loadStatus();
		} catch (e: any) {
			toast.error(
				formatBackendError(e, $i18n) ||
					(nextIsActive
						? $i18n.t('Failed to activate customer')
						: $i18n.t('Failed to deactivate customer'))
			);
		}
	}

	async function handleRecordLicense() {
		if (!selectedCustomer) return;
		if (!recordLicenseForm.token.trim()) {
			toast.error($i18n.t('License token is required'));
			return;
		}
		recordLicenseLoading = true;
		try {
			await recordLicenseKey(localStorage.token, {
				customer_id: selectedCustomer.id,
				...recordLicenseForm
			});
			toast.success($i18n.t('License recorded'));
			showRecordLicenseModal = false;
			recordLicenseForm = { tier: 'basic', max_users: 0, token: '', notes: '' };
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			await loadStatus();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to record license'));
		} finally {
			recordLicenseLoading = false;
		}
	}

	async function handleRecordFeatureKey() {
		if (!selectedCustomer) return;
		if (!recordFeatureKeyForm.module.trim() || !recordFeatureKeyForm.token.trim()) {
			toast.error($i18n.t('Module and token are required'));
			return;
		}
		recordFeatureKeyLoading = true;
		try {
			await recordFeatureKey(localStorage.token, {
				customer_id: selectedCustomer.id,
				...recordFeatureKeyForm
			});
			toast.success($i18n.t('Feature key recorded'));
			showRecordFeatureKeyModal = false;
			recordFeatureKeyForm = { module: '', token: '', notes: '' };
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to record feature key'));
		} finally {
			recordFeatureKeyLoading = false;
		}
	}

	async function handleRevokeFeatureKey(recordId: number) {
		if (!confirm($i18n.t('Revoke this feature key?'))) return;
		try {
			await revokeFeatureKey(localStorage.token, recordId);
			toast.success($i18n.t('Feature key revoked'));
			if (selectedCustomer) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to revoke feature key'));
		}
	}

	async function handleDeleteFeatureKey(recordId: number) {
		if (!confirm($i18n.t('Delete this feature key record?'))) return;
		try {
			await deleteFeatureKeyRecord(localStorage.token, recordId);
			toast.success($i18n.t('Feature key deleted'));
			if (selectedCustomer) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete feature key'));
		}
	}

	async function handleDeleteLicense(licenseId: number) {
		if (!confirm($i18n.t('Delete this license record?'))) return;
		try {
			await deleteLicenseRecord(localStorage.token, licenseId);
			toast.success($i18n.t('License deleted'));
			if (selectedCustomer) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete license'));
		}
	}

	async function handleGenerateLicense() {
		if (!selectedCustomer) return;
		generateLicenseLoading = true;
		generatedLicenseToken = '';
		try {
			const res = await generateLicenseKey(localStorage.token, {
				customer_id: selectedCustomer.id,
				...generateLicenseForm
			});
			generatedLicenseToken = res.token;
			toast.success($i18n.t('License key generated'));
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			await loadStatus();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to generate license key'));
		} finally {
			generateLicenseLoading = false;
		}
	}

	async function openGenerateFeatureKeyModal() {
		generateFeatureKeyForm = { module: '', expires: '', notes: '' };
		generatedFeatureKeyToken = '';
		showGenerateFeatureKeyModal = true;
		if (!featuresLoaded) await loadFeatures();
	}

	async function handleGenerateFeatureKey() {
		if (!selectedCustomer) return;
		if (!generateFeatureKeyForm.module.trim()) {
			toast.error($i18n.t('Module is required'));
			return;
		}
		generateFeatureKeyLoading = true;
		generatedFeatureKeyToken = '';
		try {
			const res = await generateFeatureKey(localStorage.token, {
				customer_id: selectedCustomer.id,
				...generateFeatureKeyForm
			});
			generatedFeatureKeyToken = res.token;
			toast.success($i18n.t('Feature key generated'));
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to generate feature key'));
		} finally {
			generateFeatureKeyLoading = false;
		}
	}

	async function handleDeleteCustomerHard(customer: any) {
		if (!confirm($i18n.t('Permanently delete this customer and all their key records?'))) return;
		try {
			await deleteCloocusCustomer(localStorage.token, customer.id, true);
			toast.success($i18n.t('Customer deleted'));
			if (selectedCustomer?.id === customer.id) selectedCustomer = null;
			await loadCustomers();
			await loadStatus();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete customer'));
		}
	}

	async function handleDeleteFeature(moduleId: string) {
		if (!confirm($i18n.t('Permanently delete this feature?'))) return;
		try {
			await deleteCloocusFeature(localStorage.token, moduleId);
			toast.success($i18n.t('Feature deleted'));
			features = features.filter((f) => f.module_id !== moduleId);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete feature'));
		}
	}

	function copyToClipboard(text: string) {
		navigator.clipboard.writeText(text).then(() => {
			toast.success($i18n.t('Copied to clipboard'));
		});
	}

	async function handleAddRegistryToken() {
		if (!selectedCustomer) return;
		if (!addRegistryTokenForm.token_name.trim() || !addRegistryTokenForm.token_key.trim()) {
			toast.error($i18n.t('Token name and key are required'));
			return;
		}
		addRegistryTokenLoading = true;
		try {
			await createRegistryToken(localStorage.token, {
				customer_id: selectedCustomer.id,
				...addRegistryTokenForm
			});
			toast.success($i18n.t('Registry token created'));
			showAddRegistryTokenModal = false;
			addRegistryTokenForm = { token_name: '', token_key: '', notes: '' };
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to create registry token'));
		} finally {
			addRegistryTokenLoading = false;
		}
	}

	async function handleDeleteRegistryToken(tokenId: number) {
		if (!confirm($i18n.t('Delete this registry token?'))) return;
		try {
			await deleteRegistryToken(localStorage.token, tokenId);
			toast.success($i18n.t('Registry token deleted'));
			if (selectedCustomer) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to delete registry token'));
		}
	}

	function openCreditEditModal() {
		if (!selectedCustomer) return;
		creditEditForm = {
			credit: selectedCustomer.credit || 0,
			approval_email: selectedCustomer.approval_email || '',
			email_channel: selectedCustomer.email_channel || ''
		};
		showCreditEditModal = true;
	}

	async function handleSaveCredit() {
		if (!selectedCustomer) return;
		creditEditSaving = true;
		try {
			await updateCustomerCredit(localStorage.token, selectedCustomer.id, {
				credit: creditEditForm.credit,
				approval_email: creditEditForm.approval_email || undefined,
				email_channel: creditEditForm.email_channel || undefined
			});
			toast.success($i18n.t('Credit updated'));
			showCreditEditModal = false;
			selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			try {
				creditSummary = await getCustomerCreditSummary(localStorage.token, selectedCustomer.id);
			} catch {
				creditSummary = null;
			}
			await loadCustomers();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update credit'));
		} finally {
			creditEditSaving = false;
		}
	}

	async function handleRevokeLicense(licenseId: number) {
		if (!confirm($i18n.t('Revoke this license?'))) return;
		try {
			await revokeLicense(localStorage.token, licenseId);
			toast.success($i18n.t('License revoked'));
			if (selectedCustomer) {
				selectedCustomer = await getCloocusCustomer(localStorage.token, selectedCustomer.id);
			}
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to revoke license'));
		}
	}

	async function handleAddFeature() {
		if (!addFeatureForm.module_id.trim() || !addFeatureForm.display_name.trim()) {
			toast.error($i18n.t('Module ID and Display Name are required'));
			return;
		}
		addFeatureLoading = true;
		try {
			await createCloocusFeature(localStorage.token, addFeatureForm);
			toast.success($i18n.t('Feature registered'));
			showAddFeatureModal = false;
			addFeatureForm = {
				module_id: '',
				display_name: '',
				description: '',
				tier_minimum: '',
				is_active: true
			};
			await loadFeatures();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to register feature'));
		} finally {
			addFeatureLoading = false;
		}
	}

	function openEditFeatureModal(feature: any) {
		editFeatureForm = {
			module_id: feature.module_id,
			display_name: feature.display_name || '',
			description: feature.description || '',
			tier_minimum: feature.tier_minimum || ''
		};
		showEditFeatureModal = true;
	}

	async function handleEditFeature() {
		if (!editFeatureForm.display_name.trim()) {
			toast.error($i18n.t('Display Name is required'));
			return;
		}
		editFeatureLoading = true;
		try {
			await updateCloocusFeature(localStorage.token, editFeatureForm.module_id, {
				display_name: editFeatureForm.display_name,
				description: editFeatureForm.description,
				tier_minimum: editFeatureForm.tier_minimum
			});
			toast.success($i18n.t('Feature updated'));
			showEditFeatureModal = false;
			await loadFeatures();
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update feature'));
		} finally {
			editFeatureLoading = false;
		}
	}

	async function toggleFeatureActive(feature: any) {
		try {
			await updateCloocusFeature(localStorage.token, feature.module_id, {
				is_active: !feature.is_active
			});
			feature.is_active = !feature.is_active;
			features = [...features];
		} catch (e: any) {
			toast.error(formatBackendError(e, $i18n) || $i18n.t('Failed to update feature'));
		}
	}

	function formatDate(ts: number | null) {
		if (!ts) return '-';
		return new Date(ts * 1000).toLocaleDateString();
	}

	$: if (activeTab === 'features' && !featuresLoaded) {
		loadFeatures();
	}

	$: licenseTypeOptions = [
		{ value: '', label: '-' },
		{ value: 'poc', label: 'PoC' },
		{ value: 'contract', label: $i18n.t('Contract') }
	];
</script>

{#if loading}
	<div class="flex justify-center py-10">
		<Spinner />
	</div>
{:else}
	<div class="flex flex-col gap-3">
		<!-- 상단 상태 배지 -->
		<div class="flex items-center gap-2 flex-wrap">
			<span
				class="text-xs font-medium px-2 py-0.5 rounded-sm {dbStatus
					? 'bg-green-500/20 text-green-700 dark:text-green-200'
					: 'bg-red-500/20 text-red-700 dark:text-red-200'}"
			>
				{dbStatus ? $i18n.t('Cloocus DB Connected') : $i18n.t('Cloocus DB Not Available')}
			</span>
			{#if dbStatus}
				<span class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Customers')}: {dbStatus.active_customer_count}/{dbStatus.customer_count}
					·
					{$i18n.t('Licenses')}: {dbStatus.license_record_count}
				</span>
			{/if}
		</div>

		<!-- 탭 -->
		<div class="flex items-center gap-1">
			<Button
				kind={activeTab === 'customers' ? 'filled' : 'text'}
				size="sm"
				type="button"
				on:click={() => (activeTab = 'customers')}
			>
				{$i18n.t('Customers')}
			</Button>
			<Button
				kind={activeTab === 'features' ? 'filled' : 'text'}
				size="sm"
				type="button"
				on:click={() => (activeTab = 'features')}
			>
				{$i18n.t('Feature Registry')}
			</Button>
		</div>

		<!-- 고객사 탭 -->
		{#if activeTab === 'customers'}
			<div class="flex flex-col gap-4">
				<!-- 고객사 목록 -->
				<div class="flex-1 min-w-0">
					<div class="flex items-center gap-2 mb-3">
						<div class="flex-1">
							<Input
								bind:value={customerSearch}
								placeholder={$i18n.t('Search customers...')}
								size="md"
								on:input={() => handleSearchInput()}
							>
								<svelte:fragment slot="prefix">
									<MagnifyingGlass className="size-4" />
								</svelte:fragment>
							</Input>
						</div>
						<Button kind="filled" size="md" on:click={() => (showAddCustomerModal = true)}>
							<svelte:fragment slot="prefix">
								<Plus className="size-4" strokeWidth="2" />
							</svelte:fragment>
							{$i18n.t('Add Customer')}
						</Button>
					</div>

					<div class="scrollbar-hidden relative whitespace-nowrap overflow-x-auto max-w-full rounded-sm pt-0.5">
						<!-- 헤더 -->
						<div class="hidden md:flex text-xs font-medium text-gray-500 dark:text-gray-400 px-1 mb-1 uppercase">
							<div class="flex-[2] min-w-0">{$i18n.t('Company')}</div>
							<div class="flex-[2] min-w-0">{$i18n.t('Contact')}</div>
							<div class="flex-none w-20 text-center">{$i18n.t('Type')}</div>
							<div class="flex-none w-24 text-center">{$i18n.t('Credit')}</div>
							<div class="hidden lg:flex flex-none w-16 text-center justify-center">{$i18n.t('Licenses')}</div>
							<div class="flex-none w-20 text-center">{$i18n.t('Status')}</div>
							<div class="flex-none w-44"></div>
						</div>
						<hr class="mb-1 border-gray-50 dark:border-gray-850 hidden md:block" />

						{#each customers as customer (customer.id)}
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<div
								class="flex flex-col md:flex-row md:items-center py-2 px-1 hover:bg-gray-50 dark:hover:bg-gray-950 rounded-lg gap-1 md:gap-0 cursor-pointer transition {selectedCustomer?.id === customer.id ? 'bg-gray-50 dark:bg-gray-950' : ''}"
								on:click={() => selectCustomer(customer)}
							>
								<div class="flex-[2] min-w-0 text-sm font-medium text-gray-900 dark:text-gray-100 truncate">
									{customer.company_name}
								</div>
								<div class="flex-[2] min-w-0 text-sm text-gray-500 dark:text-gray-400 hidden md:block">
									<div class="truncate">{customer.contact_name || '-'}</div>
									{#if customer.contact_email}
										<div class="text-xs text-gray-400 dark:text-gray-500 truncate">{customer.contact_email}</div>
									{/if}
								</div>
								<div class="flex-none w-20 hidden md:flex justify-center">
									{#if customer.license_type === 'poc'}
										<Badge status="warning" size="sm" content="PoC" />
									{:else if customer.license_type === 'contract'}
										<Badge status="info" size="sm" content={$i18n.t('Contract')} />
									{:else}
										<span class="text-gray-400 dark:text-gray-500">-</span>
									{/if}
								</div>
								<div class="flex-none w-24 hidden md:block text-center">
									{#if customer.credit_summary}
										<div class="text-xs">
											<span class="font-medium dark:text-gray-200">{customer.credit_summary.used}</span>
											<span class="text-gray-400 dark:text-gray-500">/</span>
											<span class="dark:text-gray-300">{customer.credit_summary.total}</span>
											{#if customer.credit_summary.pending > 0}
												<span class="text-yellow-600 dark:text-yellow-400 ml-0.5">({customer.credit_summary.pending})</span>
											{/if}
										</div>
									{:else}
										<span class="text-gray-400 dark:text-gray-500">-</span>
									{/if}
								</div>
								<div class="hidden lg:block flex-none w-16 text-sm text-center text-gray-500 dark:text-gray-400">
									{customer.active_license_count}
								</div>
								<div class="flex-none w-20 flex justify-center">
									<Badge
										status={customer.is_active ? 'success' : 'default'}
										size="sm"
										content={customer.is_active ? $i18n.t('Active') : $i18n.t('Inactive')}
									/>
								</div>
								<div class="flex-none w-44 flex gap-1.5 justify-end">
									<Button
										kind="outlined"
										size="sm"
										type="button"
										on:click={(e) => {
											e.stopPropagation();
											handleToggleCustomerActive(customer);
										}}
									>
										{customer.is_active ? $i18n.t('Deactivate') : $i18n.t('Activate')}
									</Button>
									<Button
										kind="outlined"
										size="sm"
										status="error"
										type="button"
										on:click={(e) => {
											e.stopPropagation();
											handleDeleteCustomerHard(customer);
										}}
									>
										{$i18n.t('Delete')}
									</Button>
								</div>
							</div>
						{/each}

						{#if customers.length === 0}
							<div class="flex flex-col items-center justify-center py-12 text-center">
								<p class="text-gray-500 dark:text-gray-400">
									{$i18n.t('No customers found')}
								</p>
							</div>
						{/if}
					</div>

					<!-- 페이지네이션 -->
					{#if customerTotal > 20}
						<div class="flex items-center justify-between mt-3 text-xs text-gray-500 dark:text-gray-400">
							<span>{$i18n.t('Total')}: {customerTotal}</span>
							<div class="flex items-center gap-1">
								<Button
									kind="text"
									size="sm"
									type="button"
									disabled={customerPage <= 1}
									on:click={() => {
										customerPage--;
										loadCustomers();
									}}
								>
									<ChevronLeft className="size-4" />
								</Button>
								<span class="px-2 py-1">{customerPage}</span>
								<Button
									kind="text"
									size="sm"
									type="button"
									disabled={customerPage * 20 >= customerTotal}
									on:click={() => {
										customerPage++;
										loadCustomers();
									}}
								>
									<ChevronRight className="size-4" />
								</Button>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{/if}

		<!-- 기능 레지스트리 탭 -->
		{#if activeTab === 'features'}
			<div>
				<div class="flex items-center justify-between mb-3">
					<p class="text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Registered feature modules and their minimum tier requirements')}
					</p>
				<Button kind="filled" size="md" on:click={() => (showAddFeatureModal = true)}>
					+ {$i18n.t('Add Feature')}
				</Button>
				</div>

				{#if featuresLoading}
					<div class="flex justify-center py-10">
						<Spinner />
					</div>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b dark:border-gray-800">
								<th class="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400">
									{$i18n.t('Module ID')}
								</th>
								<th class="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400">
									{$i18n.t('Display Name')}
								</th>
								<th class="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 hidden md:table-cell">
									{$i18n.t('Min Tier')}
								</th>
								<th class="text-center py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400">
									{$i18n.t('Active')}
								</th>
								<th class="py-2 px-3"></th>
							</tr>
						</thead>
						<tbody>
							{#each features as feature (feature.module_id)}
								<tr class="border-b dark:border-gray-800 hover:bg-black/5 dark:hover:bg-white/5 transition">
									<td class="py-2.5 px-3 font-mono text-xs text-gray-600 dark:text-gray-400">
										{feature.module_id}
									</td>
									<td class="py-2.5 px-3 dark:text-gray-200 text-gray-700">
										<div>{feature.display_name}</div>
										{#if feature.description}
											<div class="text-xs text-gray-400 dark:text-gray-500">{feature.description}</div>
										{/if}
									</td>
									<td class="py-2.5 px-3 hidden md:table-cell">
										{#if feature.tier_minimum}
											<span class="text-xs font-bold px-1 rounded-sm uppercase bg-gray-500/20 text-gray-700 dark:text-gray-200">
												{feature.tier_minimum}
											</span>
										{:else}
											<span class="text-gray-400 dark:text-gray-500">-</span>
										{/if}
									</td>
									<td class="py-2.5 px-3 text-center">
										<div class="flex justify-center">
											<Switch
												state={feature.is_active}
												on:change={() => toggleFeatureActive(feature)}
											/>
										</div>
									</td>
									<td class="py-2.5 px-3">
									<div class="flex gap-1">
										<button
											class="w-fit text-xs px-2 py-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl transition text-gray-500 hover:text-gray-700"
											on:click={() => openEditFeatureModal(feature)}
										>
											{$i18n.t('Edit')}
										</button>
										<button
											class="w-fit text-xs px-2 py-1.5 dark:text-red-400 dark:hover:text-red-300 hover:bg-black/5 dark:hover:bg-white/5 rounded-xl transition text-red-500 hover:text-red-600"
											on:click={() => handleDeleteFeature(feature.module_id)}
										>
											{$i18n.t('Delete')}
										</button>
									</div>
									</td>
								</tr>
							{:else}
								<tr>
									<td colspan="4" class="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
										{$i18n.t('No features registered')}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<!-- 고객사 상세 모달 -->
{#if selectedCustomer || detailLoading}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:click|self={() => (selectedCustomer = null)}
	>
		<div class="m-auto w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-5 max-h-[90vh] overflow-y-auto">
			{#if detailLoading}
				<div class="flex justify-center py-8">
					<Spinner />
				</div>
			{:else if selectedCustomer}
				<div class="flex items-center justify-between mb-2">
					<span class="text-xs font-medium text-gray-600 dark:text-gray-300">
						{$i18n.t('Customer Info')}
					</span>
					<div class="flex items-center gap-1">
						<Button kind="filled" size="md" loading={editSaving} on:click={handleSaveCustomer}>
							{$i18n.t('Save')}
						</Button>
						<Button
							kind="text"
							size="sm"
							type="button"
							on:click={() => (selectedCustomer = null)}
						>
							<XMark className="size-5" />
						</Button>
					</div>
				</div>

				<div class="flex flex-col gap-2">
					<Input
						bind:value={editForm.company_name}
						label={$i18n.t('Company Name')}
						size="sm"
						autocomplete="off"
					/>
					<div class="grid grid-cols-2 gap-2">
						<div>
							<div class="mb-1.5 text-xs font-medium text-[var(--cloo-text-primary)]">
								{$i18n.t('License Type')}
							</div>
							<Selector
								value={editForm.license_type}
								items={licenseTypeOptions}
								size="sm"
								on:change={(e) => {
									editForm.license_type = e.detail.value;
								}}
							/>
						</div>
						<div>
							<div class="mb-1.5 text-xs font-medium text-[var(--cloo-text-primary)]">
								{$i18n.t('Start Date')}
							</div>
							<input
								type="date"
								bind:value={editForm.start_date}
								class="w-full rounded-lg py-1.5 px-3 text-sm bg-white dark:text-gray-200 dark:bg-gray-900 border dark:border-gray-800 outline-hidden"
							/>
						</div>
					</div>
					<div class="grid grid-cols-2 gap-2">
						<Input
							bind:value={editForm.contact_name}
							label={$i18n.t('Customer Contact Name')}
							size="sm"
							autocomplete="off"
						/>
						<Input
							bind:value={editForm.contact_email}
							type="email"
							label={$i18n.t('Customer Contact Email')}
							size="sm"
							autocomplete="off"
						/>
					</div>
					<div class="grid grid-cols-2 gap-2">
						<Input
							bind:value={editForm.admin_contact_name}
							label={$i18n.t('Admin Contact')}
							size="sm"
							autocomplete="off"
						/>
						<Input
							bind:value={editForm.sales_contact_name}
							label={$i18n.t('Sales Contact')}
							size="sm"
							autocomplete="off"
						/>
					</div>
					<Input
						bind:value={editForm.web_url}
						type="url"
						label={$i18n.t('Web URL')}
						placeholder="https://"
						size="sm"
						autocomplete="off"
					/>
					<Textarea
						bind:value={editForm.notes}
						label={$i18n.t('Notes')}
						rows={2}
						size="sm"
					/>
				</div>

				<!-- Secret Key (WEBUI_SECRET_KEY) -->
				{#if selectedCustomer?.secret_key}
					<div class="mt-2">
						<div class="mb-0.5 text-xs text-gray-500 dark:text-gray-400">
							WEBUI_SECRET_KEY
						</div>
						<div class="flex items-center gap-2">
							<SensitiveInput
								outerClassName="flex flex-1 rounded-lg py-1.5 px-3 bg-gray-50 dark:bg-gray-900 border dark:border-gray-800"
								inputClassName="w-full text-sm bg-transparent dark:text-gray-200 outline-hidden font-mono"
								value={selectedCustomer.secret_key}
								readOnly={true}
								required={false}
							/>
							<button
								class="shrink-0 px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
								on:click={() => {
									navigator.clipboard.writeText(selectedCustomer.secret_key);
									toast.success($i18n.t('Copied to clipboard'));
								}}
							>
								{$i18n.t('Copy')}
							</button>
						</div>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Add this value as WEBUI_SECRET_KEY in the customer environment variables.')}
						</div>
					</div>
				{/if}

				<!-- SR Key -->
				{#if selectedCustomer?.sr_key}
					<div class="mt-2">
						<div class="mb-0.5 text-xs text-gray-500 dark:text-gray-400">
							SR_KEY
						</div>
						<div class="flex items-center gap-2">
							<SensitiveInput
								outerClassName="flex flex-1 rounded-lg py-1.5 px-3 bg-gray-50 dark:bg-gray-900 border dark:border-gray-800"
								inputClassName="w-full text-sm bg-transparent dark:text-gray-200 outline-hidden font-mono"
								value={selectedCustomer.sr_key}
								readOnly={true}
								required={false}
							/>
							<button
								class="shrink-0 px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
								on:click={() => {
									navigator.clipboard.writeText(selectedCustomer.sr_key);
									toast.success($i18n.t('Copied to clipboard'));
								}}
							>
								{$i18n.t('Copy')}
							</button>
						</div>
						<div class="mt-1 text-xs text-gray-400 dark:text-gray-500">
							{$i18n.t('Add the following environment variables to the customer instance:')}
						</div>
						<div class="mt-1 px-2 py-1.5 rounded bg-gray-50 dark:bg-gray-800 text-xs font-mono text-gray-600 dark:text-gray-400 select-all">
							SR_KEY={selectedCustomer.sr_key}<br/>
							CLOOCUS_PUBLIC_URL=https://cloosphere.azurewebsites.net
						</div>
					</div>
				{/if}

				<!-- 크레딧 요약 -->
				{#if creditSummary}
					<div class="mt-2">
						<div class="flex items-center justify-between mb-2">
							<span class="text-xs font-medium text-gray-600 dark:text-gray-300">
								{$i18n.t('Credit Summary')}
							</span>
							<button
								class="px-2 py-1 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
								on:click={openCreditEditModal}
							>
								{$i18n.t('Edit')}
							</button>
						</div>
						<div class="grid grid-cols-4 gap-2">
							<div class="rounded-lg p-2 bg-white dark:bg-gray-900 border dark:border-gray-800 text-center">
								<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Total')}</div>
								<div class="text-sm font-semibold dark:text-white">{creditSummary.total}</div>
							</div>
							<div class="rounded-lg p-2 bg-white dark:bg-gray-900 border dark:border-gray-800 text-center">
								<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Used')}</div>
								<div class="text-sm font-semibold text-blue-600 dark:text-blue-400">{creditSummary.used}</div>
							</div>
							<div class="rounded-lg p-2 bg-white dark:bg-gray-900 border dark:border-gray-800 text-center">
								<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Pending')}</div>
								<div class="text-sm font-semibold text-yellow-600 dark:text-yellow-400">{creditSummary.pending}</div>
							</div>
							<div class="rounded-lg p-2 bg-white dark:bg-gray-900 border dark:border-gray-800 text-center">
								<div class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Remaining')}</div>
								<div class="text-sm font-semibold {creditSummary.remaining < 0 ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'}">{creditSummary.remaining}</div>
							</div>
						</div>
					</div>
				{/if}

				<!-- 라이선스 키 이력 -->
				<div class="mt-2">
					<div class="flex items-center justify-between mb-2">
						<span class="text-xs font-medium text-gray-600 dark:text-gray-300">
							{$i18n.t('License Keys')}
						</span>
						<div class="flex gap-1">
							{#if keyGenAvailable}
							<Button
								kind="filled"
								size="sm"
								on:click={() => { generateLicenseForm = { tier: 'basic', max_users: 0, expires: '', notes: '' }; generatedLicenseToken = ''; showGenerateLicenseModal = true; }}
							>
								{$i18n.t('Generate')}
							</Button>
							{/if}
							<button
								class="px-2 py-1 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
								on:click={() => (showRecordLicenseModal = true)}
							>
								{$i18n.t('Record')}
							</button>
						</div>
					</div>

					{#if selectedCustomer.licenses.length === 0}
						<p class="text-xs text-gray-400 dark:text-gray-500 py-1">
							{$i18n.t('No licenses recorded')}
						</p>
					{:else}
						<div class="space-y-1.5 max-h-48 overflow-y-auto">
							{#each selectedCustomer.licenses as lic (lic.id)}
								<div class="text-xs rounded-lg p-2.5 bg-white dark:bg-gray-900 border dark:border-gray-800">
									<div class="flex items-center justify-between mb-1">
										<span class="font-bold uppercase text-xs px-1 rounded-sm
											{lic.is_revoked
												? 'bg-gray-500/20 text-gray-500 dark:text-gray-400'
												: 'bg-green-500/20 text-green-700 dark:text-green-200'}">
											{lic.tier}
										</span>
										<div class="flex items-center gap-1">
											{#if lic.token}
												<button
													class="w-fit text-xs px-1.5 py-0.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
													on:click={() => copyToClipboard(lic.token)}
													title={$i18n.t('Copy Key')}
												>
													{$i18n.t('Copy')}
												</button>
											{/if}
											{#if lic.is_revoked}
												<span class="text-xs text-red-500/70 dark:text-red-400/70 italic">
													{$i18n.t('Revoked')}
												</span>
											{:else}
												<button
													class="w-fit text-xs px-1.5 py-0.5 dark:text-red-400 dark:hover:text-red-300 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition text-red-500 hover:text-red-600"
													on:click={() => handleRevokeLicense(lic.id)}
												>
													{$i18n.t('Revoke')}
												</button>
											{/if}
											<button
												class="w-fit text-xs px-1.5 py-0.5 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
												on:click={() => handleDeleteLicense(lic.id)}
												title={$i18n.t('Delete')}
											>
												{$i18n.t('Delete')}
											</button>
										</div>
									</div>
									<div class="text-gray-500 dark:text-gray-400">
										{$i18n.t('Max Users')}: {lic.max_users || $i18n.t('Unlimited')}
										· {$i18n.t('Expires')}: {formatDate(lic.expires_at)}
									</div>
									{#if lic.notes}
										<div class="text-gray-400 dark:text-gray-500 mt-0.5">{lic.notes}</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>

				<!-- 개별 기능 키 이력 -->
				<div class="mt-2">
					<div class="flex items-center justify-between mb-2">
						<span class="text-xs font-medium text-gray-600 dark:text-gray-300">
							{$i18n.t('Feature Keys')}
						</span>
						<div class="flex gap-1">
							{#if keyGenAvailable}
							<Button kind="filled" size="sm" on:click={openGenerateFeatureKeyModal}>
								{$i18n.t('Generate')}
							</Button>
							{/if}
							<button
								class="px-2 py-1 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
								on:click={() => (showRecordFeatureKeyModal = true)}
							>
								{$i18n.t('Record')}
							</button>
						</div>
					</div>

					{#if selectedCustomer.feature_keys.length === 0}
						<p class="text-xs text-gray-400 dark:text-gray-500 py-1">
							{$i18n.t('No feature keys recorded')}
						</p>
					{:else}
						<div class="space-y-1.5 max-h-48 overflow-y-auto">
							{#each selectedCustomer.feature_keys as fk (fk.id)}
								<div class="text-xs rounded-lg p-2.5 bg-white dark:bg-gray-900 border dark:border-gray-800">
									<div class="flex items-center justify-between mb-1">
										<span class="font-mono font-bold text-xs px-1 rounded-sm
											{fk.is_revoked
												? 'bg-gray-500/20 text-gray-500 dark:text-gray-400'
												: 'bg-blue-500/20 text-blue-700 dark:text-blue-200'}">
											{fk.module}
										</span>
										<div class="flex items-center gap-1">
											{#if fk.token}
												<button
													class="w-fit text-xs px-1.5 py-0.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
													on:click={() => copyToClipboard(fk.token)}
													title={$i18n.t('Copy Key')}
												>
													{$i18n.t('Copy')}
												</button>
											{/if}
											{#if fk.is_revoked}
												<span class="text-xs text-red-500/70 dark:text-red-400/70 italic">
													{$i18n.t('Revoked')}
												</span>
											{:else}
												<button
													class="w-fit text-xs px-1.5 py-0.5 dark:text-red-400 dark:hover:text-red-300 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition text-red-500 hover:text-red-600"
													on:click={() => handleRevokeFeatureKey(fk.id)}
												>
													{$i18n.t('Revoke')}
												</button>
											{/if}
											<button
												class="w-fit text-xs px-1.5 py-0.5 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
												on:click={() => handleDeleteFeatureKey(fk.id)}
												title={$i18n.t('Delete')}
											>
												{$i18n.t('Delete')}
											</button>
										</div>
									</div>
									<div class="text-gray-500 dark:text-gray-400">
										{$i18n.t('Expires')}: {formatDate(fk.expires_at)}
									</div>
									{#if fk.notes}
										<div class="text-gray-400 dark:text-gray-500 mt-0.5">{fk.notes}</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>

			<!-- 레지스트리 토큰 -->
			<div class="mt-2">
				<div class="flex items-center justify-between mb-2">
					<span class="text-xs font-medium text-gray-600 dark:text-gray-300">
						{$i18n.t('Registry Tokens')}
					</span>
					<button
						class="px-2 py-1 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 transition dark:text-gray-300"
						on:click={() => { addRegistryTokenForm = { token_name: '', token_key: '', notes: '' }; showAddRegistryTokenModal = true; }}
					>
						+ {$i18n.t('Add')}
					</button>
				</div>

				{#if selectedCustomer.registry_tokens?.length === 0 || !selectedCustomer.registry_tokens}
					<p class="text-xs text-gray-400 dark:text-gray-500 py-1">
						{$i18n.t('No registry tokens')}
					</p>
				{:else}
					<div class="space-y-1.5 max-h-48 overflow-y-auto">
						{#each selectedCustomer.registry_tokens as rt (rt.id)}
							<div class="text-xs rounded-lg p-2.5 bg-gray-50 dark:bg-gray-800 border dark:border-gray-700">
								<div class="flex items-center justify-between mb-1">
									<span class="font-medium text-gray-700 dark:text-gray-200">{rt.token_name}</span>
									<div class="flex items-center gap-1">
										<button
											class="w-fit text-xs px-1.5 py-0.5 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
											on:click={() => copyToClipboard(rt.token_key)}
											title={$i18n.t('Copy Key')}
										>
											{$i18n.t('Copy')}
										</button>
										<button
											class="w-fit text-xs px-1.5 py-0.5 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg transition"
											on:click={() => handleDeleteRegistryToken(rt.id)}
											title={$i18n.t('Delete')}
										>
											{$i18n.t('Delete')}
										</button>
									</div>
								</div>
								<div class="text-gray-500 dark:text-gray-400">
									<SensitiveInput
										outerClassName="flex"
										inputClassName="w-full text-xs bg-transparent outline-hidden font-mono"
										value={rt.token_key}
										readOnly={true}
										required={false}
									/>
								</div>
								{#if rt.notes}
									<div class="text-gray-400 dark:text-gray-500 mt-0.5">{rt.notes}</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
			{/if}
		</div>
	</div>
{/if}

<!-- 고객사 추가 모달 -->
{#if showAddCustomerModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showAddCustomerModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-4 font-semibold dark:text-white">{$i18n.t('Add Customer')}</div>
			<div class="flex flex-col gap-3">
				<Input
					bind:value={addCustomerForm.company_name}
					label={$i18n.t('Company Name')}
					size="md"
					autocomplete="off"
					required
				/>
				<div class="grid grid-cols-2 gap-3">
					<div>
						<div class="mb-1.5 text-xs font-medium text-[var(--cloo-text-primary)]">
							{$i18n.t('License Type')}
						</div>
						<Selector
							value={addCustomerForm.license_type}
							items={licenseTypeOptions}
							size="md"
							on:change={(e) => {
								addCustomerForm.license_type = e.detail.value;
							}}
						/>
					</div>
					<div>
						<div class="mb-1.5 text-xs font-medium text-[var(--cloo-text-primary)]">
							{$i18n.t('Start Date')}
						</div>
						<input
							type="date"
							bind:value={addCustomerForm.start_date}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
					</div>
				</div>
				<div class="grid grid-cols-2 gap-3">
					<Input
						bind:value={addCustomerForm.contact_name}
						label={$i18n.t('Customer Contact Name')}
						size="md"
						autocomplete="off"
					/>
					<Input
						bind:value={addCustomerForm.contact_email}
						type="email"
						label={$i18n.t('Customer Contact Email')}
						size="md"
						autocomplete="off"
					/>
				</div>
				<div class="grid grid-cols-2 gap-3">
					<Input
						bind:value={addCustomerForm.admin_contact_name}
						label={$i18n.t('Admin Contact')}
						size="md"
						autocomplete="off"
					/>
					<Input
						bind:value={addCustomerForm.sales_contact_name}
						label={$i18n.t('Sales Contact')}
						size="md"
						autocomplete="off"
					/>
				</div>
				<Input
					bind:value={addCustomerForm.web_url}
					type="url"
					label={$i18n.t('Web URL')}
					placeholder="https://"
					size="md"
					autocomplete="off"
				/>
				<Textarea
					bind:value={addCustomerForm.notes}
					label={$i18n.t('Notes')}
					rows={2}
					size="md"
				/>
			</div>
			<div class="flex justify-end gap-2 mt-5">
				<Button kind="outlined" size="md" on:click={() => (showAddCustomerModal = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={addCustomerLoading} on:click={handleAddCustomer}>
					{$i18n.t('Create')}
				</Button>
			</div>
		</div>
	</div>
{/if}

<!-- 라이선스 기록 모달 -->
{#if showRecordLicenseModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showRecordLicenseModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Record License Key')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Tier')}</div>
					<select
						bind:value={recordLicenseForm.tier}
						class="dark:bg-gray-850 w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 outline-hidden"
					>
						<option value="basic">Basic</option>
						<option value="standard">Standard</option>
						<option value="professional">Professional</option>
						<option value="enterprise">Enterprise</option>
						<option value="developer">Developer</option>
					</select>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Max Users')} (0 = {$i18n.t('Unlimited')})
					</div>
					<input
						type="number"
						min="0"
						bind:value={recordLicenseForm.max_users}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('License Token')} *
					</div>
					<textarea
						bind:value={recordLicenseForm.token}
						rows="4"
						class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden resize-none"
						placeholder="eyJ..."
					></textarea>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Notes')}</div>
					<input
						type="text"
						bind:value={recordLicenseForm.notes}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showRecordLicenseModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={recordLicenseLoading} on:click={handleRecordLicense}>
				{$i18n.t('Record')}
			</Button>
		</div>
		</div>
	</div>
{/if}

<!-- 기능 키 기록 모달 -->
{#if showRecordFeatureKeyModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showRecordFeatureKeyModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Record Feature Key')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Module')} *
					</div>
					<input
						type="text"
						bind:value={recordFeatureKeyForm.module}
						placeholder="e.g. dbsphere"
						class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Feature Token')} *
					</div>
					<textarea
						bind:value={recordFeatureKeyForm.token}
						rows="4"
						class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden resize-none"
						placeholder="eyJ..."
					></textarea>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Notes')}</div>
					<input
						type="text"
						bind:value={recordFeatureKeyForm.notes}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showRecordFeatureKeyModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={recordFeatureKeyLoading} on:click={handleRecordFeatureKey}>
				{$i18n.t('Record')}
			</Button>
		</div>
		</div>
	</div>
{/if}

<!-- 라이선스 키 생성 모달 -->
{#if showGenerateLicenseModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showGenerateLicenseModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Generate License Key')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}

			{#if generatedLicenseToken}
				<!-- 생성된 키 표시 -->
				<div class="mb-4">
					<div class="mb-1 text-xs font-medium text-green-700 dark:text-green-300">
						{$i18n.t('Generated Key')}
					</div>
					<div class="relative">
						<textarea
							readonly
							value={generatedLicenseToken}
							rows="5"
							class="w-full rounded-lg py-2 px-4 text-xs font-mono bg-gray-50 dark:bg-gray-800 dark:text-gray-300 outline-hidden resize-none"
						></textarea>
						<button
							class="absolute top-2 right-2 px-2 py-1 text-xs rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 transition dark:text-gray-300"
							on:click={() => copyToClipboard(generatedLicenseToken)}
						>
							{$i18n.t('Copy')}
						</button>
					</div>
				</div>
			<div class="flex justify-end">
				<Button kind="outlined" size="md" on:click={() => (showGenerateLicenseModal = false)}>
					{$i18n.t('Close')}
				</Button>
			</div>
			{:else}
				<div class="flex flex-col gap-3">
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Tier')}</div>
						<select
							bind:value={generateLicenseForm.tier}
							class="dark:bg-gray-850 w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 outline-hidden"
						>
							<option value="basic">Basic</option>
							<option value="standard">Standard</option>
							<option value="professional">Professional</option>
							<option value="enterprise">Enterprise</option>
							<option value="developer">Developer</option>
						</select>
					</div>
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
							{$i18n.t('Max Users')} (0 = {$i18n.t('Unlimited')})
						</div>
						<input
							type="number"
							min="0"
							bind:value={generateLicenseForm.max_users}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
					</div>
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
							{$i18n.t('Expiry Date')}
						</div>
						<input
							type="date"
							bind:value={generateLicenseForm.expires}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
						{#if !generateLicenseForm.expires}
							<p class="mt-1 text-xs text-amber-600 dark:text-amber-400">
								{$i18n.t('If left empty, a permanent license will be issued (no expiry).')}
							</p>
						{/if}
					</div>
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Notes')}</div>
						<input
							type="text"
							bind:value={generateLicenseForm.notes}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
					</div>
				</div>
			<div class="flex justify-end gap-2 mt-5">
				<Button kind="outlined" size="md" on:click={() => (showGenerateLicenseModal = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={generateLicenseLoading} on:click={handleGenerateLicense}>
					{$i18n.t('Generate')}
				</Button>
			</div>
			{/if}
		</div>
	</div>
{/if}

<!-- 기능 키 생성 모달 -->
{#if showGenerateFeatureKeyModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showGenerateFeatureKeyModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Generate Feature Key')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}

			{#if generatedFeatureKeyToken}
				<div class="mb-4">
					<div class="mb-1 text-xs font-medium text-green-700 dark:text-green-300">
						{$i18n.t('Generated Key')}
					</div>
					<div class="relative">
						<textarea
							readonly
							value={generatedFeatureKeyToken}
							rows="5"
							class="w-full rounded-lg py-2 px-4 text-xs font-mono bg-gray-50 dark:bg-gray-800 dark:text-gray-300 outline-hidden resize-none"
						></textarea>
						<button
							class="absolute top-2 right-2 px-2 py-1 text-xs rounded-lg bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 transition dark:text-gray-300"
							on:click={() => copyToClipboard(generatedFeatureKeyToken)}
						>
							{$i18n.t('Copy')}
						</button>
					</div>
				</div>
			<div class="flex justify-end">
				<Button kind="outlined" size="md" on:click={() => (showGenerateFeatureKeyModal = false)}>
					{$i18n.t('Close')}
				</Button>
			</div>
			{:else}
				<div class="flex flex-col gap-3">
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
							{$i18n.t('Feature')} *
						</div>
						{#if featuresLoading}
							<div class="flex items-center gap-2 py-2 px-4 text-xs text-gray-400 dark:text-gray-500">
								<Spinner className="size-3" /> {$i18n.t('Loading...')}
							</div>
						{:else if features.length === 0}
							<div class="py-2 px-4 text-xs text-gray-400 dark:text-gray-500">
								{$i18n.t('No features registered')}
							</div>
						{:else}
							<select
								bind:value={generateFeatureKeyForm.module}
								class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
							>
								<option value="" disabled selected>{$i18n.t('Select a feature...')}</option>
								{#each features.filter(f => f.is_active) as feature}
									<option value={feature.module_id}>
										{feature.display_name} ({feature.module_id})
									</option>
								{/each}
							</select>
						{/if}
					</div>
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
							{$i18n.t('Expiry Date')}
						</div>
						<input
							type="date"
							bind:value={generateFeatureKeyForm.expires}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
						{#if !generateFeatureKeyForm.expires}
							<p class="mt-1 text-xs text-amber-600 dark:text-amber-400">
								{$i18n.t('If left empty, a permanent license will be issued (no expiry).')}
							</p>
						{/if}
					</div>
					<div>
						<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Notes')}</div>
						<input
							type="text"
							bind:value={generateFeatureKeyForm.notes}
							class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						/>
					</div>
				</div>
			<div class="flex justify-end gap-2 mt-5">
				<Button kind="outlined" size="md" on:click={() => (showGenerateFeatureKeyModal = false)}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={generateFeatureKeyLoading} on:click={handleGenerateFeatureKey}>
					{$i18n.t('Generate')}
				</Button>
			</div>
			{/if}
		</div>
	</div>
{/if}

<!-- 기능 등록 모달 -->
{#if showAddFeatureModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showAddFeatureModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-4 font-semibold dark:text-white">{$i18n.t('Register Feature')}</div>
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Module ID')} *
					</div>
					<input
						type="text"
						bind:value={addFeatureForm.module_id}
						placeholder="e.g. kbsphere"
						class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Display Name')} *
					</div>
					<input
						type="text"
						bind:value={addFeatureForm.display_name}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Description')}
					</div>
					<input
						type="text"
						bind:value={addFeatureForm.description}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Minimum Tier')}
					</div>
					<select
						bind:value={addFeatureForm.tier_minimum}
						class="dark:bg-gray-850 w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 outline-hidden"
					>
						<option value="">-</option>
						<option value="basic">Basic</option>
						<option value="standard">Standard</option>
						<option value="professional">Professional</option>
						<option value="enterprise">Enterprise</option>
						<option value="developer">Developer</option>
					</select>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showAddFeatureModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={addFeatureLoading} on:click={handleAddFeature}>
				{$i18n.t('Register')}
			</Button>
		</div>
		</div>
	</div>
{/if}

<!-- 기능 편집 모달 -->
{#if showEditFeatureModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showEditFeatureModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-4 font-semibold dark:text-white">{$i18n.t('Edit Feature')}</div>
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Module ID')}
					</div>
					<input
						type="text"
						value={editFeatureForm.module_id}
						disabled
						class="w-full rounded-lg py-2 px-4 text-sm font-mono bg-gray-100 dark:text-gray-400 dark:bg-gray-800 outline-hidden cursor-not-allowed"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Display Name')} *
					</div>
					<input
						type="text"
						bind:value={editFeatureForm.display_name}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Description')}
					</div>
					<textarea
						bind:value={editFeatureForm.description}
						rows="2"
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden resize-none"
					></textarea>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Minimum Tier')}
					</div>
					<select
						bind:value={editFeatureForm.tier_minimum}
						class="dark:bg-gray-850 w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 outline-hidden"
					>
						<option value="">-</option>
						<option value="basic">Basic</option>
						<option value="standard">Standard</option>
						<option value="professional">Professional</option>
						<option value="enterprise">Enterprise</option>
						<option value="developer">Developer</option>
					</select>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showEditFeatureModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={editFeatureLoading} on:click={handleEditFeature}>
				{$i18n.t('Save')}
			</Button>
		</div>
		</div>
	</div>
{/if}

<!-- 레지스트리 토큰 추가 모달 -->
{#if showAddRegistryTokenModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showAddRegistryTokenModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Add Registry Token')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Token Name')} *
					</div>
					<input
						type="text"
						bind:value={addRegistryTokenForm.token_name}
						placeholder="e.g. cloosphere-acr-token"
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Token Key')} *
					</div>
					<SensitiveInput
						inputClassName="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
						placeholder="..."
						bind:value={addRegistryTokenForm.token_key}
						required={false}
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">{$i18n.t('Notes')}</div>
					<input
						type="text"
						bind:value={addRegistryTokenForm.notes}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showAddRegistryTokenModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={addRegistryTokenLoading} on:click={handleAddRegistryToken}>
				{$i18n.t('Create')}
			</Button>
		</div>
		</div>
	</div>
{/if}

<!-- 크레딧 수정 모달 -->
{#if showCreditEditModal}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<div
		class="modal fixed top-0 right-0 left-0 bottom-0 bg-black/60 w-full h-screen max-h-[100dvh] flex justify-center z-[9999] overflow-y-auto overscroll-contain"
		on:mousedown|self={() => (showCreditEditModal = false)}
	>
		<div class="m-auto w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-3xl p-4">
			<div class="mb-0.5 font-semibold dark:text-white">{$i18n.t('Edit Credit')}</div>
			{#if selectedCustomer}
				<div class="mb-4 text-xs text-gray-500 dark:text-gray-400">{selectedCustomer.company_name}</div>
			{/if}
			<div class="flex flex-col gap-3">
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Total Credit')}
					</div>
					<input
						type="number"
						bind:value={creditEditForm.credit}
						min="0"
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Approval Email')}
					</div>
					<input
						type="email"
						bind:value={creditEditForm.approval_email}
						placeholder={selectedCustomer?.contact_email || 'email@example.com'}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					/>
				</div>
				<div>
					<div class="mb-1 text-xs font-medium dark:text-gray-300 text-gray-600">
						{$i18n.t('Email Channel')}
					</div>
					<select
						bind:value={creditEditForm.email_channel}
						class="w-full rounded-lg py-2 px-4 text-sm bg-gray-50 dark:text-gray-300 dark:bg-gray-850 outline-hidden"
					>
						<option value="">{$i18n.t('Default')}</option>
						{#each emailChannels as ch}
							<option value={ch.name}>{ch.name} ({ch.engine})</option>
						{/each}
					</select>
				</div>
			</div>
		<div class="flex justify-end gap-2 mt-5">
			<Button kind="outlined" size="md" on:click={() => (showCreditEditModal = false)}>
				{$i18n.t('Cancel')}
			</Button>
			<Button kind="filled" size="md" loading={creditEditSaving} on:click={handleSaveCredit}>
				{$i18n.t('Save')}
			</Button>
		</div>
		</div>
	</div>
{/if}
