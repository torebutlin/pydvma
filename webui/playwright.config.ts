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
  webServer: [
    {
      command: 'npm run build && npm run preview',
      port: 4173,
      reuseExistingServer: true,
    },
    {
      // Serves the SAME dist under /pydvma/app/ — the GitHub Pages layout.
      // Regression coverage for root-absolute asset paths (the engine-boot
      // failure that only reproduced on the deployed site): subpath.spec.ts
      // boots the real engine through this server. The symlink makes the
      // sub-path mount track dist without copying; python's http.server
      // follows it. Starts alongside the preview server; specs only run
      // once BOTH ports are ready, and the build belongs to server #1.
      command:
        'mkdir -p .subpath/pydvma && ln -sfn "$(pwd)/dist" .subpath/pydvma/app && python3 -m http.server -d .subpath 4175',
      port: 4175,
      reuseExistingServer: true,
    },
  ],
});
