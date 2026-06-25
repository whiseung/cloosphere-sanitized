<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { createInquiry, getMyInquiries, closeInquiry } from '$lib/apis/inquiries';
	import Button from '$lib/components/common/Button.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	type I18nStore = Readable<{ t: (key: string) => string }>;

	const i18n = getContext<I18nStore>('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;

	const INQUIRY_TYPES: Record<string, { label: string; subtypes: Record<string, string> }> = {
		usage_limit: {
			label: 'Usage Limit',
			subtypes: {
				limit_increase: 'Limit Increase Request',
				limit_check: 'Limit Check'
			}
		},
		feature: {
			label: 'Feature Inquiry',
			subtypes: {
				chat: 'Chat',
				agent: 'Agent',
				knowledge: 'Knowledge Base',
				database: 'Database',
				tool: 'Tool'
			}
		},
		bug: {
			label: 'Bug Report',
			subtypes: {
				chat_error: 'Chat Error',
				agent_error: 'Agent Error',
				upload_error: 'Upload Error',
				other_error: 'Other Error'
			}
		},
		account: {
			label: 'Account / Permission',
			subtypes: {
				permission_request: 'Permission Request',
				account_issue: 'Account Issue'
			}
		},
		other: {
			label: 'Other',
			subtypes: {
				improvement: 'Improvement Suggestion',
				other: 'Other'
			}
		}
	};

	const STATUS_CONFIG: Record<string, { label: string; class: string }> = {
		open: {
			label: 'Open',
			class: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/50 dark:text-yellow-200'
		},
		in_progress: {
			label: 'In Progress',
			class: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200'
		},
		resolved: {
			label: 'Resolved',
			class: 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200'
		},
		closed: {
			label: 'Closed',
			class: 'bg-gray-100 text-gray-600 dark:bg-gray-700/50 dark:text-gray-400'
		}
	};

	let activeTab: 'new' | 'history' = 'new';

	// Form state
	let title = '';
	let type = '';
	let subtype = '';
	let content = '';
	let loading = false;

	// History state
	let myInquiries: any[] = [];
	let historyLoading = false;
	let expandedId: string | null = null;
	let historyLoaded = false;

	// Badge count (responded inquiries)
	export let badgeCount = 0;

	$: availableSubtypes = type ? INQUIRY_TYPES[type]?.subtypes ?? {} : {};
	$: if (type) {
		subtype = '';
	}

	$: typeItems = Object.entries(INQUIRY_TYPES).map(([value, info]) => ({
		value,
		label: $i18n.t(info.label)
	}));
	$: subtypeItems = Object.entries(availableSubtypes).map(([value, label]) => ({
		value,
		label: $i18n.t(label)
	}));

	$: if (show) {
		resetForm();
		historyLoaded = false;
		expandedId = null;
	}

	$: if (show && activeTab === 'history' && !historyLoaded) {
		loadMyInquiries();
	}

	$: badgeCount = myInquiries.filter((i) => i.admin_note && i.status !== 'closed').length;

	const loadMyInquiries = async () => {
		historyLoading = true;
		try {
			myInquiries = await getMyInquiries(localStorage.token);
			historyLoaded = true;
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		} finally {
			historyLoading = false;
		}
	};

	const submitHandler = async () => {
		if (!title.trim() || !type || !subtype || !content.trim()) {
			toast.error($i18n.t('Please fill in all fields'));
			return;
		}

		loading = true;
		try {
			const res = await createInquiry(localStorage.token, {
				title: title.trim(),
				type,
				subtype,
				content: content.trim()
			});

			if (res) {
				toast.success($i18n.t('Inquiry submitted successfully'));
				dispatch('submit');
				resetForm();
				// Switch to history tab to show the new inquiry
				historyLoaded = false;
				activeTab = 'history';
			}
		} catch (error) {
			toast.error($i18n.t(`${error}`));
		} finally {
			loading = false;
		}
	};

	const handleClose = async (inquiryId: string) => {
		try {
			await closeInquiry(localStorage.token, inquiryId);
			toast.success($i18n.t('Inquiry closed'));
			historyLoaded = false;
			await loadMyInquiries();
		} catch (e) {
			toast.error($i18n.t(`${e}`));
		}
	};

	const resetForm = () => {
		title = '';
		type = '';
		subtype = '';
		content = '';
	};

	const formatDate = (timestamp: number) => {
		return new Date(timestamp * 1000).toLocaleDateString(undefined, {
			year: 'numeric',
			month: '2-digit',
			day: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	};

	export const loadBadgeCount = async () => {
		try {
			const inquiries = await getMyInquiries(localStorage.token);
			myInquiries = inquiries;
			historyLoaded = true;
		} catch (e) {
			// silent
		}
	};
</script>

<Modal size="md" bind:show>
	<div>
		<div class="flex justify-between dark:text-gray-300 px-5 py-4">
			<div class="text-lg font-medium self-center">{$i18n.t('Contact Admin')}</div>
			<button
				class="self-center"
				on:click={() => {
					show = false;
				}}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="w-5 h-5"
				>
					<path
						d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z"
					/>
				</svg>
			</button>
		</div>

		<!-- Tabs -->
		<div class="flex border-b border-gray-100 dark:border-gray-850 px-5">
			<button
				class="px-4 py-2 text-sm font-medium transition {activeTab === 'new'
					? 'border-b-2 border-black dark:border-white text-black dark:text-white'
					: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
				on:click={() => {
					activeTab = 'new';
				}}
			>
				{$i18n.t('New Inquiry')}
			</button>
			<button
				class="px-4 py-2 text-sm font-medium transition flex items-center gap-1.5 {activeTab ===
				'history'
					? 'border-b-2 border-black dark:border-white text-black dark:text-white'
					: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
				on:click={() => {
					activeTab = 'history';
				}}
			>
				{$i18n.t('My Inquiries')}
				{#if badgeCount > 0}
					<span class="size-2 rounded-full bg-green-500"></span>
				{/if}
			</button>
		</div>

		{#if activeTab === 'new'}
			<!-- New Inquiry Form -->
			<form
				class="flex flex-col p-5 gap-3 dark:text-gray-200"
				on:submit|preventDefault={submitHandler}
			>
				<div class="flex flex-col">
					<div class="mb-1 text-xs text-gray-500">{$i18n.t('Type')}</div>
					<Selector
						bind:value={type}
						items={typeItems}
						placeholder={$i18n.t('Select type')}
						searchEnabled={false}
						size="md"
						portal={null}
						ariaLabel={$i18n.t('Type')}
					/>
				</div>

				{#if type}
					<div class="flex flex-col">
						<div class="mb-1 text-xs text-gray-500">{$i18n.t('Subtype')}</div>
						<Selector
							bind:value={subtype}
							items={subtypeItems}
							placeholder={$i18n.t('Select subtype')}
							searchEnabled={false}
							size="md"
							portal={null}
							ariaLabel={$i18n.t('Subtype')}
						/>
					</div>
				{/if}

				<div class="flex flex-col">
					<div class="mb-1 text-xs text-gray-500">{$i18n.t('Title')}</div>
					<input
						class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 outline-hidden"
						type="text"
						bind:value={title}
						placeholder={$i18n.t('Enter title')}
						required
					/>
				</div>

				<div class="flex flex-col">
					<div class="mb-1 text-xs text-gray-500">{$i18n.t('Inquiry Content')}</div>
					<textarea
						class="w-full rounded-sm py-2 px-4 text-sm dark:text-gray-300 dark:bg-gray-800 outline-hidden resize-none"
						rows="5"
						bind:value={content}
						placeholder={$i18n.t('Describe your inquiry in detail')}
						required
					></textarea>
				</div>

				<div class="flex justify-end pt-2">
					<Button kind="filled" size="md" type="submit" {loading}>
						{$i18n.t('Submit')}
					</Button>
				</div>
			</form>
		{:else}
			<!-- Inquiry History -->
			<div class="p-5 dark:text-gray-200 max-h-[60vh] overflow-y-auto">
				{#if historyLoading}
					<div class="flex justify-center py-8">
						<Spinner />
					</div>
				{:else if myInquiries.length === 0}
					<div class="text-center text-gray-500 py-8">
						{$i18n.t('No inquiries')}
					</div>
				{:else}
					<div class="flex flex-col gap-2">
						{#each myInquiries as inquiry (inquiry.id)}
							<div
								class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden"
							>
								<!-- svelte-ignore a11y-click-events-have-key-events -->
								<div
									class="w-full text-left p-3 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/50 transition"
									role="button"
									tabindex="0"
									on:click={() => {
										expandedId = expandedId === inquiry.id ? null : inquiry.id;
									}}
								>
									<div class="flex items-center justify-between gap-2">
										<div class="flex-1 min-w-0">
											<div class="flex items-center gap-2">
												<div class="font-medium text-sm truncate">
													{inquiry.title}
												</div>
												{#if inquiry.admin_note}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 20 20"
														fill="currentColor"
														class="size-4 shrink-0 text-blue-500"
													>
														<path
															fill-rule="evenodd"
															d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-11.25a.75.75 0 00-1.5 0v2.5h-2.5a.75.75 0 000 1.5h2.5v2.5a.75.75 0 001.5 0v-2.5h2.5a.75.75 0 000-1.5h-2.5v-2.5z"
															clip-rule="evenodd"
														/>
													</svg>
												{/if}
											</div>
											<div class="text-xs text-gray-500 mt-0.5">
												{$i18n.t(
													INQUIRY_TYPES[inquiry.type]?.label ?? inquiry.type
												)}
												&middot; {formatDate(inquiry.created_at)}
											</div>
										</div>
										<div class="flex items-center gap-2 shrink-0">
											<span
												class="px-2 py-0.5 rounded-full text-xs font-medium {STATUS_CONFIG[
													inquiry.status
												]?.class ?? ''}"
											>
												{$i18n.t(
													STATUS_CONFIG[inquiry.status]?.label ??
														inquiry.status
												)}
											</span>
											<svg
												xmlns="http://www.w3.org/2000/svg"
												viewBox="0 0 20 20"
												fill="currentColor"
												class="size-4 text-gray-400 transition-transform {expandedId ===
												inquiry.id
													? 'rotate-180'
													: ''}"
											>
												<path
													fill-rule="evenodd"
													d="M5.22 8.22a.75.75 0 011.06 0L10 11.94l3.72-3.72a.75.75 0 111.06 1.06l-4.25 4.25a.75.75 0 01-1.06 0L5.22 9.28a.75.75 0 010-1.06z"
													clip-rule="evenodd"
												/>
											</svg>
										</div>
									</div>
								</div>

								{#if expandedId === inquiry.id}
									<div
										class="px-3 pb-3 space-y-3 border-t border-gray-100 dark:border-gray-700"
									>
										<div class="pt-3">
											<div class="text-xs text-gray-500 mb-1">
												{$i18n.t('Inquiry Content')}
											</div>
											<div
												class="text-sm whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 rounded-sm p-3"
											>
												{inquiry.content}
											</div>
										</div>

										{#if inquiry.admin_note}
											<div>
												<div class="text-xs text-gray-500 mb-1">
													{$i18n.t('Admin Response')}
												</div>
												<div
													class="text-sm whitespace-pre-wrap bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-sm p-3"
												>
													{inquiry.admin_note}
												</div>
											</div>
										{/if}

										<div class="flex items-center justify-between">
											{#if inquiry.updated_at !== inquiry.created_at}
												<div class="text-xs text-gray-400">
													{$i18n.t('Updated')}: {formatDate(inquiry.updated_at)}
												</div>
											{:else}
												<div></div>
											{/if}

											{#if inquiry.status !== 'closed'}
												<Button
													kind="outlined"
													size="sm"
													on:click={() => handleClose(inquiry.id)}
												>
													{$i18n.t('Close Inquiry')}
												</Button>
											{/if}
										</div>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</Modal>
