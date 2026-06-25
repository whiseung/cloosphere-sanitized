import type { PermissionLevel } from '$lib/stores';

/** "none"이 아닌 모든 레벨(access/read/write)을 유효 권한으로 판단 */
export function hasPermission(level: PermissionLevel | string | undefined | null): boolean {
	return !!level && level !== 'none';
}
