// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces

// Vite define 상수 (vite.config.ts에서 빌드 시 주입)
declare const APP_NAME: string;
declare const APP_VERSION: string;
declare const APP_BUILD_HASH: string;

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface Platform {}
	}
}

export {};
