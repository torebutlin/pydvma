import { test, expect } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * `pydvma serve` bridge e2e (Wave B).  The app (served by `vite preview`
 * on :4173, per playwright.config.ts) is opened with `?bridge=ws://…` so
 * the BridgeProvider drives a REAL `pydvma serve` process instead of the
 * Web Audio path.  It proves the full loop over the socket: capabilities →
 * bridge devices in Setup, start_monitor → frames streaming into the mini
 * oscilloscope, and log → a `.dvma` container parsed back into a set that
 * lands in the tray.
 *
 * SKIPPED unless `BRIDGE_E2E` is set, because the CI Playwright runner has
 * no pydvma + websockets installed.  To run locally:
 *
 *     BRIDGE_E2E=1 npx playwright test e2e/bridge.spec.ts
 *
 * This spec spawns `python3 -m pydvma.serve --driver mock --port 8763`
 * itself (beforeAll) and tears it down (afterAll); pydvma must be
 * importable (`pip install -e .`) and the `[serve]` extra present
 * (`pip install websockets`).  Equivalent manual form: run
 * `python3 -m pydvma.serve --driver mock --port 8763` in another shell
 * first, then the command above.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
const PORT = Number(process.env.BRIDGE_PORT ?? 8763);
const WS_URL = `ws://127.0.0.1:${PORT}/ws`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

let server: ChildProcessWithoutNullStreams | undefined;

/** Poll the loopback TCP port until the bridge server accepts a connection. */
function waitForPort(port: number, timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() > deadline) reject(new Error(`bridge port ${port} never opened`));
        else setTimeout(attempt, 200);
      });
    };
    attempt();
  });
}

test.beforeAll(async () => {
  if (!BRIDGE_E2E) return;
  server = spawn('python3', ['-m', 'pydvma.serve', '--driver', 'mock', '--port', String(PORT)], {
    cwd: REPO_ROOT,
    stdio: 'pipe',
  });
  server.stdout.on('data', () => { /* drain */ });
  server.stderr.on('data', () => { /* drain */ });
  await waitForPort(PORT);
});

test.afterAll(async () => {
  if (!server) return;
  server.kill('SIGINT');
  await new Promise((r) => setTimeout(r, 300));
});

test.describe('pydvma serve bridge', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python3 -m pydvma.serve)');

  test('bridge devices appear in Setup, the monitor streams, and Log Data lands a set', async ({ page }) => {
    await page.goto(`/?bridge=${encodeURIComponent(WS_URL)}`);

    const ribbon = page.getByRole('navigation', { name: 'stages' });
    // Capabilities resolving over the socket flips the liveSource gate:
    // the Setup stage un-gates once the bridge is connected.
    await expect(ribbon.getByRole('button', { name: 'Setup' })).not.toHaveClass(/gated/, { timeout: 20000 });
    await ribbon.getByRole('button', { name: 'Setup' }).click();

    // The device dropdown lists BRIDGE devices — the mock backend's
    // synthetic entry is always present.
    const deviceSelect = page.getByRole('combobox', { name: 'input device' });
    await expect(deviceSelect).toContainText('Mock signal generator');
    await deviceSelect.selectOption({ label: 'Mock signal generator' });
    // A short capture keeps the mock log quick.
    await page.getByRole('combobox', { name: 'duration' }).selectOption('0.5');

    // Start the monitor from the mini oscilloscope: configure + start_monitor
    // round-trip the socket, and chunk frames begin flowing (isStreaming).
    await page.getByTestId('mini-start').click();
    await expect(page.getByTestId('mini-stop')).toBeVisible({ timeout: 20000 });
    await expect(page.getByTestId('mini-monitor')).toContainText('live');

    // Stop the monitor before logging (clean single-stream capture).
    await page.getByTestId('mini-stop').click();
    await expect(page.getByTestId('mini-start')).toBeVisible();

    // Log Data → the bridge runs a mock capture, returns a .dvma container,
    // and the parsed set lands in the tray.
    await ribbon.getByRole('button', { name: 'Acquire' }).click();
    await page.getByRole('button', { name: 'Log Data' }).click();
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
  });

  /** Setup → Acquire with the Mock device selected and a short duration. */
  async function gotoAcquireWithMock(page: import('@playwright/test').Page) {
    await page.goto(`/?bridge=${encodeURIComponent(WS_URL)}`);
    const ribbon = page.getByRole('navigation', { name: 'stages' });
    await expect(ribbon.getByRole('button', { name: 'Setup' })).not.toHaveClass(/gated/, { timeout: 20000 });
    await ribbon.getByRole('button', { name: 'Setup' }).click();
    const deviceSelect = page.getByRole('combobox', { name: 'input device' });
    await expect(deviceSelect).toContainText('Mock signal generator');
    await deviceSelect.selectOption({ label: 'Mock signal generator' });
    await page.getByRole('combobox', { name: 'duration' }).selectOption('0.5');
    await ribbon.getByRole('button', { name: 'Acquire' }).click();
  }

  test('Wave C: the output group renders (mock reports ao) and a log WITH output lands a set', async ({ page }) => {
    await gotoAcquireWithMock(page);

    // The mock backend reports ao:true (setup_output_mock), so the Acquire
    // output group renders. If a server build predates that capability,
    // self-skip rather than fail (do not fake it).
    const outGroup = page.getByTestId('acquire-output');
    if (!(await outGroup.isVisible().catch(() => false))) {
      test.skip(true, 'server does not report AO capability — no output group');
    }

    // Arm the output stimulus → the Log button gains the OUT badge, and the
    // log message carries output = {type, amp, f1, f2}.
    await page.getByTestId('output-on').check();
    await expect(page.getByTestId('out-badge')).toBeVisible();

    await page.getByTestId('log-btn').click();
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
  });

  test('Wave C: an armed pretrigger shows "armed" and a mock timeout still lands a set', async ({ page }) => {
    await gotoAcquireWithMock(page);

    // Pretrigger arm renders only when the bridge advertises pretrigger.
    const arm = page.getByTestId('pretrig-arm');
    if (!(await arm.isVisible().catch(() => false))) {
      test.skip(true, 'server does not report pretrigger capability');
    }
    await arm.check();
    // A short timeout keeps the mock's never-trigger path quick.
    await page.getByTestId('pretrig-timeout').fill('0.3');

    await page.getByTestId('log-btn').click();

    // The bridge surfaces the server's `armed` status event; this state is
    // stable for the length of the capture (the transient `timeout` right
    // before completion — MockRecorder never triggers — is covered by the
    // fake-transport unit test, and the view switches to Time on completion).
    await expect(page.getByTestId('pretrig-status')).toContainText('armed', { timeout: 20000 });
    // The buffered capture still lands as a set despite no trigger.
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
  });

  test('round-4: the pretrigger arm control edits the sample count and a log lands a set', async ({ page }) => {
    await gotoAcquireWithMock(page);

    const arm = page.getByTestId('pretrig-arm');
    if (!(await arm.isVisible().catch(() => false))) {
      test.skip(true, 'server does not report pretrigger capability');
    }
    await arm.check();

    // The editable samples input appears on the arm control, prefilled with the
    // bare-arm default (100 — round-4 item 11, was a wasteful 1000).
    const samples = page.getByTestId('pretrig-samples-arm');
    await expect(samples).toBeVisible();
    await expect(samples).toHaveValue('100');
    // Edit it directly on the arm control (drives the same store value Setup shows).
    await samples.fill('150');
    // A short timeout keeps the mock's never-trigger path quick.
    await page.getByTestId('pretrig-timeout').fill('0.3');

    await page.getByTestId('log-btn').click();
    // The server arms with the edited count; MockRecorder times out but the
    // buffered set still lands.
    await expect(page.getByTestId('pretrig-status')).toContainText('armed', { timeout: 20000 });
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
  });

  test('round-4: the output group exposes duration + device/channels and a fuller-output log lands a set', async ({ page }) => {
    await gotoAcquireWithMock(page);

    const outGroup = page.getByTestId('acquire-output');
    if (!(await outGroup.isVisible().catch(() => false))) {
      test.skip(true, 'server does not report AO capability — no output group');
    }
    await page.getByTestId('output-on').check();
    await expect(page.getByTestId('out-badge')).toBeVisible();

    // Fuller controls (round-4 item 12): an explicit output duration…
    await page.getByTestId('output-duration').fill('0.3');
    // …and, when the bridge lists AO devices, an output device + channel count.
    const dev = page.getByTestId('output-device');
    if (await dev.isVisible().catch(() => false)) {
      await dev.selectOption({ label: 'Mock signal generator' });
      await page.getByTestId('output-channels').fill('1');
    }

    await page.getByTestId('log-btn').click();
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
  });

  test('Wave D regression: an honoured mock rate shows no DSA coerced-fs note', async ({ page }) => {
    // The mock driver reports no vmax caps and echoes the requested fs
    // exactly, so this can only be a NEGATIVE regression: exercise the
    // onConfigured wiring end-to-end and confirm no spurious coerced-fs note
    // fires. (The positive clamp/coercion paths are covered in vitest with
    // fake caps — the mock never triggers them.)
    await page.goto(`/?bridge=${encodeURIComponent(WS_URL)}`);
    const ribbon = page.getByRole('navigation', { name: 'stages' });
    await expect(ribbon.getByRole('button', { name: 'Setup' })).not.toHaveClass(/gated/, { timeout: 20000 });
    await ribbon.getByRole('button', { name: 'Setup' }).click();
    const deviceSelect = page.getByRole('combobox', { name: 'input device' });
    await expect(deviceSelect).toContainText('Mock signal generator');
    await deviceSelect.selectOption({ label: 'Mock signal generator' });

    // Force a configure round-trip via the mini monitor.
    await page.getByTestId('mini-start').click();
    await expect(page.getByTestId('mini-stop')).toBeVisible({ timeout: 20000 });
    // The mock honoured the requested rate → the coerced-fs note stays absent.
    await expect(page.getByTestId('setup-coerced-fs')).toHaveCount(0);
    await page.getByTestId('mini-stop').click();
  });
});

/**
 * Launch-config prefill (round-6 Qt-parity): `pydvma serve --settings file.json`
 * serves a MySettings JSON at `/config`, and the app now CONSUMES it — mapping
 * fs / channels / duration / device / pretrigger / output onto the Setup +
 * Acquire stores at boot.  This spec spawns a SECOND server that serves BOTH the
 * built UI (`--ui-dir webui/dist`) and the settings, then opens the app AT that
 * server's own origin (no `?bridge=` param — the same-origin `/config` probe
 * detects the bridge), so `/config` is same-origin exactly as in a real
 * `pydvma-serve` deployment.  Requires `webui/dist` to be built.
 */
const SETTINGS_PORT = Number(process.env.BRIDGE_SETTINGS_PORT ?? 8764);
const SETTINGS_ORIGIN = `http://127.0.0.1:${SETTINGS_PORT}`;
const DIST_DIR = path.join(REPO_ROOT, 'webui', 'dist');

test.describe('pydvma serve --settings launch prefill', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets + a built webui/dist)');

  let settingsServer: ChildProcessWithoutNullStreams | undefined;
  let settingsFile: string | undefined;

  test.beforeAll(async () => {
    if (!BRIDGE_E2E) return;
    if (!fs.existsSync(path.join(DIST_DIR, 'index.html'))) {
      throw new Error(`webui/dist not built (${DIST_DIR}); run \`npm run build\` first`);
    }
    settingsFile = path.join(os.tmpdir(), `pydvma-serve-settings-${Date.now()}.json`);
    fs.writeFileSync(settingsFile, JSON.stringify({
      fs: 8000, channels: 3, stored_time: 5,
      device_driver: 'mock',
      pretrig_samples: 150, pretrig_timeout: 3,
      output: { type: 'sweep', amp: 0.4, f1: 20, f2: 800 },
    }));
    settingsServer = spawn('python3', [
      '-m', 'pydvma.serve', '--driver', 'mock', '--port', String(SETTINGS_PORT),
      '--settings', settingsFile, '--ui-dir', DIST_DIR,
    ], { cwd: REPO_ROOT, stdio: 'pipe' });
    settingsServer.stdout.on('data', () => { /* drain */ });
    settingsServer.stderr.on('data', () => { /* drain */ });
    await waitForPort(SETTINGS_PORT);
  });

  test.afterAll(async () => {
    if (settingsServer) { settingsServer.kill('SIGINT'); await new Promise((r) => setTimeout(r, 300)); }
    if (settingsFile) { try { fs.unlinkSync(settingsFile); } catch { /* */ } }
  });

  test('Setup + Acquire are prefilled from the served MySettings', async ({ page }) => {
    // Open the app AT the settings server's origin so /config is same-origin.
    await page.goto(`${SETTINGS_ORIGIN}/`);
    const ribbon = page.getByRole('navigation', { name: 'stages' });
    await expect(ribbon.getByRole('button', { name: 'Setup' })).not.toHaveClass(/gated/, { timeout: 20000 });
    await ribbon.getByRole('button', { name: 'Setup' }).click();

    // Core input fields reflect the served fs / channels / duration.
    await expect(page.getByRole('combobox', { name: 'sample rate' })).toHaveValue('8000');
    await expect(page.getByRole('spinbutton', { name: 'channel count' })).toHaveValue('3');
    await expect(page.getByRole('combobox', { name: 'duration' })).toHaveValue('5');

    // The device dropdown resolved device_driver='mock' → the mock entry.
    await expect(page.getByRole('combobox', { name: 'input device' }))
      .toHaveValue(/mock:0/);

    // Acquire: the armed pretrigger + output group reflect the served config
    // (only where the mock advertises the capability).
    await ribbon.getByRole('button', { name: 'Acquire' }).click();
    const arm = page.getByTestId('pretrig-arm');
    if (await arm.isVisible().catch(() => false)) {
      await expect(arm).toBeChecked();
    }
    const outOn = page.getByTestId('output-on');
    if (await outOn.isVisible().catch(() => false)) {
      await expect(outOn).toBeChecked();
    }
  });
});
