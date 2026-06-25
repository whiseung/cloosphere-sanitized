/**
 * 디렉토리 파일 선택 유틸리티.
 *
 * 기본 경로: File System Access API (`showDirectoryPicker`)
 *   - Chromium 계열에서 한 번만 권한 프롬프트 → 대량 업로드 시 네이티브
 *     "이 사이트에 N개 파일을 업로드하시겠습니까?" 확인창을 우회
 *
 * 폴백 경로: 숨김 `<input webkitdirectory>` 클릭
 *   - Firefox/Safari 등 미지원 브라우저
 *   - 이 경우는 브라우저 네이티브 확인창이 뜨는 걸 피할 수 없음
 *
 * 숨김/잡파일(`.*`, Thumbs.db, desktop.ini)은 기본 제외.
 */

type FileSystemHandleKind = 'file' | 'directory';
interface FileSystemHandleBase {
	kind: FileSystemHandleKind;
	name: string;
}
interface FileSystemFileHandleLike extends FileSystemHandleBase {
	kind: 'file';
	getFile(): Promise<File>;
}
interface FileSystemDirectoryHandleLike extends FileSystemHandleBase {
	kind: 'directory';
	values(): AsyncIterable<FileSystemFileHandleLike | FileSystemDirectoryHandleLike>;
}

const SKIP_FILENAMES = new Set(['Thumbs.db', 'desktop.ini', '.DS_Store']);

const isSkipFile = (name: string): boolean => {
	if (!name) return true;
	if (name.startsWith('.')) return true;
	if (SKIP_FILENAMES.has(name)) return true;
	return false;
};

const assignRelativePath = (file: File, relativePath: string): File => {
	// webkitRelativePath 는 읽기 전용이라 직접 set 불가 — defineProperty 로 주입
	try {
		Object.defineProperty(file, 'webkitRelativePath', {
			value: relativePath,
			configurable: true
		});
	} catch {
		// 이미 값이 있어서 실패하면 무시
	}
	return file;
};

const walkDirectoryHandle = async (
	dirHandle: FileSystemDirectoryHandleLike,
	basePath: string,
	accumulator: File[]
): Promise<void> => {
	for await (const entry of dirHandle.values()) {
		const relPath = basePath ? `${basePath}/${entry.name}` : entry.name;
		if (isSkipFile(entry.name)) continue;
		if (entry.kind === 'file') {
			try {
				const file = await (entry as FileSystemFileHandleLike).getFile();
				if (file.size > 0) {
					accumulator.push(assignRelativePath(file, relPath));
				}
			} catch (e) {
				console.warn('directory-picker: failed to read file', relPath, e);
			}
		} else if (entry.kind === 'directory') {
			await walkDirectoryHandle(entry as FileSystemDirectoryHandleLike, relPath, accumulator);
		}
	}
};

/**
 * File System Access API 로 디렉토리 선택 → 재귀적으로 파일 수집.
 *
 * 반환값:
 *   - `{ files: File[] }`  성공 (빈 디렉토리면 빈 배열)
 *   - `{ canceled: true }` 사용자가 다이얼로그를 취소
 *   - `{ unsupported: true }` API 미지원 브라우저 (폴백 필요)
 */
export const pickDirectoryViaFileSystemAPI = async (): Promise<
	{ files: File[] } | { canceled: true } | { unsupported: true }
> => {
	const win = window as unknown as {
		showDirectoryPicker?: (opts?: { mode?: 'read' | 'readwrite' }) => Promise<
			FileSystemDirectoryHandleLike
		>;
	};
	if (typeof win.showDirectoryPicker !== 'function') {
		return { unsupported: true };
	}
	try {
		const handle = await win.showDirectoryPicker({ mode: 'read' });
		const files: File[] = [];
		// 최상위 디렉토리 이름부터 상대 경로로 기록 → 기존 webkitRelativePath 포맷 유지
		await walkDirectoryHandle(handle, handle.name, files);
		return { files };
	} catch (e: unknown) {
		// 사용자 취소 또는 권한 거부
		if (
			e instanceof DOMException &&
			(e.name === 'AbortError' || e.name === 'NotAllowedError')
		) {
			return { canceled: true };
		}
		console.error('pickDirectoryViaFileSystemAPI error:', e);
		return { canceled: true };
	}
};

/**
 * `<input webkitdirectory>` 클릭 + change 대기 방식의 디렉토리 선택.
 * File System Access API 미지원 브라우저용 폴백.
 */
export const pickDirectoryViaInput = (inputEl: HTMLInputElement): Promise<File[]> => {
	return new Promise((resolve) => {
		let settled = false;
		const cleanup = () => {
			inputEl.removeEventListener('change', onChange);
			window.removeEventListener('focus', onFocus);
		};
		const onChange = () => {
			if (settled) return;
			settled = true;
			cleanup();
			const picked = Array.from(inputEl.files ?? []) as File[];
			// 숨김/잡파일 필터링
			const filtered = picked.filter((f) => {
				const rel = f.webkitRelativePath || f.name;
				const base = rel.split('/').pop() || '';
				if (isSkipFile(base)) return false;
				return f.size > 0;
			});
			// 다음 선택에서 같은 폴더를 다시 고를 수 있게 초기화
			inputEl.value = '';
			resolve(filtered);
		};
		// focus 이벤트로 "다이얼로그 취소" 감지 (change 이벤트가 발생 안 함)
		const onFocus = () => {
			// 다이얼로그 닫힘 감지를 위해 약간의 지연
			setTimeout(() => {
				if (settled) return;
				if (!inputEl.files || inputEl.files.length === 0) {
					settled = true;
					cleanup();
					resolve([]);
				}
			}, 300);
		};
		inputEl.addEventListener('change', onChange, { once: false });
		window.addEventListener('focus', onFocus, { once: true });
		inputEl.click();
	});
};

/**
 * 디렉토리 선택 통합 엔트리 — File System Access 우선, 폴백은 input 엘리먼트.
 *
 * @param fallbackInputEl `<input webkitdirectory>` 요소 (폴백 경로에서만 사용)
 * @returns 수집된 파일 목록 (취소/빈 선택은 빈 배열)
 */
export const pickDirectoryFiles = async (
	fallbackInputEl: HTMLInputElement | null
): Promise<File[]> => {
	const result = await pickDirectoryViaFileSystemAPI();
	if ('files' in result) return result.files;
	if ('canceled' in result) return [];
	// unsupported → 폴백
	if (!fallbackInputEl) return [];
	return pickDirectoryViaInput(fallbackInputEl);
};
