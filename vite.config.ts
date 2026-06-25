import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

// /** @type {import('vite').Plugin} */
// const viteServerConfig = {
// 	name: 'log-request-middleware',
// 	configureServer(server) {
// 		server.middlewares.use((req, res, next) => {
// 			res.setHeader('Access-Control-Allow-Origin', '*');
// 			res.setHeader('Access-Control-Allow-Methods', 'GET');
// 			res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
// 			res.setHeader('Cross-Origin-Embedder-Policy', 'require-corp');
// 			next();
// 		});
// 	}
// };

export default defineConfig({
	plugins: [
		sveltekit(),
		viteStaticCopy({
			silent: true,
			targets: [
				{
					src: 'node_modules/onnxruntime-web/dist/*.jsep.*',
					dest: 'wasm'
				},
				{
					src: 'guide/**/*',
					dest: 'guide'
				}
			]
		})
	],
	server: {
		proxy: {
			// 개발 환경에서 백엔드 정적 파일 프록시 (CORS 우회)
			'/static': {
				target: 'http://localhost:8080',
				changeOrigin: true
			},
			'/cache': {
				target: 'http://localhost:8080',
				changeOrigin: true
			},
			'/api/v1/branding': {
				target: 'http://localhost:8080',
				changeOrigin: true
			},
			// 문서 생성 툴(create_pptx/docx/xlsx) 의 signed URL 다운로드 경로.
			// LLM 응답에 박힌 ${WEBUI_URL}/api/v1/files/{id}/public?... 링크가
			// dev 모드(WEBUI_URL=5173)에서도 동작하도록 백엔드로 프록시.
			'/api/v1/files': {
				target: 'http://localhost:8080',
				changeOrigin: true
			}
		}
	},
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build'),
		// 고객사별 브랜딩: 환경변수로 변경 가능 (기본값: ClooSphere)
		APP_NAME: JSON.stringify(process.env.APP_NAME || 'ClooSphere')
	},
	build: {
		sourcemap: false,
		chunkSizeWarningLimit: 2000,
		rollupOptions: {
			output: {
				// Let Vite automatically split chunks for optimal loading
				manualChunks: undefined
			}
		}
	},
	worker: {
		format: 'es'
	}
});
