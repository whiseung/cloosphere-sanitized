<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import { toast } from 'svelte-sonner';

	import Modal from '$lib/components/common/Modal.svelte';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import Selector from '$lib/components/common/Selector.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import { config } from '$lib/stores';
	import { testDbConnection, getDbTables, type ConnectionTestForm } from '$lib/apis/dbsphere';

	const i18n = getContext<Readable<{ t: (key: string) => string }>>('i18n');
	const dispatch = createEventDispatcher();

	type FieldType = 'text' | 'number' | 'password' | 'json-textarea' | 'service-account-json';

	type FieldDef = {
		key: string;
		labelKey: string;
		type: FieldType;
		required?: boolean;
		placeholder?: string;
		defaultValue?: string | number;
		/** Masked in edit mode; dirty-tracked so untouched value is preserved server-side (P-H1). */
		sensitive?: boolean;
	};

	export let show: boolean = false;
	/** Existing connection values when editing. Sensitive fields come back as
	 * mask placeholders ("**********") — we keep them masked unless the user
	 * types a new value, so the original cleartext never leaves the server. */
	export let initialConnection: Record<string, any> | null = null;
	export let initialAllowDataModifications: boolean = false;
	/** When true, sensitive fields start masked and are only sent if dirty. */
	export let isEditing: boolean = false;
	export let saving: boolean = false;
	/** Stored DbSphere id (edit mode). Lets the backend resolve masked
	 * credentials when testing a connection without retyping them. */
	export let dbsphereId: string | null = null;

	const PASSWORD_MASK = '**********';

	// Field schemas per DB type. Keys mirror `DBConfig` on the backend
	// (backend/extension_modules/dbsphere/dbsphere_state.py) so the payload
	// flows straight into the existing `from_dbsphere_data()` factory without
	// transformation. Required/optional reflects what each runner in
	// `sql_runners/` actually reads.
	const FIELD_SCHEMAS: Record<string, FieldDef[]> = {
		PostgreSQL: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true, placeholder: 'localhost' },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 5432 },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true, placeholder: 'Database Name' },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true, placeholder: 'User Name' },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'public' }
		],
		MySQL: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true, placeholder: 'localhost' },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 3306 },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true }
		],
		MSSQL: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true, placeholder: 'localhost' },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 1433 },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'dbo' }
		],
		Oracle: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 1521 },
			{ key: 'service_name', labelKey: 'Service Name', type: 'text', placeholder: 'ORCLPDB1' },
			{ key: 'database', labelKey: 'SID', type: 'text', placeholder: '(or use Service Name)' },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{
				key: 'schema_name',
				labelKey: 'Schema (Owner)',
				type: 'text',
				placeholder: 'e.g. INSPUSER (defaults to username)'
			}
		],
		SQLite: [
			{ key: 'database', labelKey: 'Database File', type: 'text', required: true, placeholder: '/path/to/database.sqlite' }
		],
		Snowflake: [
			{ key: 'account', labelKey: 'Account', type: 'text', required: true, placeholder: 'xy12345.us-east-1' },
			{ key: 'warehouse', labelKey: 'Warehouse', type: 'text', required: true, placeholder: 'COMPUTE_WH' },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'PUBLIC' },
			{ key: 'role', labelKey: 'Role', type: 'text', placeholder: 'SYSADMIN' }
		],
		Databricks: [
			{ key: 'host', labelKey: 'Server Hostname', type: 'text', required: true, placeholder: 'adb-xxx.azuredatabricks.net' },
			{ key: 'http_path', labelKey: 'HTTP Path', type: 'text', required: true, placeholder: '/sql/1.0/warehouses/xxxxxxxxxxxxxxxx' },
			{ key: 'access_token', labelKey: 'Access Token', type: 'password', required: true, sensitive: true },
			{ key: 'catalog', labelKey: 'Catalog', type: 'text', placeholder: 'main' },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'default' }
		],
		Synapse: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true, placeholder: 'workspace.sql.azuresynapse.net' },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 1433 },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'dbo' }
		],
		Fabric: [
			{ key: 'host', labelKey: 'Host', type: 'text', required: true, placeholder: 'xyz.datawarehouse.fabric.microsoft.com' },
			{ key: 'port', labelKey: 'Port', type: 'number', required: true, defaultValue: 1433 },
			{ key: 'database', labelKey: 'Database', type: 'text', required: true },
			{ key: 'username', labelKey: 'Username', type: 'text', required: true },
			{ key: 'password', labelKey: 'Password', type: 'password', required: true, sensitive: true },
			{ key: 'schema_name', labelKey: 'Schema', type: 'text', placeholder: 'dbo' }
		],
		BigQuery: [
			{ key: 'project_id', labelKey: 'Project ID', type: 'text', required: true, placeholder: 'my-gcp-project' },
			{ key: 'dataset_id', labelKey: 'Dataset', type: 'text', required: true, placeholder: 'my_dataset' },
			{
				key: 'credentials_json',
				labelKey: 'Service Account JSON',
				type: 'service-account-json',
				required: true,
				sensitive: true,
				placeholder: '{"type": "service_account", "project_id": "...", ...}'
			}
		]
	};

	// Falls back to all known schema keys so unknown types from server config still appear.
	$: dbTypes = (($config as unknown as { dbsphere?: { types?: string[] } } | null)?.dbsphere
		?.types ?? Object.keys(FIELD_SCHEMAS)) as string[];

	// Stored db_type values vary across history: backend lowercases via
	// `DBConfig.from_dbsphere_data` (e.g. "postgresql"), older UIs may have
	// written "postgres" / "Postgres" / "PostgreSQL". Normalize back to the
	// canonical FIELD_SCHEMAS key so both the Selector and the schema lookup hit.
	const DB_TYPE_ALIASES: Record<string, string> = {
		postgres: 'PostgreSQL',
		postgresql: 'PostgreSQL'
	};
	const canonicalDbType = (raw: string): string => {
		if (!raw) return '';
		if (FIELD_SCHEMAS[raw]) return raw;
		const lowered = raw.toLowerCase();
		for (const key of Object.keys(FIELD_SCHEMAS)) {
			if (key.toLowerCase() === lowered) return key;
		}
		return DB_TYPE_ALIASES[lowered] ?? raw;
	};

	let dbType = '';
	let values: Record<string, string> = {};
	let dirtyKeys: Set<string> = new Set();
	let allowDataModifications = false;

	// Service-account-json field local state (BigQuery)
	let saFileInput: HTMLInputElement | null = null;
	let saExpanded = false;

	// BigQuery ADC toggle. When on, the Service Account JSON field is hidden,
	// not required, and never sent — auth defers to ADC on the backend.
	let bigQueryAdc = false;
	// A function, not a `$:` reactive — the reactive binding drifts from dbType on
	// modal remount (see lookupSchema note), which left use_adc out of the save
	// payload and hid the toggle when reopening an existing connection. A function
	// re-reads dbType on every call/render.
	const isBigQueryType = () => canonicalDbType(dbType) === 'BigQuery';

	// Schema actually shown/validated: drop credentials_json when ADC is on.
	// `adc` is taken as a param (not closed over) so the template `{#each}` lists
	// it as a direct dependency and re-runs when the toggle flips — otherwise the
	// Service Account field would not reappear after turning ADC off.
	const effectiveSchema = (t: string, adc: boolean): FieldDef[] => {
		const fields = lookupSchema(t);
		if (canonicalDbType(t) === 'BigQuery' && adc) {
			return fields.filter((f) => f.key !== 'credentials_json');
		}
		return fields;
	};

	const handleAdcToggle = (e: CustomEvent<boolean>) => {
		bigQueryAdc = e.detail;
		if (bigQueryAdc) {
			// Wipe any pasted/masked SA key so it can't leak into the payload.
			const { credentials_json, ...rest } = values;
			values = rest;
			dirtyKeys.delete('credentials_json');
			dirtyKeys = dirtyKeys;
			saExpanded = false;
		}
	};

	// Connection test — exercises the in-progress values against the backend
	// (/dbsphere/test-connection). State is local and does NOT touch the
	// parent's connectionVerified gate.
	let testing = false;
	let testResult: {
		success: boolean;
		message?: string;
		tables?: { name: string }[];
		tableMessage?: string;
	} | null = null;

	// Like handleSave's payload loop but INCLUDES masked sensitive fields, so the
	// backend can resolve them from the stored record via dbsphere_id (edit mode).
	const buildTestForm = (): ConnectionTestForm => {
		const form = {
			db_type: dbType,
			host: '',
			port: 0,
			database: '',
			username: '',
			password: ''
		} as ConnectionTestForm;
		const sink = form as Record<string, unknown>;
		for (const f of effectiveSchema(dbType, bigQueryAdc)) {
			const raw = values[f.key];
			if (raw === undefined || raw === '') continue;
			if (f.type === 'number') {
				const n = Number(raw);
				if (Number.isFinite(n)) sink[f.key] = n;
			} else {
				sink[f.key] = raw;
			}
		}
		if (isBigQueryType()) form.use_adc = bigQueryAdc;
		if (dbsphereId) form.dbsphere_id = dbsphereId;
		return form;
	};

	const handleTestConnection = async () => {
		if (!dbType) {
			toast.error($i18n.t('Please select a database type.'));
			return;
		}
		const missing = effectiveSchema(dbType, bigQueryAdc).filter(
			(f) =>
				f.required &&
				!values[f.key] &&
				!(f.sensitive && isEditing && !dirtyKeys.has(f.key))
		);
		if (missing.length > 0) {
			toast.error($i18n.t('Please fill in all required fields.'));
			return;
		}

		testing = true;
		testResult = null;
		try {
			const res = await testDbConnection(localStorage.token, buildTestForm());
			if (res?.success) {
				// Connectivity is OK — also pull the schema (tables) so the user
				// can see it right here, like the detail page does on test.
				let tables: { name: string }[] = [];
				let tableMessage = '';
				try {
					const t = await getDbTables(localStorage.token, buildTestForm());
					tables = t?.tables ?? [];
					tableMessage = t?.message ?? '';
				} catch (e) {
					tableMessage = `${e}`;
				}
				testResult = { success: true, tables, tableMessage };
				toast.success($i18n.t('Connection successful!'));
			} else {
				testResult = res;
				if (res?.message) toast.error(res.message);
			}
		} catch (e) {
			testResult = { success: false, message: `${e}` };
			toast.error(`${e}`);
		} finally {
			testing = false;
		}
	};

	function lookupSchema(t: string): FieldDef[] {
		return FIELD_SCHEMAS[t] ?? FIELD_SCHEMAS[canonicalDbType(t)] ?? [];
	}

	// Re-seed form whenever the modal is opened with (possibly new) initial data.
	$: if (show) {
		seedForm();
	}

	// Belt-and-suspenders: the parent uses Modal `{#if show}` so the modal body
	// remounts every open. The `$:` block fires on remount, but in some HMR /
	// reactive-sweep orderings the first render commits before seedForm() flips
	// dbType — leaving the form blank until the user toggles DB type. Calling
	// once here on mount guarantees dbType is set before first paint.
	onMount(() => {
		if (show) seedForm();
	});

	const seedForm = () => {
		dbType = canonicalDbType(initialConnection?.db_type ?? '');
		dirtyKeys = new Set();
		allowDataModifications = initialAllowDataModifications;
		saExpanded = false;
		bigQueryAdc = Boolean(initialConnection?.use_adc);
		testResult = null;

		const conn = initialConnection ?? {};
		// Hydrate every known field across all schemas so DB-type switching
		// preserves previously-entered values. Sensitive fields show mask
		// placeholder in edit mode. Build into a local object then assign once —
		// Svelte does not pick up `values[key] = ...` index-assignment as a
		// reactive write, which was hiding existing connection values on first
		// open (user only saw them after toggling DB type and back).
		const next: Record<string, string> = {};
		const seenKeys = new Set<string>();
		for (const fields of Object.values(FIELD_SCHEMAS)) {
			for (const f of fields) {
				if (seenKeys.has(f.key)) continue;
				seenKeys.add(f.key);
				const raw = conn[f.key];
				if (raw === undefined || raw === null) continue;
				if (f.sensitive && isEditing) {
					next[f.key] = PASSWORD_MASK;
				} else {
					next[f.key] = String(raw);
				}
			}
		}
		values = next;
	};

	const handleDbTypeChange = (e: CustomEvent<{ value: string | number }>) => {
		dbType = String(e.detail.value);
		testResult = null;
		// Reset port to the vendor default when switching DB types — the previous
		// port belongs to a different vendor and is almost always wrong.
		const portField = FIELD_SCHEMAS[dbType]?.find((f) => f.key === 'port');
		if (portField?.defaultValue !== undefined) {
			values = { ...values, port: String(portField.defaultValue) };
		}
	};

	const setValue = (key: string, v: string, opts?: { sensitive?: boolean }) => {
		values = { ...values, [key]: v };
		if (opts?.sensitive) {
			dirtyKeys.add(key);
			dirtyKeys = dirtyKeys;
		}
	};

	// Input/Textarea dispatch a CustomEvent that wraps the native DOM event in
	// `detail`, whereas SensitiveInput forwards the native InputEvent directly.
	// Normalize both shapes so we always read the current value off `target`.
	//
	// For sensitive fields in edit mode we additionally strip the leading
	// PASSWORD_MASK prefix on the first keystroke so the user's input never
	// concatenates with the mask placeholder (which would otherwise send a
	// string like "**********X" to the backend as the new credential).
	const handleInputEvent = (
		key: string,
		sensitive: boolean | undefined,
		event: Event | CustomEvent<Event>
	) => {
		const native: Event =
			'detail' in event && event.detail instanceof Event ? event.detail : (event as Event);
		const target = native.target as HTMLInputElement | HTMLTextAreaElement | null;
		let next = target?.value ?? '';
		if (sensitive && isEditing && !dirtyKeys.has(key) && next.startsWith(PASSWORD_MASK)) {
			next = next.slice(PASSWORD_MASK.length);
			// Reflect the stripped value back into the input so cursor + display
			// stay in sync with the value we'll actually save.
			if (target) target.value = next;
		}
		setValue(key, next, { sensitive });
	};

	const close = () => {
		show = false;
		dispatch('close');
	};

	const handleCancel = () => {
		close();
	};

	const handleSave = () => {
		if (!dbType) {
			toast.error($i18n.t('Database Type is required'));
			return;
		}

		// Required-field validation. In edit mode, a sensitive field that still
		// holds the mask is treated as satisfied — the server keeps the
		// previously-stored value when no fresh ciphertext is sent.
		const fields = effectiveSchema(dbType, bigQueryAdc);
		const missing = fields.filter(
			(f) =>
				f.required &&
				!values[f.key] &&
				!(f.sensitive && isEditing && !dirtyKeys.has(f.key))
		);
		if (missing.length > 0) {
			toast.error($i18n.t('Please fill in all required fields.'));
			return;
		}

		const payload: Record<string, unknown> = {
			db_type: dbType,
			allow_data_modifications: allowDataModifications
		};
		if (isBigQueryType()) {
			payload.use_adc = bigQueryAdc;
		}
		for (const f of fields) {
			const raw = values[f.key];
			if (raw === undefined || raw === '') continue;
			// P-H1: skip sensitive fields the user did not edit so the
			// server-side resolve_connection_password() keeps the original.
			if (f.sensitive && isEditing && !dirtyKeys.has(f.key)) continue;
			if (f.type === 'number') {
				const n = Number(raw);
				if (Number.isFinite(n)) payload[f.key] = n;
			} else {
				payload[f.key] = raw;
			}
		}

		dispatch('save', payload);
	};

	const handleAllowToggle = (e: CustomEvent<boolean>) => {
		allowDataModifications = e.detail;
	};

	const handleServiceAccountFileChange = async (key: string, e: Event) => {
		const target = e.target as HTMLInputElement;
		const file = target.files?.[0];
		if (!file) return;
		try {
			const text = await file.text();
			JSON.parse(text);
			setValue(key, text, { sensitive: true });
		} catch {
			toast.error($i18n.t('Invalid JSON file'));
		} finally {
			// Reset so selecting the same file again still fires onchange.
			target.value = '';
		}
	};

	// Pull identifying fields out of a Google service-account JSON so the user
	// can verify which account is loaded without seeing private_key etc.
	const parseServiceAccountSummary = (json: string): string | null => {
		if (!json || json === PASSWORD_MASK) return null;
		try {
			const obj = JSON.parse(json) as { client_email?: string; project_id?: string };
			const email = obj.client_email;
			const project = obj.project_id;
			if (email && project) return `${email} · ${project}`;
			return email ?? project ?? null;
		} catch {
			return null;
		}
	};

	$: serviceAccountSummary = parseServiceAccountSummary(values['credentials_json'] ?? '');
	$: serviceAccountUsingSaved = (values['credentials_json'] ?? '') === PASSWORD_MASK;
</script>

<!-- Figma 1296:13037 — modal width 600px. Use md (672px) + max-w cap. -->
<Modal bind:show size="md" className="bg-white dark:bg-gray-900 rounded-xl max-w-[600px]">
	<div class="cloo-db-configure">
		<!-- Header -->
		<header
			class="flex items-center justify-between px-6 py-3 border-b border-[var(--cloo-border-default)]"
		>
			<h2 class="text-base font-semibold text-[var(--cloo-text-primary)]">
				{$i18n.t('DB Configure')}
			</h2>
			<button
				type="button"
				class="p-1.5 rounded-full hover:bg-[var(--cloo-surface-hover)]"
				aria-label={$i18n.t('Close')}
				on:click={close}
			>
				<svg
					class="size-5"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</header>

		<!-- Body -->
		<div class="px-6 py-4 flex flex-col gap-2 max-h-[70vh] overflow-y-auto">
			<!-- Allow data modifications — Figma 1296:13041 (LabelBase left flex-1 + right Switch) -->
			<LabelBase
				label={$i18n.t('Allow data modifications')}
				caption={$i18n.t(
					'Off: agent can only run SELECT (read-only). On: agent can also run INSERT/UPDATE/DELETE/DDL, but each call requires user approval.'
				)}
				size="md"
			>
				<svelte:fragment slot="right">
					<Switch state={allowDataModifications} on:change={handleAllowToggle} />
				</svelte:fragment>
			</LabelBase>

			<!-- Database Type -->
			<div class="cloo-db-configure__row">
				<div class="cloo-db-configure__label">
					<div class="font-semibold text-sm text-[var(--cloo-text-primary)]">
						{$i18n.t('Database Type')}
						<span class="text-[var(--cloo-text-danger,#c10007)]">*</span>
					</div>
				</div>
				<div class="cloo-db-configure__control">
					<Selector
						value={dbType}
						items={dbTypes.map((t) => ({ value: t, label: t }))}
						size="sm"
						placeholder={$i18n.t('Select Type')}
						portal="body"
						contentClassName="z-[10000]"
						on:change={handleDbTypeChange}
					/>
				</div>
			</div>

			<!-- Dynamic fields per DB type — inline lookup so the template re-reads
			     FIELD_SCHEMAS every render. Reactive bindings were observed to
			     drift from dbType across modal remounts (form rendered blank on
			     second Configure click), so handleSave() also calls effectiveSchema()
			     directly rather than reading a cached reactive value. bigQueryAdc is
			     passed so the list re-runs when the ADC toggle flips. -->
			{#each effectiveSchema(dbType, bigQueryAdc) as field (field.key)}
				<div class="cloo-db-configure__row">
					<div class="cloo-db-configure__label">
						<div class="font-semibold text-sm text-[var(--cloo-text-primary)]">
							{$i18n.t(field.labelKey)}
							{#if field.required}
								<span class="text-[var(--cloo-text-danger,#c10007)]">*</span>
							{/if}
						</div>
					</div>
					<div class="cloo-db-configure__control">
						{#if field.type === 'password'}
							<SensitiveInput
								size="sm"
								placeholder={field.placeholder ?? '**********'}
								value={values[field.key] ?? ''}
								on:input={(e) => handleInputEvent(field.key, true, e)}
							/>
						{:else if field.type === 'service-account-json'}
							<div class="flex flex-col gap-2 w-full min-w-0">
								<div class="flex items-center gap-2 flex-wrap">
									<input
										type="file"
										accept=".json,application/json"
										class="hidden"
										bind:this={saFileInput}
										on:change={(e) => handleServiceAccountFileChange(field.key, e)}
									/>
									<Button
										kind="outlined"
										size="sm"
										on:click={() => saFileInput?.click()}
									>
										{serviceAccountSummary || serviceAccountUsingSaved
											? $i18n.t('Replace JSON file')
											: $i18n.t('Upload JSON file')}
									</Button>
									<button
										type="button"
										class="text-xs underline text-[var(--cloo-text-tertiary)] ml-auto"
										on:click={() => (saExpanded = !saExpanded)}
									>
										{saExpanded ? $i18n.t('Hide') : $i18n.t('Paste manually')}
									</button>
								</div>
								{#if serviceAccountSummary}
									<div
										class="text-xs text-[var(--cloo-color-success)] truncate min-w-0"
										title={serviceAccountSummary}
									>
										✓ {serviceAccountSummary}
									</div>
								{:else if serviceAccountUsingSaved}
									<div class="text-xs text-[var(--cloo-text-tertiary)]">
										{$i18n.t('Using saved credentials')}
									</div>
								{/if}
								{#if saExpanded}
									<Textarea
										size="sm"
										rows={4}
										autoResize={false}
										placeholder={field.placeholder ?? ''}
										value={values[field.key] ?? ''}
										className="max-h-[140px] overflow-auto"
										on:input={(e) => handleInputEvent(field.key, true, e)}
									/>
								{/if}
							</div>
						{:else if field.type === 'json-textarea'}
							<Textarea
								size="sm"
								rows={6}
								placeholder={field.placeholder ?? ''}
								value={values[field.key] ?? ''}
								on:input={(e) => handleInputEvent(field.key, field.sensitive, e)}
							/>
						{:else}
							<Input
								size="sm"
								type={field.type === 'number' ? 'number' : 'text'}
								placeholder={field.placeholder ?? ''}
								value={values[field.key] ?? ''}
								on:input={(e) => handleInputEvent(field.key, field.sensitive, e)}
							/>
						{/if}
					</div>
				</div>

				<!-- BigQuery: ADC toggle, placed right below the Dataset field.
				     isBigQueryType() is a function (not a reactive) so it re-reads
				     dbType every render — a reactive binding drifts on modal remount
				     and left the toggle hidden when opening an existing connection. -->
				{#if field.key === 'dataset_id' && isBigQueryType()}
					<LabelBase
						label={$i18n.t('Use Application Default Credentials (ADC)')}
						caption={$i18n.t(
							'On: authenticate via the GCP runtime (workload identity / GOOGLE_APPLICATION_CREDENTIALS / gcloud ADC) instead of a Service Account key. Project ID is still required.'
						)}
						size="md"
					>
						<svelte:fragment slot="right">
							<Switch state={bigQueryAdc} on:change={handleAdcToggle} />
						</svelte:fragment>
					</LabelBase>
				{/if}
			{/each}

			{#if dbType && lookupSchema(dbType).length === 0}
				<div class="text-xs text-[var(--cloo-text-tertiary)] px-3 py-2">
					{$i18n.t('No configuration fields defined for this database type.')}
				</div>
			{/if}

			<!-- Info banner — encourage minimum-privilege DB users (H3) -->
			<div
				class="text-xs text-[var(--cloo-text-tertiary)] mt-2 px-3 py-2 rounded bg-[var(--cloo-bg-neutral-hovered,transparent)] border border-[var(--cloo-border-subtle)]"
			>
				{$i18n.t('Recommended: use a dedicated DB user with minimum privileges.')}
			</div>

			<!-- Connection test result -->
			{#if testResult}
				<div
					class="text-xs mt-1 px-3 py-2 rounded border {testResult.success
						? 'text-[var(--cloo-color-success)] border-[var(--cloo-color-success)]'
						: 'text-[var(--cloo-text-danger,#c10007)] border-[var(--cloo-border-subtle)]'}"
				>
					{#if testResult.success}
						<div>
							✓ {$i18n.t('Connection successful!')}
							{#if testResult.tables}
								({testResult.tables.length})
							{/if}
						</div>
						{#if testResult.tables && testResult.tables.length > 0}
							<div
								class="mt-1 text-[var(--cloo-text-tertiary)] max-h-[80px] overflow-auto break-all"
							>
								{testResult.tables.map((t) => t.name).join(', ')}
							</div>
						{:else if testResult.tableMessage}
							<div class="mt-1 text-[var(--cloo-text-tertiary)]">
								{testResult.tableMessage}
							</div>
						{/if}
					{:else}
						{testResult.message ?? ''}
					{/if}
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<footer
			class="flex items-center justify-between gap-2 px-6 py-3 border-t border-[var(--cloo-border-default)]"
		>
			<Button
				kind="outlined"
				size="md"
				loading={testing}
				disabled={saving || testing}
				on:click={handleTestConnection}
			>
				{$i18n.t('Test Connection')}
			</Button>
			<div class="flex items-center gap-2">
				<Button kind="outlined" size="md" on:click={handleCancel}>
					{$i18n.t('Cancel')}
				</Button>
				<Button kind="filled" size="md" loading={saving} disabled={saving} on:click={handleSave}>
					{isEditing ? $i18n.t('Save & Update') : $i18n.t('Save')}
				</Button>
			</div>
		</footer>
	</div>
</Modal>

<style>
	.cloo-db-configure__row {
		display: flex;
		align-items: flex-start;
		gap: var(--cloo-space-2);
		min-height: 36px;
	}

	.cloo-db-configure__label {
		flex: 0 0 190px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-top: 6px;
	}

	.cloo-db-configure__control {
		flex: 1 1 0;
		min-width: 0;
		display: flex;
		align-items: center;
	}

	.cloo-db-configure__control :global(.cloo-input),
	.cloo-db-configure__control :global(.cloo-textarea),
	.cloo-db-configure__control :global(.cloo-selector) {
		width: 100%;
	}
</style>
