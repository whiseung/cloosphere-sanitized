<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { updateUserPassword } from '$lib/apis/auths';
	import Button from '$lib/components/common/Button.svelte';
	import Input from '$lib/components/common/Input.svelte';
	import LabelBase from '$lib/components/common/LabelBase.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';

	const i18n = getContext('i18n');

	let show = false;
	let currentPassword = '';
	let newPassword = '';
	let newPasswordConfirm = '';

	const updatePasswordHandler = async () => {
		if (newPassword === newPasswordConfirm) {
			const res = await updateUserPassword(localStorage.token, currentPassword, newPassword).catch(
				(error) => {
					toast.error($i18n.t(`${error}`));
					return null;
				}
			);

			if (res) {
				toast.success($i18n.t('Successfully updated.'));
			}

			currentPassword = '';
			newPassword = '';
			newPasswordConfirm = '';
		} else {
			toast.error(
				`The passwords you entered don't quite match. Please double-check and try again.`
			);
			newPassword = '';
			newPasswordConfirm = '';
		}
	};
</script>

<form
	class="flex flex-col text-sm"
	on:submit|preventDefault={() => {
		updatePasswordHandler();
	}}
>
	<LabelBase label={$i18n.t('Change Password')} size="md">
		<svelte:fragment slot="right">
			<Button
				kind="text"
				size="sm"
				on:click={() => {
					show = !show;
				}}
			>
				{#if show}
					<ChevronUp className="size-4" strokeWidth="2" />
				{:else}
					<ChevronDown className="size-4" strokeWidth="2" />
				{/if}
			</Button>
		</svelte:fragment>
	</LabelBase>

	{#if show}
		<div class="py-2.5 space-y-2">
			<Input
				bind:value={currentPassword}
				label={$i18n.t('Current Password')}
				type="password"
				placeholder={$i18n.t('Enter your current password')}
				size="md"
				autocomplete="current-password"
				required
			/>

			<Input
				bind:value={newPassword}
				label={$i18n.t('New Password')}
				type="password"
				placeholder={$i18n.t('Enter your new password')}
				size="md"
				autocomplete="new-password"
				required
			/>

			<Input
				bind:value={newPasswordConfirm}
				label={$i18n.t('Confirm Password')}
				type="password"
				placeholder={$i18n.t('Confirm your new password')}
				size="md"
				autocomplete="off"
				required
			/>
		</div>

		<div class="mt-3 flex justify-end">
			<Button kind="filled" size="md" type="submit">
				{$i18n.t('Update password')}
			</Button>
		</div>
	{/if}
</form>
