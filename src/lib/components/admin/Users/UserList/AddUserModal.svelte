<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher } from 'svelte';
	import { onMount, getContext } from 'svelte';
	import { addUser } from '$lib/apis/auths';

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { config } from '$lib/stores';

	import Button from '$lib/components/common/Button.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Tabs from '$lib/components/common/Tabs.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;

	let loading = false;
	let tab: '' | 'import' = '';
	let inputFiles: FileList | null = null;

	let _user = {
		name: '',
		email: '',
		password: '',
		role: 'user'
	};

	$: roleItems = [
		{ value: 'pending', label: $i18n.t('pending') },
		{ value: 'user', label: $i18n.t('user') },
		{ value: 'admin', label: $i18n.t('admin') }
	];

	$: tabItems = [
		{
			id: 'form',
			labelKey: 'Form',
			href: '#form',
			state: (tab === '' ? 'selected' : 'default') as 'selected' | 'default'
		},
		{
			id: 'import',
			labelKey: 'CSV Import',
			href: '#import',
			state: (tab === 'import' ? 'selected' : 'default') as 'selected' | 'default'
		}
	];

	$: if (show) {
		_user = {
			name: '',
			email: '',
			password: '',
			role: 'user'
		};
	}

	const handleTabClick = (event: MouseEvent) => {
		const target = (event.target as HTMLElement)?.closest('a[href^="#"]') as HTMLAnchorElement | null;
		if (!target) return;
		event.preventDefault();
		const href = target.getAttribute('href');
		if (href === '#form') tab = '';
		else if (href === '#import') tab = 'import';
	};

	const submitHandler = async () => {
		const stopLoading = () => {
			dispatch('save');
			loading = false;
		};

		if (tab === '') {
			loading = true;

			const res = await addUser(
				localStorage.token,
				_user.name,
				_user.email,
				_user.password,
				_user.role
			).catch((error) => {
				toast.error($i18n.t(`${error}`));
			});

			if (res) {
				stopLoading();
				show = false;
			}
		} else {
			if (inputFiles) {
				loading = true;

				const file = inputFiles[0];
				const reader = new FileReader();

				reader.onload = async (e) => {
					const buffer = e.target?.result as ArrayBuffer;

					// Try UTF-8 first, fallback to EUC-KR for Korean Windows CSV
					let csv = new TextDecoder('utf-8').decode(buffer);
					if (csv.includes('�')) {
						csv = new TextDecoder('euc-kr').decode(buffer);
					}

					// Remove BOM if present
					if (csv.charCodeAt(0) === 0xfeff) {
						csv = csv.slice(1);
					}

					const rows = csv.split(/\r?\n/).filter((row) => row.trim() !== '');

					let userCount = 0;

					for (const [idx, row] of rows.entries()) {
						if (idx === 0) continue; // skip header

						const columns = row.split(',').map((col) => col.trim());
						console.log(idx, columns);

						if (
							columns.length === 4 &&
							['admin', 'user', 'pending'].includes(columns[3].toLowerCase())
						) {
							const res = await addUser(
								localStorage.token,
								columns[0],
								columns[1],
								columns[2],
								columns[3].toLowerCase()
							).catch((error) => {
								toast.error($i18n.t('Row {{row}}: {{error}}', { row: idx + 1, error }));
								return null;
							});

							if (res) {
								userCount = userCount + 1;
							}
						} else {
							toast.error($i18n.t('Row {{row}}: invalid format.', { row: idx + 1 }));
						}
					}

					toast.success($i18n.t('Successfully imported {{count}} users.', { count: userCount }));
					inputFiles = null;
					const uploadInputElement = document.getElementById(
						'upload-user-csv-input'
					) as HTMLInputElement | null;

					if (uploadInputElement) {
						uploadInputElement.value = '';
					}

					stopLoading();
				};

				reader.readAsArrayBuffer(file);
			} else {
				toast.error($i18n.t('File not found.'));
			}
		}

		loading = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center">{$i18n.t('Add User')}</div>
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

		<div class="flex flex-col w-full px-4 pb-3 dark:text-gray-200">
			<form
				class="flex flex-col w-full"
				on:submit|preventDefault={submitHandler}
			>
				<!-- svelte-ignore a11y-click-events-have-key-events -->
				<!-- svelte-ignore a11y-no-static-element-interactions -->
				<div class="-mt-1 mb-2" on:click={handleTabClick}>
					<Tabs items={tabItems} />
				</div>

				<div class="px-1">
					{#if tab === ''}
						<div class="flex flex-col w-full gap-3">
							<div class="flex flex-col gap-1">
								<div class="text-xs text-gray-500">{$i18n.t('Role')}</div>
								<Selector
									value={_user.role}
									items={roleItems}
									size="md"
									searchEnabled={false}
									portal="body"
									contentClassName="z-[10000]"
									on:change={(e) => {
										_user.role = e.detail.value;
									}}
								/>
							</div>

							<Input
								bind:value={_user.name}
								label={$i18n.t('Name')}
								placeholder={$i18n.t('Enter Your Full Name')}
								size="md"
								required
							/>

							<hr class=" border-gray-100 dark:border-gray-850 w-full" />

							<Input
								bind:value={_user.email}
								label={$config?.features?.enable_email_deidentify
									? $i18n.t('Account ID')
									: $i18n.t('Email')}
								placeholder={$config?.features?.enable_email_deidentify
									? $i18n.t('Enter Account ID')
									: $i18n.t('Enter Your Email')}
								type={$config?.features?.enable_email_deidentify ? 'text' : 'email'}
								size="md"
								required
							/>

							<Input
								bind:value={_user.password}
								label={$i18n.t('Password')}
								placeholder={$i18n.t('Enter Your Password')}
								type="password"
								size="md"
							/>
						</div>
					{:else if tab === 'import'}
						<div>
							<div class="mb-3 w-full">
								<input
									id="upload-user-csv-input"
									hidden
									bind:files={inputFiles}
									type="file"
									accept=".csv"
								/>

								<button
									class="w-full text-sm font-medium py-3 bg-transparent hover:bg-gray-100 border border-dashed dark:border-gray-850 dark:hover:bg-gray-850 text-center rounded-xl"
									type="button"
									on:click={() => {
										document.getElementById('upload-user-csv-input')?.click();
									}}
								>
									{#if inputFiles}
										{inputFiles.length > 0 ? `${inputFiles.length}` : ''} document(s) selected.
									{:else}
										{$i18n.t('Click here to select a csv file.')}
									{/if}
								</button>
							</div>

							<div class=" text-xs text-gray-500">
								ⓘ {$i18n.t(
									'Ensure your CSV file includes 4 columns in this order: Name, Email, Password, Role.'
								)}
								<a
									class="underline dark:text-gray-200"
									href="{WEBUI_BASE_URL}/static/user-import.csv"
								>
									{$i18n.t('Click here to download user import template file.')}
								</a>
							</div>
						</div>
					{/if}
				</div>

				<div class="flex justify-end pt-3 text-sm font-medium">
					<Button kind="filled" size="md" type="submit" {loading}>
						{$i18n.t('Save')}
					</Button>
				</div>
			</form>
		</div>
	</div>
</Modal>
