<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { testEmailConnection, sendTestEmail } from '$lib/apis/notifications';
	import type { EmailChannelConfig } from '$lib/apis/notifications';

	import Modal from '$lib/components/common/Modal.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Button from '$lib/components/common/Button.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let edit = false;
	export let index = -1; // list index in saved channels (-1 = new)
	export let channel: EmailChannelConfig | null = null;
	export let onSubmit: (ch: EmailChannelConfig) => void = () => {};
	export let onDelete: () => void = () => {};

	let name = '';
	let engine = '';
	let smtp = {
		server: '',
		port: 587,
		username: '',
		password: '',
		use_tls: true,
		use_ssl: false,
		from_address: '',
		from_name: 'Cloosphere'
	};
	let sendgrid = { api_key: '', from_address: '', from_name: 'Cloosphere' };
	let azure = { connection_string: '', from_address: '', from_name: 'Cloosphere' };
	let msgraph = {
		tenant_id: '',
		client_id: '',
		client_secret: '',
		sender_email: '',
		from_name: 'Cloosphere'
	};

	let testingConnection = false;
	let sendingTestEmail = false;
	let testEmailAddress = '';

	$: engineOptions = [
		{ value: '', label: $i18n.t('Select a provider') },
		{ value: 'smtp', label: 'SMTP' },
		{ value: 'sendgrid', label: 'SendGrid' },
		{ value: 'azure', label: 'Azure Email' },
		{ value: 'msgraph', label: 'MS Graph API' }
	];

	const init = () => {
		if (channel) {
			name = channel.name ?? '';
			engine = channel.engine ?? '';
			smtp = {
				server: '',
				port: 587,
				username: '',
				password: '',
				use_tls: true,
				use_ssl: false,
				from_address: '',
				from_name: 'Cloosphere',
				...channel.smtp
			};
			sendgrid = {
				api_key: '',
				from_address: '',
				from_name: 'Cloosphere',
				...channel.sendgrid
			};
			azure = {
				connection_string: '',
				from_address: '',
				from_name: 'Cloosphere',
				...channel.azure
			};
			msgraph = {
				tenant_id: '',
				client_id: '',
				client_secret: '',
				sender_email: '',
				from_name: 'Cloosphere',
				...channel.msgraph
			};
		} else {
			name = '';
			engine = '';
			smtp = {
				server: '',
				port: 587,
				username: '',
				password: '',
				use_tls: true,
				use_ssl: false,
				from_address: '',
				from_name: 'Cloosphere'
			};
			sendgrid = { api_key: '', from_address: '', from_name: 'Cloosphere' };
			azure = { connection_string: '', from_address: '', from_name: 'Cloosphere' };
			msgraph = {
				tenant_id: '',
				client_id: '',
				client_secret: '',
				sender_email: '',
				from_name: 'Cloosphere'
			};
		}
		testEmailAddress = '';
	};

	$: if (show) init();

	const handleSecurityChange = (type: 'tls' | 'ssl') => {
		if (type === 'ssl' && smtp.use_ssl) smtp.use_tls = false;
		else if (type === 'tls' && smtp.use_tls) smtp.use_ssl = false;
	};

	const handleTestConnection = async () => {
		testingConnection = true;
		const result = await testEmailConnection(localStorage.token, index);
		testingConnection = false;
		if (result.success) {
			toast.success($i18n.t('Connection successful'));
		} else {
			toast.error($i18n.t('Connection failed') + ': ' + result.message);
		}
	};

	const handleSendTestEmail = async () => {
		if (!testEmailAddress) {
			toast.error($i18n.t('Please enter a test email address'));
			return;
		}
		sendingTestEmail = true;
		const result = await sendTestEmail(localStorage.token, testEmailAddress, index);
		sendingTestEmail = false;
		if (result.success) {
			toast.success($i18n.t('Test email sent successfully'));
		} else {
			toast.error($i18n.t('Failed to send test email') + ': ' + result.message);
		}
	};

	const submitHandler = () => {
		onSubmit({ name, engine, smtp, sendgrid, azure, msgraph });
		show = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<!-- Header -->
		<div class="flex justify-between dark:text-gray-100 px-5 pt-4 pb-2">
			<div class="text-lg font-medium self-center font-primary">
				{edit ? $i18n.t('Edit Email Channel') : $i18n.t('Add Email Channel')}
			</div>
			<button
				class="self-center"
				type="button"
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

		<!-- Body -->
		<div class="flex flex-col w-full px-4 pb-4 dark:text-gray-200">
			<form class="flex flex-col w-full" on:submit|preventDefault={submitHandler}>
				<div class="px-1 flex flex-col gap-3">
					<!-- Channel name -->
					<Input
						bind:value={name}
						label={$i18n.t('Channel Name')}
						placeholder="e.g. ops-team-smtp"
						size="md"
					/>

					<!-- Provider -->
					<LabelBase label={$i18n.t('Email Provider')} size="md">
						<svelte:fragment slot="right">
							<div class="min-w-[14rem]">
								<Selector
									value={engine ?? ''}
									items={engineOptions}
									size="sm"
									searchEnabled={false}
									on:change={(event) => {
										engine = event.detail.value;
									}}
								/>
							</div>
						</svelte:fragment>
					</LabelBase>

					{#if engine === 'smtp'}
						<!-- Server + Port -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={smtp.server}
									label={$i18n.t('SMTP Server')}
									placeholder="smtp.example.com"
									size="md"
								/>
							</div>
							<div class="w-24 shrink-0">
								<Input
									bind:value={smtp.port}
									label={$i18n.t('Port')}
									type="number"
									size="md"
								/>
							</div>
						</div>

						<!-- Username + Password -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={smtp.username}
									label={$i18n.t('Username')}
									size="md"
									autocomplete="off"
								/>
							</div>
							<div class="flex-1">
								<LabelBase label={$i18n.t('Password')} size="md" />
								<SensitiveInput
									placeholder={$i18n.t('Password')}
									bind:value={smtp.password}
									required={false}
								/>
							</div>
						</div>

						<!-- TLS / SSL -->
						<LabelBase label={$i18n.t('Use TLS (STARTTLS)')} size="md">
							<svelte:fragment slot="right">
								<Switch
									bind:state={smtp.use_tls}
									on:change={() => handleSecurityChange('tls')}
								/>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Use SSL')} size="md">
							<svelte:fragment slot="right">
								<Switch
									bind:state={smtp.use_ssl}
									on:change={() => handleSecurityChange('ssl')}
								/>
							</svelte:fragment>
						</LabelBase>

						<!-- From -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={smtp.from_address}
									label={$i18n.t('From Address')}
									type="email"
									placeholder="noreply@example.com"
									size="md"
								/>
							</div>
							<div class="flex-1">
								<Input
									bind:value={smtp.from_name}
									label={$i18n.t('From Name')}
									placeholder="Cloosphere"
									size="md"
								/>
							</div>
						</div>
					{:else if engine === 'sendgrid'}
						<!-- API Key -->
						<div>
							<LabelBase label={$i18n.t('API Key')} size="md" />
							<SensitiveInput
								placeholder={$i18n.t('Enter SendGrid API Key')}
								bind:value={sendgrid.api_key}
								required={false}
							/>
						</div>

						<!-- From -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={sendgrid.from_address}
									label={$i18n.t('From Address')}
									type="email"
									placeholder="noreply@example.com"
									size="md"
								/>
							</div>
							<div class="flex-1">
								<Input
									bind:value={sendgrid.from_name}
									label={$i18n.t('From Name')}
									placeholder="Cloosphere"
									size="md"
								/>
							</div>
						</div>
					{:else if engine === 'azure'}
						<!-- Connection String -->
						<div>
							<LabelBase label={$i18n.t('Connection String')} size="md" />
							<SensitiveInput
								placeholder={$i18n.t('Enter Azure Communication Services connection string')}
								bind:value={azure.connection_string}
								required={false}
							/>
						</div>

						<!-- From -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={azure.from_address}
									label={$i18n.t('From Address')}
									type="email"
									placeholder="DoNotReply@your-domain.azurecomm.net"
									size="md"
								/>
							</div>
							<div class="flex-1">
								<Input
									bind:value={azure.from_name}
									label={$i18n.t('From Name')}
									placeholder="Cloosphere"
									size="md"
								/>
							</div>
						</div>
					{:else if engine === 'msgraph'}
						<!-- Tenant ID -->
						<Input
							bind:value={msgraph.tenant_id}
							label={$i18n.t('Tenant ID')}
							placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
							size="md"
						/>

						<!-- Client ID + Client Secret -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={msgraph.client_id}
									label={$i18n.t('Client ID')}
									placeholder="App Registration Client ID"
									size="md"
								/>
							</div>
							<div class="flex-1">
								<LabelBase label={$i18n.t('Client Secret')} size="md" />
								<SensitiveInput
									placeholder={$i18n.t('Client Secret')}
									bind:value={msgraph.client_secret}
									required={false}
								/>
							</div>
						</div>

						<!-- Sender Email + From Name -->
						<div class="flex gap-2">
							<div class="flex-1">
								<Input
									bind:value={msgraph.sender_email}
									label={$i18n.t('Sender Email')}
									type="email"
									placeholder="noreply@company.com"
									size="md"
								/>
							</div>
							<div class="flex-1">
								<Input
									bind:value={msgraph.from_name}
									label={$i18n.t('From Name')}
									placeholder="Cloosphere"
									size="md"
								/>
							</div>
						</div>
					{/if}

					<!-- Test section (edit mode only — uses saved config at index) -->
					{#if edit && engine}
						<hr class="border-gray-100 dark:border-gray-700/10 my-0.5" />

						<LabelBase label={$i18n.t('Test Connection')} size="md">
							<svelte:fragment slot="right">
								<Button
									kind="outlined"
									size="sm"
									type="button"
									loading={testingConnection}
									disabled={testingConnection}
									on:click={handleTestConnection}
								>
									{$i18n.t('Test')}
								</Button>
							</svelte:fragment>
						</LabelBase>

						<div class="flex gap-2 items-end">
							<div class="flex-1">
								<Input
									bind:value={testEmailAddress}
									label={$i18n.t('Send Test Email')}
									type="email"
									placeholder={$i18n.t('Enter email address')}
									size="md"
								/>
							</div>
							<div class="shrink-0">
								<Button
									kind="outlined"
									size="md"
									type="button"
									loading={sendingTestEmail}
									disabled={sendingTestEmail}
									on:click={handleSendTestEmail}
								>
									{$i18n.t('Send')}
								</Button>
							</div>
						</div>
					{/if}
				</div>

				<!-- Footer -->
				<div class="flex justify-end pt-3 text-sm font-medium gap-1.5">
					{#if edit}
						<Button
							kind="outlined"
							size="md"
							type="button"
							on:click={() => {
								onDelete();
								show = false;
							}}
						>
							{$i18n.t('Delete')}
						</Button>
					{/if}
					<Button kind="filled" size="md" type="submit">
						{$i18n.t('Save')}
					</Button>
				</div>
			</form>
		</div>
	</div>
</Modal>
