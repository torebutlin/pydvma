import { defineConfig } from '@playwright/test';

/**
 * First Playwright e2e config for the web UI (Task 9). Tests live in
 * `e2e/`; the built app is served by `vite preview` on port 4173. The
 * webServer runs a fresh `build` then `preview`, and reuses an already-
 * running server when one is present (so repeated local runs are fast).
 */
export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: 'http://localhost:4173' },
  webServer: {
    command: 'npm run build && npm run preview',
    port: 4173,
    reuseExistingServer: true,
  },
});
