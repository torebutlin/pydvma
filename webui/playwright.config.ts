import { defineConfig } from '@playwright/test';

/**
 * First Playwright e2e config for the web UI (Task 9). Tests live in
 * `e2e/`; the built app is served by `vite preview` on port 4173. The
 * webServer runs a fresh `build` then `preview`, and reuses an already-
 * running server when one is present (so repeated local runs are fast).
 */
export default defineConfig({
  testDir: 'e2e',
  use: {
    baseURL: 'http://localhost:4173',
    // Fake mic so the Live monitor's getUserMedia resolves headlessly with a
    // built-in sine source (used by live.spec.ts); harmless for other specs.
    launchOptions: {
      args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'],
    },
  },
  webServer: {
    command: 'npm run build && npm run preview',
    port: 4173,
    reuseExistingServer: true,
  },
});
