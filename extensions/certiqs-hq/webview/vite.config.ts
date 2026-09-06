import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

export default defineConfig({
	plugins: [react(), tailwindcss()],
	root: path.resolve(__dirname),
	define: {
		'process.env.NODE_ENV': JSON.stringify('production'),
		'process.env': JSON.stringify({ NODE_ENV: 'production' }),
	},
	build: {
		outDir: path.resolve(__dirname, '../media'),
		emptyOutDir: true,
		cssCodeSplit: false,
		sourcemap: false,
		minify: true,
		lib: {
			entry: path.resolve(__dirname, 'src/main.tsx'),
			name: 'CertiqsHq',
			formats: ['iife'],
			fileName: () => 'webview.js',
		},
		rollupOptions: {
			output: {
				assetFileNames: 'webview[extname]',
			},
		},
	},
});
