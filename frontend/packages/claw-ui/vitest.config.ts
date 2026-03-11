import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@claw/core': path.resolve(__dirname, '../claw-core/src/index.ts'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    root: path.resolve(__dirname),
    include: ['__tests__/**/*.test.{ts,tsx}'],
    setupFiles: ['./test/setup.ts'],
  },
});
