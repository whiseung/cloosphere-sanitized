import { toast } from 'svelte-sonner';
import { toastHistory } from '$lib/stores/toast-history';

/**
 * sonner toast의 success/error/info/warning 메서드를 패치하여
 * 호출 시 자동으로 토스트 히스토리에 기록.
 * +layout.svelte에서 앱 시작 시 한 번만 호출.
 */
export function initToastHistory() {
	const original = {
		success: toast.success.bind(toast),
		error: toast.error.bind(toast),
		info: toast.info.bind(toast),
		warning: toast.warning.bind(toast)
	};

	toast.success = (message: any, ...args: any[]) => {
		if (typeof message === 'string') toastHistory.add('success', message);
		return (original.success as any)(message, ...args);
	};

	toast.error = (message: any, ...args: any[]) => {
		if (typeof message === 'string') toastHistory.add('error', message);
		return (original.error as any)(message, ...args);
	};

	toast.info = (message: any, ...args: any[]) => {
		if (typeof message === 'string') toastHistory.add('info', message);
		return (original.info as any)(message, ...args);
	};

	toast.warning = (message: any, ...args: any[]) => {
		if (typeof message === 'string') toastHistory.add('warning', message);
		return (original.warning as any)(message, ...args);
	};
}
