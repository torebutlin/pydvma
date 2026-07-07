import { test, expect } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import net from 'node:net';
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
});
