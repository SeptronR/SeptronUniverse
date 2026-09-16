import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Dev proxy target for /api, /ws, /uploads, /health. Override with VITE_PROXY_TARGET to develop against another backend.
const API_TARGET = process.env.VITE_PROXY_TARGET || 'http://localhost:8000';
const WS_TARGET = API_TARGET.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        // recharts is pulled in by every page with a chart — split it once so it is cached across navigations
        manualChunks: { charts: ['recharts'], vendor: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'] },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true, ws: true },
      '/uploads': { target: API_TARGET, changeOrigin: true },
      '/health': { target: API_TARGET, changeOrigin: true },
      '/ready': { target: API_TARGET, changeOrigin: true },
      '/ws': { target: WS_TARGET, ws: true },
    },
  },
});
