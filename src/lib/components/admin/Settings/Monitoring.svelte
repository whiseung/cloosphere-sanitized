<script lang="ts">
	import {
		getMonitoringConfig,
		updateMonitoringConfig,
		downloadMonitoringBundle
	} from '$lib/apis/configs';
	import Switch from '$lib/components/common/Switch.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	let ENABLE_OTEL = false;
	let OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4318';

	let initialEnableOtel = false;
	let initialEndpoint = '';
	let downloadingBundle = false;
	let loading = true;
	let copiedCommand: string | null = null;

	let origin = '';
	$: if (typeof window !== 'undefined') {
		origin = window.location.origin;
	}

	$: setupCommands = [
		{
			label: $i18n.t('Download the monitoring package'),
			command: `curl -H "Authorization: Bearer <API_KEY>" "${origin}/api/v1/configs/monitoring/download" -o cloosphere-monitor.tar.gz`
		},
		{
			label: $i18n.t('Extract and move into directory'),
			command: 'tar xzf cloosphere-monitor.tar.gz && cd cloosphere-monitor'
		},
		{
			label: $i18n.t('Review environment variables (auto-configured from server)'),
			command: 'cat .env'
		},
		{
			label: $i18n.t('Run setup script'),
			command: './setup.sh'
		}
	];

	const copyCommand = (command: string) => {
		navigator.clipboard.writeText(command);
		copiedCommand = command;
		setTimeout(() => {
			copiedCommand = null;
		}, 2000);
	};

	$: changed =
		ENABLE_OTEL !== initialEnableOtel || OTEL_EXPORTER_OTLP_ENDPOINT !== initialEndpoint;

	const updateHandler = async () => {
		const res = await updateMonitoringConfig(localStorage.token, {
			ENABLE_OTEL,
			OTEL_EXPORTER_OTLP_ENDPOINT
		}).catch((err) => {
			toast.error($i18n.t(`${err}`));
			return null;
		});

		if (res) {
			initialEnableOtel = res.ENABLE_OTEL;
			initialEndpoint = res.OTEL_EXPORTER_OTLP_ENDPOINT;
			saveHandler();
		}
	};

	onMount(async () => {
		const config = await getMonitoringConfig(localStorage.token).catch(() => null);
		if (config) {
			ENABLE_OTEL = config.ENABLE_OTEL;
			OTEL_EXPORTER_OTLP_ENDPOINT = config.OTEL_EXPORTER_OTLP_ENDPOINT;
			initialEnableOtel = config.ENABLE_OTEL;
			initialEndpoint = config.OTEL_EXPORTER_OTLP_ENDPOINT;
		}
		loading = false;
	});
</script>

<form
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={updateHandler}
>
	<div class="mt-0.5 space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		{#if !loading}
			<div class="">
				<!-- OpenTelemetry -->
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">{$i18n.t('OpenTelemetry')}</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="mb-2.5 flex w-full items-center justify-between pr-2">
						<div class="self-center text-xs font-medium">
							{$i18n.t('Enable OpenTelemetry')}
						</div>
						<Switch bind:state={ENABLE_OTEL} />
					</div>

					{#if ENABLE_OTEL}
						<div class="mb-2.5 w-full">
							<Input
								bind:value={OTEL_EXPORTER_OTLP_ENDPOINT}
								label={$i18n.t('OTEL Endpoint')}
								caption={$i18n.t(
									'OTLP endpoint for the OpenTelemetry Collector. Use port 4318 (HTTP, recommended) or 4317 (gRPC). Cloud environments like Azure App Service require HTTP (4318).'
								)}
								placeholder="http://localhost:4318"
								size="md"
								inputClassName="font-mono"
							/>
						</div>
					{/if}

					{#if changed}
						<div
							class="mt-3 flex items-center gap-2 px-3 py-2 rounded-lg bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-400 text-xs"
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="size-4 shrink-0"
							>
								<path
									fill-rule="evenodd"
									d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 1 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
									clip-rule="evenodd"
								/>
							</svg>
							{$i18n.t('Changes will take effect after restarting the application.')}
						</div>
					{/if}
				</div>

				<!-- Monitoring Setup Download -->
				<div class="mb-3">
					<div class="mb-2.5 text-base font-medium">
						{$i18n.t('Monitoring Stack')}
					</div>

					<hr class="border-gray-100 dark:border-gray-850 my-2" />

					<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
						{$i18n.t(
							'Download the monitoring setup package (Prometheus, Grafana, Loki, OTEL Collector) to deploy on your monitoring server.'
						)}
					</div>

					<!-- Quick Start Commands -->
					<div class="mb-4 space-y-2.5">
						<div class="text-xs font-medium text-gray-600 dark:text-gray-300">
							{$i18n.t('Quick Start')}
						</div>

						{#each setupCommands as { label, command }, idx}
							<div class="space-y-1">
								<div class="text-xs text-gray-400 dark:text-gray-500">
									{idx + 1}. {label}
								</div>
								<div class="flex items-center gap-1">
									<code
										class="flex-1 block text-xs font-mono px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 text-gray-700 dark:text-gray-300 select-all"
									>
										{command}
									</code>
									<Tooltip content={$i18n.t('Copy')}>
										<Button
											kind="text"
											size="sm"
											type="button"
											on:click={() => copyCommand(command)}
										>
											{#if copiedCommand === command}
												<Check className="size-3.5 text-green-500" />
											{:else}
												<Clipboard className="size-3.5" />
											{/if}
										</Button>
									</Tooltip>
								</div>
								{#if idx === 0}
									<div class="text-xs text-gray-400 dark:text-gray-500 mt-1 ml-0.5">
										* {$i18n.t('<API_KEY>: Click your profile icon (bottom-left) → Settings → Account → API keys')}
									</div>
								{/if}
							</div>
						{/each}
					</div>

					<div class="flex items-center gap-3 my-3">
						<hr class="flex-1 border-gray-200 dark:border-gray-700" />
						<span class="text-xs text-gray-400 dark:text-gray-500">{$i18n.t('or')}</span>
						<hr class="flex-1 border-gray-200 dark:border-gray-700" />
					</div>

					<Button
						kind="outlined"
						size="sm"
						type="button"
						disabled={downloadingBundle}
						loading={downloadingBundle}
						on:click={async () => {
							downloadingBundle = true;
							try {
								await downloadMonitoringBundle(localStorage.token);
								toast.success($i18n.t('Monitoring setup downloaded'));
							} catch (e) {
								toast.error($i18n.t(`${e}`));
							} finally {
								downloadingBundle = false;
							}
						}}
					>
						<svelte:fragment slot="prefix">
							<ArrowDownTray className="size-4" />
						</svelte:fragment>
						{downloadingBundle ? $i18n.t('Downloading...') : $i18n.t('Download via Browser')}
					</Button>
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
