<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Readable } from 'svelte/store';
	import Checkbox from '$lib/components/common/Checkbox.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import RadioGroup from '$lib/components/common/RadioGroup.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	type I18nStore = Readable<{
		t: (key: string) => string;
	}>;

	const i18n = getContext<I18nStore>('i18n');

	export let responseFormat: {
		type: 'text' | 'json_schema';
		json_schema?: {
			name: string;
			description?: string;
			schema: object;
			strict?: boolean;
		};
	} = {
		type: 'text'
	};

	let formatType: 'text' | 'json_schema' = 'text';
	let schemaName = '';
	let schemaDescription = '';
	let strictMode = true;
	let initialized = false;

	// Input mode: visual (field builder) or json (raw JSON)
	let inputMode: 'visual' | 'json' = 'visual';
	let rawJsonSchema = '';
	let jsonError = '';

	// Field builder
	interface SchemaField {
		name: string;
		type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object';
		description: string;
		required: boolean;
		arrayItemType?: 'string' | 'number' | 'integer' | 'boolean' | 'object';
		enumValues?: string;
		objectSchema?: string; // JSON string for nested object schema
	}

	let fields: SchemaField[] = [];

	function getErrorMessage(error: unknown): string {
		return error instanceof Error ? error.message : String(error);
	}

	const fieldTypes = [
		{ value: 'string', label: 'String' },
		{ value: 'number', label: 'Number' },
		{ value: 'integer', label: 'Integer' },
		{ value: 'boolean', label: 'Boolean' },
		{ value: 'array', label: 'Array' },
		{ value: 'object', label: 'Object' }
	];

	// Initialize from prop on mount
	onMount(() => {
		if (responseFormat) {
			formatType = responseFormat.type ?? 'text';
			if (responseFormat.json_schema) {
				schemaName = responseFormat.json_schema.name ?? '';
				schemaDescription = responseFormat.json_schema.description ?? '';
				strictMode = responseFormat.json_schema.strict ?? true;
				if (responseFormat.json_schema.schema) {
					fields = parseSchemaToFields(responseFormat.json_schema.schema);
					rawJsonSchema = JSON.stringify(responseFormat.json_schema.schema, null, 2);
				}
			}
		}
		initialized = true;
	});

	// Parse JSON schema to field list
	function parseSchemaToFields(schema: any): SchemaField[] {
		const result: SchemaField[] = [];
		if (schema.properties) {
			const requiredFields = schema.required || [];
			for (const [name, prop] of Object.entries(schema.properties) as [string, any][]) {
				const field: SchemaField = {
					name,
					type: prop.type || 'string',
					description: prop.description || '',
					required: requiredFields.includes(name)
				};
				if (prop.type === 'array' && prop.items) {
					field.arrayItemType = prop.items.type || 'string';
					if (prop.items.type === 'object' && prop.items.properties) {
						field.objectSchema = JSON.stringify(prop.items, null, 2);
					}
				}
				if (prop.type === 'object' && prop.properties) {
					field.objectSchema = JSON.stringify(prop, null, 2);
				}
				if (prop.enum) {
					field.enumValues = prop.enum.join(', ');
				}
				result.push(field);
			}
		}
		return result;
	}

	// Build JSON schema from fields
	function buildSchemaFromFields(): object {
		const properties: Record<string, any> = {};
		const required: string[] = [];

		for (const field of fields) {
			if (!field.name.trim()) continue;

			let prop: any = {};

			if (field.enumValues?.trim()) {
				prop.type = 'string';
				prop.enum = field.enumValues.split(',').map((v) => v.trim()).filter((v) => v);
			} else if (field.type === 'array') {
				prop.type = 'array';
				if (field.arrayItemType === 'object' && field.objectSchema?.trim()) {
					try {
						prop.items = JSON.parse(field.objectSchema);
					} catch {
						prop.items = { type: 'object' };
					}
				} else {
					prop.items = { type: field.arrayItemType || 'string' };
				}
			} else if (field.type === 'object') {
				if (field.objectSchema?.trim()) {
					try {
						prop = JSON.parse(field.objectSchema);
					} catch {
						prop = { type: 'object' };
					}
				} else {
					prop.type = 'object';
				}
			} else {
				prop.type = field.type;
			}

			if (field.description.trim() && !prop.description) {
				prop.description = field.description.trim();
			}

			properties[field.name.trim()] = prop;

			if (field.required) {
				required.push(field.name.trim());
			}
		}

		return {
			type: 'object',
			properties,
			required,
			additionalProperties: false
		};
	}

	// Add new field
	function addField() {
		fields = [
			...fields,
			{
				name: '',
				type: 'string',
				description: '',
				required: false
			}
		];
	}

	// Remove field
	function removeField(index: number) {
		fields = fields.filter((_, i) => i !== index);
	}

	// Move field up/down
	function moveField(index: number, direction: 'up' | 'down') {
		const newIndex = direction === 'up' ? index - 1 : index + 1;
		if (newIndex < 0 || newIndex >= fields.length) return;
		const newFields = [...fields];
		[newFields[index], newFields[newIndex]] = [newFields[newIndex], newFields[index]];
		fields = newFields;
	}

	// Sync fields to JSON when switching modes
	function syncFieldsToJson() {
		if (fields.length > 0) {
			const schema = buildSchemaFromFields();
			rawJsonSchema = JSON.stringify(schema, null, 2);
			jsonError = '';
		}
	}

	// Sync JSON to fields when switching modes
	function syncJsonToFields() {
		if (rawJsonSchema.trim()) {
			try {
				const schema = JSON.parse(rawJsonSchema);
				fields = parseSchemaToFields(schema);
				jsonError = '';
			} catch (e) {
				jsonError = getErrorMessage(e);
			}
		}
	}

	// Handle mode switch
	function switchToMode(mode: 'visual' | 'json') {
		if (mode === 'json' && inputMode === 'visual') {
			syncFieldsToJson();
		} else if (mode === 'visual' && inputMode === 'json') {
			syncJsonToFields();
		}
		inputMode = mode;
	}

	// Format JSON
	function formatJson() {
		try {
			const parsed = JSON.parse(rawJsonSchema);
			rawJsonSchema = JSON.stringify(parsed, null, 2);
			jsonError = '';
		} catch (e) {
			jsonError = getErrorMessage(e);
		}
	}

	// Validate JSON schema
	function validateJsonSchema(): boolean {
		if (!rawJsonSchema.trim()) return false;
		try {
			JSON.parse(rawJsonSchema);
			jsonError = '';
			return true;
		} catch (e) {
			jsonError = getErrorMessage(e);
			return false;
		}
	}

	// Sync back to parent (only after initialized)
	$: if (initialized) {
		if (formatType === 'text') {
			responseFormat = { type: 'text' };
		} else if (formatType === 'json_schema' && schemaName) {
			let schema: object | null = null;

			if (inputMode === 'visual' && fields.length > 0) {
				schema = buildSchemaFromFields();
			} else if (inputMode === 'json' && rawJsonSchema.trim()) {
				try {
					schema = JSON.parse(rawJsonSchema);
					jsonError = '';
				} catch (e) {
					jsonError = getErrorMessage(e);
				}
			}

			if (schema) {
				responseFormat = {
					type: 'json_schema',
					json_schema: {
						name: schemaName,
						...(schemaDescription && { description: schemaDescription }),
						schema,
						strict: strictMode
					}
				};
			}
		}
	}

	// Add example fields
	function insertExample() {
		schemaName = 'analysis_result';
		schemaDescription = 'Structured analysis response';
		if (inputMode === 'visual') {
			fields = [
				{ name: 'summary', type: 'string', description: 'A brief summary', required: true },
				{ name: 'key_points', type: 'array', description: 'List of key points', required: true, arrayItemType: 'string' },
				{ name: 'sentiment', type: 'string', description: 'Overall sentiment', required: false, enumValues: 'positive, negative, neutral' },
				{ name: 'metadata', type: 'object', description: 'Additional metadata', required: false, objectSchema: '{\n  "type": "object",\n  "properties": {\n    "source": { "type": "string" },\n    "confidence": { "type": "number" }\n  }\n}' }
			];
		} else {
			rawJsonSchema = JSON.stringify({
				type: 'object',
				properties: {
					summary: { type: 'string', description: 'A brief summary' },
					key_points: { type: 'array', items: { type: 'string' }, description: 'List of key points' },
					sentiment: { type: 'string', enum: ['positive', 'negative', 'neutral'], description: 'Overall sentiment' },
					metadata: {
						type: 'object',
						properties: {
							source: { type: 'string' },
							confidence: { type: 'number' }
						}
					}
				},
				required: ['summary', 'key_points'],
				additionalProperties: false
			}, null, 2);
		}
	}

	// Check if schema is valid
	$: isSchemaValid = inputMode === 'visual'
		? (schemaName && fields.length > 0 && fields.every(f => f.name.trim()))
		: (schemaName && rawJsonSchema.trim() && !jsonError);
	$: formatOptions = [
		{ label: $i18n.t('Chat'), value: 'text' },
		{ label: $i18n.t('Structured Output'), value: 'json_schema' }
	];
</script>

<div class="response-format">
	<div class="response-format__header">
		<div class="response-format__heading">
			<h3>{$i18n.t('Response Format')}</h3>
			<p>{$i18n.t('Configure how the model should format its responses.')}</p>
		</div>

		<div class="response-format__selector">
			<RadioGroup
				value={formatType}
				options={formatOptions}
				orientation="horizontal"
				ariaLabel={$i18n.t('Response Format')}
				on:change={(event) => {
					formatType = event.detail.value === 'json_schema' ? 'json_schema' : 'text';
				}}
			/>
		</div>
	</div>

	{#if formatType === 'json_schema'}
		<div class="response-format__panel">
			<!-- Schema Name & Description -->
			<div class="response-format__grid">
				<Input
					bind:value={schemaName}
					label={$i18n.t('Schema Name')}
					placeholder="e.g., analysis_result"
					size="md"
				/>
				<Input
					bind:value={schemaDescription}
					label={`${$i18n.t('Description')} (${$i18n.t('optional')})`}
					placeholder={$i18n.t('Brief description')}
					size="md"
				/>
			</div>

			<!-- Input Mode Toggle -->
			<div class="response-format__toolbar">
				<div class="response-format__mode-switch">
					<button
						type="button"
						class={`response-format__mode-button ${inputMode === 'visual' ? 'is-active' : ''}`.trim()}
						on:click={() => switchToMode('visual')}
					>
						{$i18n.t('Visual')}
					</button>
					<button
						type="button"
						class={`response-format__mode-button ${inputMode === 'json' ? 'is-active' : ''}`.trim()}
						on:click={() => switchToMode('json')}
					>
						JSON
					</button>
				</div>
				<button
					type="button"
					class="response-format__secondary-button"
					on:click={insertExample}
				>
					{$i18n.t('Insert Example')}
				</button>
			</div>

			{#if inputMode === 'visual'}
				<!-- Visual Field Builder -->
				<div>
					<div class="response-format__subheader">
						<div class="response-format__subheader-label">{$i18n.t('Fields')}</div>
						<button
							type="button"
							class="response-format__add-button"
							on:click={addField}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
								<path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
							</svg>
							{$i18n.t('Add Field')}
						</button>
					</div>

					{#if fields.length === 0}
						<div class="response-format__empty-state">
							{$i18n.t('No fields defined. Click "Add Field" to get started.')}
						</div>
					{:else}
						<div class="response-format__fields">
							{#each fields as field, index}
								<div class="response-format__field-row">
									<!-- Field Name & Description -->
									<div class="flex-1 min-w-0">
										<input
											type="text"
											bind:value={field.name}
											placeholder={$i18n.t('Field name')}
											class="response-format__field-input"
										/>
										<input
											type="text"
											bind:value={field.description}
											placeholder={$i18n.t('Description (optional)')}
											class="response-format__field-caption"
										/>
									</div>

									<!-- Field Type -->
									<div class="w-24 shrink-0">
										<select
											bind:value={field.type}
											class="response-format__mini-select"
										>
											{#each fieldTypes as ft}
												<option value={ft.value}>{ft.label}</option>
											{/each}
										</select>
										{#if field.type === 'array'}
											<select
												bind:value={field.arrayItemType}
												class="response-format__mini-select mt-1"
											>
												<option value="string">String[]</option>
												<option value="number">Number[]</option>
												<option value="integer">Integer[]</option>
												<option value="boolean">Boolean[]</option>
												<option value="object">Object[]</option>
											</select>
										{/if}
									</div>

									<!-- Enum Values (for string type) -->
									{#if field.type === 'string'}
										<div class="w-24 shrink-0">
											<input
												type="text"
												bind:value={field.enumValues}
												placeholder={$i18n.t('Enum')}
												class="response-format__mini-select"
											/>
											<div class="response-format__micro-copy">{$i18n.t('comma separated')}</div>
										</div>
									{/if}

									<!-- Object Schema (for object type or array of objects) -->
									{#if field.type === 'object' || (field.type === 'array' && field.arrayItemType === 'object')}
										<div class="w-32 shrink-0">
											<textarea
												bind:value={field.objectSchema}
												placeholder={$i18n.t('Object JSON')}
												rows="2"
												class="response-format__object-json"
											></textarea>
										</div>
									{/if}

								<div class="shrink-0 flex flex-col items-center">
									<div title={$i18n.t('Required')}>
										<Checkbox
											state={field.required ? 'checked' : 'unchecked'}
											on:change={(e) => { field.required = e.detail === 'checked'; }}
										/>
									</div>
									<span class="response-format__micro-copy">{$i18n.t('Req')}</span>
								</div>

									<!-- Actions -->
									<div class="response-format__field-actions">
										<button
											type="button"
											class="response-format__action-button"
											on:click={() => moveField(index, 'up')}
											disabled={index === 0}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
												<path fill-rule="evenodd" d="M14.77 12.79a.75.75 0 01-1.06-.02L10 8.832 6.29 12.77a.75.75 0 11-1.08-1.04l4.25-4.5a.75.75 0 011.08 0l4.25 4.5a.75.75 0 01-.02 1.06z" clip-rule="evenodd" />
											</svg>
										</button>
										<button
											type="button"
											class="response-format__action-button"
											on:click={() => moveField(index, 'down')}
											disabled={index === fields.length - 1}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
												<path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd" />
											</svg>
										</button>
										<button
											type="button"
											class="response-format__action-button is-danger"
											on:click={() => removeField(index)}
										>
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
												<path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
											</svg>
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{:else}
				<!-- JSON Input Mode -->
				<div>
					<div class="response-format__subheader">
						<div class="response-format__subheader-label">{$i18n.t('JSON Schema')}</div>
						<button
							type="button"
							class="response-format__secondary-button"
							on:click={formatJson}
						>
							{$i18n.t('Format')}
						</button>
					</div>
					<textarea
						bind:value={rawJsonSchema}
						on:input={() => validateJsonSchema()}
						placeholder={`{
  "type": "object",
  "properties": {
    "field_name": { "type": "string" }
  },
  "required": ["field_name"],
  "additionalProperties": false
}`}
						rows="10"
						class={`response-format__json-input ${jsonError ? 'is-error' : ''}`.trim()}
					></textarea>
					{#if jsonError}
						<p class="response-format__error-text">{$i18n.t('JSON Error')}: {jsonError}</p>
					{/if}
				</div>
			{/if}

			<!-- Strict Mode -->
			<div class="response-format__strict-row">
				<div>
					<div class="response-format__subheader-label">{$i18n.t('Strict Mode')}</div>
					<p class="response-format__micro-copy">
						{$i18n.t('Enforce exact schema compliance')}
					</p>
				</div>
				<Switch state={strictMode} ariaLabel={$i18n.t('Strict Mode')} on:change={(event) => {
					strictMode = event.detail;
				}} />
			</div>

			<!-- Validation Status -->
			{#if !schemaName}
				<div class="response-format__notice">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('Please enter a schema name')}</span>
				</div>
			{:else if inputMode === 'visual' && fields.length === 0}
				<div class="response-format__notice">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('Please add at least one field')}</span>
				</div>
			{:else if inputMode === 'visual' && fields.some(f => !f.name.trim())}
				<div class="response-format__notice">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('All fields must have a name')}</span>
				</div>
			{:else if inputMode === 'json' && !rawJsonSchema.trim()}
				<div class="response-format__notice">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('Please enter a JSON schema')}</span>
				</div>
			{:else if inputMode === 'json' && jsonError}
				<div class="response-format__notice is-danger">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('Invalid JSON schema')}</span>
				</div>
			{:else if isSchemaValid}
				<div class="response-format__notice is-success">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 shrink-0">
						<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd" />
					</svg>
					<span>{$i18n.t('Schema is valid')} {#if inputMode === 'visual'}({fields.length} {$i18n.t('fields')}){/if}</span>
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.response-format {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.response-format__header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.response-format__heading {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.response-format__heading h3 {
		margin: 0;
		font-size: 1rem;
		line-height: 1.5rem;
		font-weight: 600;
		color: var(--cloo-text-primary);
	}

	.response-format__heading p {
		margin: 0;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	.response-format__panel {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 1.5rem;
		border: 1px solid var(--cloo-border-default);
		border-radius: 0.75rem;
		background: var(--cloo-bg-surface);
	}

	.response-format__grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.75rem;
	}

	.response-format__toolbar,
	.response-format__subheader,
	.response-format__strict-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.response-format__mode-switch {
		display: inline-flex;
		gap: 0.25rem;
		padding: 0.125rem;
		border-radius: 0.5rem;
		background: var(--cloo-bg-default);
	}

	.response-format__mode-button,
	.response-format__secondary-button,
	.response-format__add-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.375rem;
		min-height: 2rem;
		padding: 0.375rem 0.75rem;
		border-radius: var(--cloo-radius-default);
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
		transition:
			background-color 150ms ease,
			border-color 150ms ease,
			color 150ms ease,
			opacity 150ms ease;
	}

	.response-format__mode-button {
		border: 0;
		background: transparent;
		color: var(--cloo-text-muted);
	}

	.response-format__mode-button.is-active {
		background: var(--cloo-bg-surface);
		color: var(--cloo-text-primary);
		box-shadow: 0 1px 2px color-mix(in srgb, var(--cloo-text-default) 10%, transparent);
	}

	.response-format__secondary-button {
		border: 1px solid var(--cloo-border-default);
		background: var(--cloo-bg-surface);
		color: var(--cloo-text-primary);
	}

	.response-format__add-button {
		border: 0;
		background: var(--cloo-color-primary);
		color: var(--cloo-color-on-primary);
	}

	.response-format__subheader-label {
		font-size: 0.75rem;
		line-height: 1rem;
		font-weight: 500;
		color: var(--cloo-text-primary);
	}

	.response-format__empty-state {
		padding: 1rem;
		border: 1px dashed var(--cloo-border-default);
		border-radius: 0.75rem;
		text-align: center;
		font-size: 0.875rem;
		line-height: 1.25rem;
		color: var(--cloo-text-muted);
	}

	.response-format__fields {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.response-format__field-row {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		padding: 0.75rem;
		border: 1px solid var(--cloo-border-subtle);
		border-radius: 0.75rem;
		background: var(--cloo-bg-default);
	}

	.response-format__field-input,
	.response-format__field-caption {
		width: 100%;
		border: 0;
		background: transparent;
		outline: none;
	}

	.response-format__field-input {
		padding: 0.125rem 0.25rem;
		border-bottom: 1px solid var(--cloo-border-subtle);
		font-size: 0.875rem;
		line-height: 1.25rem;
		color: var(--cloo-text-primary);
	}

	.response-format__field-caption {
		padding: 0.25rem;
		margin-top: 0.25rem;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-text-muted);
	}

	.response-format__mini-select,
	.response-format__object-json,
	.response-format__json-input {
		width: 100%;
		border: 1px solid var(--cloo-border-subtle);
		border-radius: var(--cloo-radius-default);
		background: var(--cloo-bg-surface);
		color: var(--cloo-text-default);
		outline: none;
	}

	.response-format__mini-select {
		padding: 0.375rem 0.5rem;
		font-size: 0.75rem;
		line-height: 1rem;
	}

	.response-format__object-json {
		padding: 0.5rem;
		font-size: 0.625rem;
		line-height: 0.875rem;
		font-family: monospace;
		resize: none;
	}

	.response-format__micro-copy {
		margin-top: 0.125rem;
		padding-inline: 0.25rem;
		font-size: 0.625rem;
		line-height: 0.875rem;
		color: var(--cloo-text-muted);
	}

	.response-format__field-actions {
		display: flex;
		flex-direction: column;
		gap: 0.125rem;
	}

	.response-format__action-button {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0.125rem;
		border: 0;
		background: transparent;
		color: var(--cloo-text-muted);
	}

	.response-format__action-button.is-danger {
		color: var(--cloo-color-danger);
	}

	.response-format__json-input {
		padding: 0.75rem;
		font-size: 0.75rem;
		line-height: 1rem;
		font-family: monospace;
		resize: vertical;
	}

	.response-format__json-input.is-error {
		border-color: var(--cloo-color-danger-border);
	}

	.response-format__error-text {
		margin: 0.25rem 0 0;
		font-size: 0.75rem;
		line-height: 1rem;
		color: var(--cloo-color-danger);
	}

	.response-format__notice {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		border: 1px solid color-mix(in srgb, var(--token-scale-warning-300) 80%, transparent);
		border-radius: 0.75rem;
		background: color-mix(in srgb, var(--token-scale-warning-50) 92%, var(--cloo-bg-surface));
		color: var(--token-scale-warning-700);
		font-size: 0.75rem;
		line-height: 1rem;
	}

	.response-format__notice.is-danger {
		border-color: var(--cloo-color-danger-border);
		background: color-mix(in srgb, var(--cloo-color-danger-soft) 92%, var(--cloo-bg-surface));
		color: var(--cloo-color-danger);
	}

	.response-format__notice.is-success {
		border-color: color-mix(in srgb, var(--token-scale-success-300) 85%, transparent);
		background: color-mix(in srgb, var(--token-scale-success-50) 92%, var(--cloo-bg-surface));
		color: var(--token-scale-success-700);
	}

	@media (max-width: 767px) {
		.response-format__header,
		.response-format__toolbar,
		.response-format__subheader,
		.response-format__strict-row {
			flex-direction: column;
			align-items: stretch;
		}

		.response-format__grid {
			grid-template-columns: minmax(0, 1fr);
		}

		.response-format__selector {
			width: 100%;
		}
	}
</style>
