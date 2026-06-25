import { writable, derived } from 'svelte/store';

export type ToastType = 'success' | 'error' | 'info' | 'warning' | 'running';

export interface ToastProgress {
	current: number | null;
	total: number | null;
	label?: string | null;
	// 진행 중 발생한 오류(실패) 개수 — 진행 카운트 옆에 "(N)" 으로 노출 (옵션).
	failed?: number | null;
}

export interface ToastHistoryItem {
	id: string;
	type: ToastType;
	message: string;
	timestamp: number;
	read: boolean;
	// 진행률(running 등 장시간 작업)을 bar 로 표현할 때 사용.
	progress?: ToastProgress | null;
	// 클릭 시 이동할 라우트 (옵션). 없으면 클릭 액션 없음.
	linkTo?: string | null;
	// true 면 history 에서 자동으로 사라지지 않고 명시적 dismiss 요구.
	persistent?: boolean;
}

const MAX_HISTORY = 50;

function createToastHistoryStore() {
	const { subscribe, update, set } = writable<ToastHistoryItem[]>([]);

	return {
		subscribe,
		add(type: ToastType, message: string): string {
			const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
			const item: ToastHistoryItem = {
				id,
				type,
				message: typeof message === 'string' ? message : String(message),
				timestamp: Date.now(),
				read: false
			};
			update((items) => [item, ...items].slice(0, MAX_HISTORY));
			return id;
		},
		/**
		 * 특정 id 의 item 을 upsert. 이미 있으면 patch 필드만 갱신 + 최신 타임스탬프로 정렬.
		 * 없으면 신규 추가. 진행률 추적용 엔트리에 사용.
		 */
		upsert(id: string, patch: Partial<Omit<ToastHistoryItem, 'id' | 'timestamp'>>) {
			update((items) => {
				const idx = items.findIndex((it) => it.id === id);
				if (idx >= 0) {
					const prev = items[idx];
					const nextItem: ToastHistoryItem = {
						...prev,
						...patch,
						id: prev.id,
						timestamp: Date.now()
					};
					const next = items.slice();
					next.splice(idx, 1);
					return [nextItem, ...next].slice(0, MAX_HISTORY);
				}
				const nextItem: ToastHistoryItem = {
					id,
					type: patch.type ?? 'info',
					message: patch.message ?? '',
					timestamp: Date.now(),
					read: patch.read ?? false,
					progress: patch.progress ?? null,
					linkTo: patch.linkTo ?? null,
					persistent: patch.persistent ?? false
				};
				return [nextItem, ...items].slice(0, MAX_HISTORY);
			});
		},
		markAllRead() {
			update((items) => items.map((item) => ({ ...item, read: true })));
		},
		remove(id: string) {
			update((items) => items.filter((item) => item.id !== id));
		},
		clear() {
			set([]);
		}
	};
}

export const toastHistory = createToastHistoryStore();

export const unreadToastCount = derived(toastHistory, ($history) =>
	$history.filter((item) => !item.read).length
);
