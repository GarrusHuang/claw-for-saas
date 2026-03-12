import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    projects: [
      'packages/claw-core/vitest.config.ts',
      'packages/claw-ui/vitest.config.ts',
      'app/vitest.config.ts',
    ],
  },
});
