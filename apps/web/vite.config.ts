import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: true },
      '/auth': { target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 4173,
    proxy: {
      '/api': { target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: true },
      '/auth': { target: process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { target: 'es2022', sourcemap: false, chunkSizeWarningLimit: 700 },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    setupFiles: ['./src/test/setup.ts'],
    restoreMocks: true,
    clearMocks: true,
    // The full jsdom suite starts several editor-heavy files in parallel.
    // Keep individual assertions strict while allowing for shared CI/desktop CPU contention.
    testTimeout: 10_000,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      thresholds: {
        statements: 70,
        branches: 60,
        functions: 35,
        lines: 70,
      },
    },
  },
});
