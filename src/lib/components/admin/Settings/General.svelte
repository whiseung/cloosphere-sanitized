<script lang="ts">
	import DOMPurify from 'dompurify';

	import { getBackendConfig, getVersionUpdates, getWebhookUrl, updateWebhookUrl } from '$lib/apis';
	import {
		getAdminConfig,
		getLdapConfig,
		getLdapServer,
		updateAdminConfig,
		updateLdapConfig,
		updateLdapServer
	} from '$lib/apis/auths';
	import { getGroups } from '$lib/apis/groups';
	import Button from '$lib/components/common/Button.svelte';
	import Form, { type FormItem } from '$lib/components/common/Form.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ConnectionCheckModal from './General/ConnectionCheckModal.svelte';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION } from '$lib/constants';
	import { config, showChangelog } from '$lib/stores';
	import { compareVersion } from '$lib/utils';
	import { onMount, getContext } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	type I18nStore = Readable<{ t: (key: string) => string }>;

	const i18n = getContext<I18nStore>('i18n');

	export let saveHandler: Function;

	let updateAvailable = null;
	let showConnectionCheck = false;
	let version = {
		current: '',
		latest: ''
	};

	let adminConfig: any = null;
	let webhookUrl = '';
	let groups: Array<{ id: string; name: string }> = [];

	// LDAP
	let ENABLE_LDAP = false;
	let LDAP_SERVER = {
		label: '',
		host: '',
		port: '',
		attribute_for_mail: 'mail',
		attribute_for_username: 'uid',
		app_dn: '',
		app_dn_password: '',
		search_base: '',
		search_filters: '',
		use_tls: false,
		certificate_path: '',
		ciphers: ''
	};

	// Selector items are flat ({value, label}[]); flatten optgroup by prefixing group rows
	// with the localized "Group" label so they remain visually distinct from base roles.
	$: roleOptions = [
		{ value: 'pending', label: $i18n.t('pending') },
		{ value: 'user', label: $i18n.t('user') },
		{ value: 'admin', label: $i18n.t('admin') },
		...groups.map((group) => ({
			value: `user:group:${group.id}`,
			label: `${$i18n.t('Group')}: ${group.name}`
		}))
	];

	$: featureItems = (adminConfig
		? [
				{
					id: 'community',
					label: $i18n.t('Enable Community Sharing'),
					state: !!adminConfig.ENABLE_COMMUNITY_SHARING
				},
				{
					id: 'rating',
					label: $i18n.t('Enable Message Rating'),
					state: !!adminConfig.ENABLE_MESSAGE_RATING
				},
				{
					id: 'channels',
					label: `${$i18n.t('Channels')} (${$i18n.t('Beta')})`,
					state: !!adminConfig.ENABLE_CHANNELS
				},
				{
					id: 'webhooks',
					label: $i18n.t('User Webhooks'),
					state: !!adminConfig.ENABLE_USER_WEBHOOKS
				}
			]
		: []) satisfies FormItem[];

	const handleFeatureChange = (
		event: CustomEvent<{ index: number; nextState: boolean; item: FormItem }>
	) => {
		if (!adminConfig) return;
		const { item, nextState } = event.detail;
		switch (item.id) {
			case 'community':
				adminConfig.ENABLE_COMMUNITY_SHARING = nextState;
				break;
			case 'rating':
				adminConfig.ENABLE_MESSAGE_RATING = nextState;
				break;
			case 'channels':
				adminConfig.ENABLE_CHANNELS = nextState;
				break;
			case 'webhooks':
				adminConfig.ENABLE_USER_WEBHOOKS = nextState;
				break;
		}
	};

	const checkForVersionUpdates = async () => {
		updateAvailable = null;
		version = await getVersionUpdates(localStorage.token).catch((error) => {
			return {
				current: WEBUI_VERSION,
				latest: WEBUI_VERSION
			};
		});

		updateAvailable = compareVersion(version.latest, version.current);
	};

	const updateLdapServerHandler = async () => {
		if (!ENABLE_LDAP) return;
		const res = await updateLdapServer(localStorage.token, LDAP_SERVER).catch((error) => {
			toast.error($i18n.t(`${error}`));
			return null;
		});
		if (res) {
			toast.success($i18n.t('LDAP server updated'));
		}
	};

	const JWT_DURATION_PATTERN = /^(-1|0|(-?\d+(\.\d+)?)(ms|s|m|h|d|w))$/;

	const updateHandler = async () => {
		if (
			adminConfig.JWT_EXPIRES_IN &&
			!JWT_DURATION_PATTERN.test(adminConfig.JWT_EXPIRES_IN.trim())
		) {
			toast.error(
				$i18n.t("Invalid JWT expiration format. Use '30m', '1h', '10d', or '-1' for no expiration.")
			);
			return;
		}

		webhookUrl = await updateWebhookUrl(localStorage.token, webhookUrl);
		const res = await updateAdminConfig(localStorage.token, adminConfig);
		await updateLdapServerHandler();

		if (res) {
			saveHandler();
		} else {
			toast.error($i18n.t('Failed to update settings'));
		}
	};

	onMount(async () => {
		checkForVersionUpdates();

		await Promise.all([
			(async () => {
				adminConfig = await getAdminConfig(localStorage.token);
			})(),

			(async () => {
				webhookUrl = await getWebhookUrl(localStorage.token);
			})(),
			(async () => {
				LDAP_SERVER = await getLdapServer(localStorage.token);
			})(),
			(async () => {
				groups = await getGroups(localStorage.token).catch(() => []);
			})()
		]);

		const ldapConfig = await getLdapConfig(localStorage.token);
		ENABLE_LDAP = ldapConfig.ENABLE_LDAP;
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		updateHandler();
	}}
>
	<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		{#if adminConfig !== null}
			<div>
				<!-- Version Section -->
				<div class="mb-3.5">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('General')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5">
						<div class=" mb-1 text-xs font-medium flex space-x-2 items-center">
							<div>{$i18n.t('Version')}</div>
						</div>
						<div class="flex w-full justify-between items-center">
							<div class="flex flex-col text-xs text-gray-700 dark:text-gray-200">
								<div class="flex gap-1">
									<Tooltip content={WEBUI_BUILD_HASH}>
										v{WEBUI_VERSION}
									</Tooltip>
								</div>
							</div>
							<Button kind="outlined" size="sm" on:click={() => (showConnectionCheck = true)}>
								{$i18n.t('Settings Status')}
							</Button>
						</div>
					</div>
				</div>

				<!-- Authentication Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('Authentication')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-2.5 pr-2">
						<LabelBase label={$i18n.t('Default User Role')} size="md">
							<svelte:fragment slot="right">
								<div class="min-w-[14rem]">
									<Selector
										value={adminConfig.DEFAULT_USER_ROLE}
										items={roleOptions}
										placeholder="Select a role"
										size="sm"
										on:change={(event) => {
											adminConfig.DEFAULT_USER_ROLE = event.detail.value;
										}}
									/>
								</div>
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Enable New Sign Ups')} size="md">
							<svelte:fragment slot="right">
								<Switch bind:state={adminConfig.ENABLE_SIGNUP} />
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Enable Onboarding')} size="md">
							<svelte:fragment slot="right">
								<Switch bind:state={adminConfig.ENABLE_ONBOARDING} />
							</svelte:fragment>
						</LabelBase>

						<LabelBase
							label={$i18n.t('Show Admin Details in Account Pending Overlay')}
							size="md"
						>
							<svelte:fragment slot="right">
								<Switch bind:state={adminConfig.SHOW_ADMIN_DETAILS} />
							</svelte:fragment>
						</LabelBase>

						<LabelBase label={$i18n.t('Enable API Key')} size="md">
							<svelte:fragment slot="right">
								<Switch bind:state={adminConfig.ENABLE_API_KEY} />
							</svelte:fragment>
						</LabelBase>

						{#if adminConfig?.ENABLE_API_KEY}
							<LabelBase label={$i18n.t('API Key Endpoint Restrictions')} size="md">
								<svelte:fragment slot="right">
									<Switch bind:state={adminConfig.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS} />
								</svelte:fragment>
							</LabelBase>

							{#if adminConfig?.ENABLE_API_KEY_ENDPOINT_RESTRICTIONS}
								<div>
									<Input
										bind:value={adminConfig.API_KEY_ALLOWED_ENDPOINTS}
										label={$i18n.t('Allowed Endpoints')}
										placeholder={'e.g.) /api/v1/messages, /api/v1/channels'}
										size="md"
									/>

									<div class="mt-1.5 text-xs text-gray-400 dark:text-gray-500">
										<a
											href="/guide"
											target="_blank"
											class=" text-gray-300 font-medium underline"
										>
											{$i18n.t('To learn more about available endpoints, visit our documentation.')}
										</a>
									</div>
								</div>
							{/if}
						{/if}

						<Input
							bind:value={adminConfig.JWT_EXPIRES_IN}
							label={$i18n.t('JWT Expiration')}
							caption={`${$i18n.t('Valid time units:')} ${$i18n.t("'s', 'm', 'h', 'd', 'w' or '-1' for no expiration.")}`}
							placeholder={'e.g.) "30m","1h", "10d".'}
							size="md"
						/>
					</div>

					<!-- LDAP -->
					<div class="mt-3 pr-2">
						<LabelBase label={$i18n.t('LDAP')} size="md">
							<svelte:fragment slot="right">
								<Switch
									bind:state={ENABLE_LDAP}
									on:change={async () => {
										updateLdapConfig(localStorage.token, ENABLE_LDAP);
									}}
								/>
							</svelte:fragment>
						</LabelBase>

						{#if ENABLE_LDAP}
							<div class="flex flex-col gap-2.5 mt-2.5">
								<div class="flex w-full gap-2">
									<div class="w-full">
										<Input
											bind:value={LDAP_SERVER.label}
											label={$i18n.t('Label')}
											placeholder={$i18n.t('Enter server label')}
											size="md"
											required
										/>
									</div>
									<div class="w-full"></div>
								</div>

								<div class="flex w-full gap-2">
									<div class="w-full">
										<Input
											bind:value={LDAP_SERVER.host}
											label={$i18n.t('Host')}
											placeholder={$i18n.t('Enter server host')}
											size="md"
											required
										/>
									</div>
									<div class="w-full">
										<Input
											bind:value={LDAP_SERVER.port}
											label={$i18n.t('Port')}
											caption={$i18n.t('Default to 389 or 636 if TLS is enabled')}
											placeholder={$i18n.t('Enter server port')}
											type="number"
											size="md"
										/>
									</div>
								</div>

								<div class="flex w-full gap-2">
									<div class="w-full">
										<Input
											bind:value={LDAP_SERVER.app_dn}
											label={$i18n.t('Application DN')}
											caption={$i18n.t('The Application Account DN you bind with for search')}
											placeholder={$i18n.t('Enter Application DN')}
											size="md"
											required
										/>
									</div>
									<div class="w-full">
										<LabelBase label={$i18n.t('Application DN Password')} size="md" />
										<SensitiveInput
											placeholder={$i18n.t('Enter Application DN Password')}
											bind:value={LDAP_SERVER.app_dn_password}
										/>
									</div>
								</div>

								<Input
									bind:value={LDAP_SERVER.attribute_for_mail}
									label={$i18n.t('Attribute for Mail')}
									caption={$i18n.t(
										'The LDAP attribute that maps to the mail that users use to sign in.'
									)}
									placeholder={$i18n.t('Example: mail')}
									size="md"
									required
								/>

								<Input
									bind:value={LDAP_SERVER.attribute_for_username}
									label={$i18n.t('Attribute for Username')}
									caption={$i18n.t(
										'The LDAP attribute that maps to the username that users use to sign in.'
									)}
									placeholder={$i18n.t('Example: sAMAccountName or uid or userPrincipalName')}
									size="md"
									required
								/>

								<Input
									bind:value={LDAP_SERVER.search_base}
									label={$i18n.t('Search Base')}
									caption={$i18n.t('The base to search for users')}
									placeholder={$i18n.t('Example: ou=users,dc=foo,dc=example')}
									size="md"
									required
								/>

								<Input
									bind:value={LDAP_SERVER.search_filters}
									label={$i18n.t('Search Filters')}
									placeholder={$i18n.t('Example: (&(objectClass=inetOrgPerson)(uid=%s))')}
									size="md"
								/>

								<div class="text-xs text-gray-400 dark:text-gray-500">
									<a
										class=" text-gray-300 font-medium underline"
										href="https://ldap.com/ldap-filters/"
										target="_blank"
									>
										{$i18n.t('Click here for filter guides.')}
									</a>
								</div>

								<LabelBase label={$i18n.t('TLS')} size="md">
									<svelte:fragment slot="right">
										<Switch bind:state={LDAP_SERVER.use_tls} />
									</svelte:fragment>
								</LabelBase>

								{#if LDAP_SERVER.use_tls}
									<Input
										bind:value={LDAP_SERVER.certificate_path}
										label={$i18n.t('Certificate Path')}
										placeholder={$i18n.t('Enter certificate path')}
										size="md"
									/>

									<div class="flex w-full gap-2">
										<div class="w-full">
											<Input
												bind:value={LDAP_SERVER.ciphers}
												label={$i18n.t('Ciphers')}
												caption={$i18n.t('Default to ALL')}
												placeholder={$i18n.t('Example: ALL')}
												size="md"
											/>
										</div>
										<div class="w-full"></div>
									</div>
								{/if}
							</div>
						{/if}
					</div>
				</div>

				<!-- 사용량 제한 설정은 [관리자 > 설정 > 모델 > Token Limit] 모달로 이동 -->

				<!-- Features Section -->
				<div class="mb-3">
					<div class=" mb-2.5 text-base font-medium">{$i18n.t('Features')}</div>

					<hr class=" border-gray-100 dark:border-gray-850 my-2" />

					<div class="flex flex-col gap-3 pr-2">
						<Form items={featureItems} on:change={handleFeatureChange} />

						<Input
							bind:value={adminConfig.WEBUI_URL}
							label={$i18n.t('WebUI URL')}
							caption={$i18n.t(
								'Enter the public URL of your WebUI. This URL will be used to generate links in the notifications.'
							)}
							placeholder={'e.g.) "http://localhost:3000"'}
							size="md"
						/>

						<Input
							bind:value={webhookUrl}
							label={$i18n.t('Webhook URL')}
							placeholder={'https://example.com/webhook'}
							size="md"
						/>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<Button kind="filled" size="md" type="submit">
			{$i18n.t('Save')}
		</Button>
	</div>
</form>

<ConnectionCheckModal bind:show={showConnectionCheck} />
