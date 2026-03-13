import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@claw/core': path.resolve(__dirname, '../packages/claw-core/src/index.ts'),
      '@claw/ui': path.resolve(__dirname, '../packages/claw-ui/src/index.ts'),
    },
  },
  server: {
    port: 3001,
    proxy: {
      '/api/ws': { target: 'ws://localhost:8000', ws: true },
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
