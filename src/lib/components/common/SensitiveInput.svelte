<script lang="ts">
	import Input from './Input.svelte';

	export let value: string = '';
	export let placeholder = '';
	export let required = false;
	export let readOnly = false;
	export let disabled = false;
	export let loading = false;
	export let error = false;
	export let label = '';
	export let caption = '';
	export let size: 'sm' | 'md' = 'sm';
	export let autocomplete: string | undefined = undefined;
	export let ariaLabel: string | undefined = undefined;

	// Legacy custom-styling props (undefined = use design system Input layout)
	export let outerClassName: string | undefined = undefined;
	export let inputClassName: string | undefined = undefined;
	export let showButtonClassName: string | undefined = undefined;

	let show = false;

	$: useLegacy =
		outerClassName !== undefined ||
		inputClassName !== undefined ||
		showButtonClassName !== undefined;

	$: legacyOuterClass = outerClassName ?? 'flex flex-1 bg-transparent';
	$: legacyInputClass =
		inputClassName ??
		'w-full text-sm py-0.5 placeholder:text-gray-300 dark:placeholder:text-gray-700 bg-transparent outline-hidden';
	$: legacyShowButtonClass = showButtonClassName ?? 'pl-1.5  transition bg-transparent';

	const toggleShow = (e: MouseEvent) => {
		e.preventDefault();
		show = !show;
	};
</script>

{#if useLegacy}
	<div class={legacyOuterClass}>
		<input
			class={`${legacyInputClass} ${show ? '' : 'password'}`}
			{placeholder}
			bind:value
			required={required && !readOnly}
			disabled={readOnly || disabled}
			autocomplete={autocomplete ?? 'off'}
			type="text"
			on:input
			on:change
		/>
		<button class={legacyShowButtonClass} type="button" on:click={toggleShow}>
			{#if show}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="size-4"
				>
					<path
						fill-rule="evenodd"
						d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l10.5 10.5a.75.75 0 1 0 1.06-1.06l-1.322-1.323a7.012 7.012 0 0 0 2.16-3.11.87.87 0 0 0 0-.567A7.003 7.003 0 0 0 4.82 3.76l-1.54-1.54Zm3.196 3.195 1.135 1.136A1.502 1.502 0 0 1 9.45 8.389l1.136 1.135a3 3 0 0 0-4.109-4.109Z"
						clip-rule="evenodd"
					/>
					<path
						d="m7.812 10.994 1.816 1.816A7.003 7.003 0 0 1 1.38 8.28a.87.87 0 0 1 0-.566 6.985 6.985 0 0 1 1.113-2.039l2.513 2.513a3 3 0 0 0 2.806 2.806Z"
					/>
				</svg>
			{:else}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 16 16"
					fill="currentColor"
					class="size-4"
				>
					<path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
					<path
						fill-rule="evenodd"
						d="M1.38 8.28a.87.87 0 0 1 0-.566 7.003 7.003 0 0 1 13.238.006.87.87 0 0 1 0 .566A7.003 7.003 0 0 1 1.379 8.28ZM11 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
						clip-rule="evenodd"
					/>
				</svg>
			{/if}
		</button>
	</div>
{:else}
	<Input
		bind:value
		{label}
		{caption}
		{placeholder}
		{size}
		{required}
		{readOnly}
		{disabled}
		{loading}
		{error}
		type={show ? 'text' : 'password'}
		autocomplete={autocomplete ?? 'off'}
		{ariaLabel}
		on:input
		on:change
	>
		<svelte:fragment slot="suffix">
			<button
				type="button"
				class="flex items-center justify-center text-[var(--cloo-text-muted)] hover:text-[var(--cloo-text-default)] transition bg-transparent"
				on:click={toggleShow}
				aria-label={show ? 'Hide value' : 'Show value'}
			>
				{#if show}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path
							fill-rule="evenodd"
							d="M3.28 2.22a.75.75 0 0 0-1.06 1.06l10.5 10.5a.75.75 0 1 0 1.06-1.06l-1.322-1.323a7.012 7.012 0 0 0 2.16-3.11.87.87 0 0 0 0-.567A7.003 7.003 0 0 0 4.82 3.76l-1.54-1.54Zm3.196 3.195 1.135 1.136A1.502 1.502 0 0 1 9.45 8.389l1.136 1.135a3 3 0 0 0-4.109-4.109Z"
							clip-rule="evenodd"
						/>
						<path
							d="m7.812 10.994 1.816 1.816A7.003 7.003 0 0 1 1.38 8.28a.87.87 0 0 1 0-.566 6.985 6.985 0 0 1 1.113-2.039l2.513 2.513a3 3 0 0 0 2.806 2.806Z"
						/>
					</svg>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 16 16"
						fill="currentColor"
						class="size-4"
					>
						<path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z" />
						<path
							fill-rule="evenodd"
							d="M1.38 8.28a.87.87 0 0 1 0-.566 7.003 7.003 0 0 1 13.238.006.87.87 0 0 1 0 .566A7.003 7.003 0 0 1 1.379 8.28ZM11 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
							clip-rule="evenodd"
						/>
					</svg>
				{/if}
			</button>
		</svelte:fragment>
	</Input>
{/if}
