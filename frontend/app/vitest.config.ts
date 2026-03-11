import { defineConfig } from 'vitest/config';
import path from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@claw/core': path.resolve(__dirname, '../packages/claw-core/src/index.ts'),
      '@claw/ui': path.resolve(__dirname, '../packages/claw-ui/src/index.ts'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    root: path.resolve(__dirname),
    include: ['__tests__/**/*.test.{ts,tsx}'],
    setupFiles: ['../packages/claw-ui/test/setup.ts'],
  },
});
