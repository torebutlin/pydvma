import { test, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

/**
 * Settings pushed from a notebook into an OPEN app (`Session.apply_settings`).
 *
 * A real `dvma.launch` runs in a spawned Python process that takes one JSON
 * command per stdin line and calls `session.apply_settings(...)`, printing the
 * notebook's own confirmation line and then `OK` (or `ERR <message>`). The page
 * is opened at the session's own URL — the launch path exactly, `/config` and
 * the bridge on one origin. Mock driver, so it runs anywhere pydvma does.
 *
 * Gated on BRIDGE_E2E like every spec that spawns Python.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// Port claim: see the list in engine-native.spec.ts.
const PORT = Number(process.env.NOTEBOOK_PORT ?? 8769);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST_DIR = path.join(REPO_ROOT, 'webui', 'dist');

const DRIVER = `
import json, sys
from pydvma import options
from pydvma.session import launch
port, ui_dir, session_dir = int(sys.argv[1]), sys.argv[2], sys.argv[3]
s = launch(options.MySettings(device_driver='mock', fs=8000, channels=1, stored_time=1),
           open_browser=False, port=port, ui_dir=ui_dir, session_dir=session_dir,
           recover=False)
print('READY', flush=True)
for line in sys.stdin:
    cmd = json.loads(line)
    try:
        settings = cmd.get('settings')
        s.apply_settings(None if settings is None else options.MySettings(**settings),
                         **cmd.get('kw', {}))
        print('OK', flush=True)
    except Exception as e:
        print('ERR', type(e).__name__, str(e).replace('\\n', ' '), flush=True)
`;

let py: ChildProcessWithoutNullStreams | undefined;
let sessionDir: string | undefined;
let lines: string[] = [];

/**
 * Consume stdout up to and including the next line that starts with one of
 * `prefixes`; returns every consumed line (the match last).
 */
async function upTo(prefixes: string[], timeoutMs = 20000): Promise<string[]> {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const i = lines.findIndex((l) => prefixes.some((p) => l.startsWith(p)));
    if (i >= 0) return lines.splice(0, i + 1);
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`no ${prefixes.join('/')} line; got: ${lines.join(' | ')}`);
}

/** Push settings from the "notebook": `end` is OK / ERR, `printed` what came before. */
async function push(settings: Record<string, unknown> | null, kw: Record<string, unknown> = {}) {
  py!.stdin.write(JSON.stringify({ settings, kw }) + '\n');
  const out = await upTo(['OK', 'ERR']);
  return { end: out[out.length - 1], printed: out.slice(0, -1).join('\n') };
}

function waitForPort(port: number, timeoutMs = 20000): Promise<void> {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() - t0 > timeoutMs) reject(new Error(`port ${port} never opened`));
        else setTimeout(attempt, 200);
      });
    };
    attempt();
  });
}

const ribbon = (page: Page) => page.getByRole('navigation', { name: 'stages' });

/**
 * Open the session's own URL and wait until the tab has BOOTED — its device
 * list is in, which comes after the bridge socket is up. "Setup is active" is
 * not enough: the app opens on Setup before it has connected.
 */
async function openBooted(page: Page) {
  await page.goto(`${ORIGIN}/`);
  await expect(ribbon(page).getByRole('button', { name: 'Setup' })).toHaveClass(/active/, { timeout: 20000 });
  await expect(page.getByRole('combobox', { name: 'input device' }))
    .toContainText('Mock signal generator', { timeout: 20000 });
}

test.describe('notebook → open app: Session.apply_settings', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python3)');
  test.setTimeout(120_000);

  test.beforeAll(async () => {
    if (!BRIDGE_E2E) return;
    sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-e2e-'));
    lines = [];
    py = spawn(PYTHON, ['-c', DRIVER, String(PORT), DIST_DIR, sessionDir],
      { cwd: REPO_ROOT, stdio: 'pipe' });
    let buf = '';
    py.stdout.on('data', (d: Buffer) => {
      buf += d.toString();
      const parts = buf.split('\n');
      buf = parts.pop() ?? '';
      lines.push(...parts.map((l) => l.trim()).filter(Boolean));
    });
    py.stderr.on('data', () => { /* drain */ });
    await upTo(['READY'], 30000);
    await waitForPort(PORT);
  });

  test.afterAll(async () => {
    if (py) { py.kill('SIGINT'); await new Promise((r) => setTimeout(r, 300)); py = undefined; }
    if (sessionDir) { fs.rmSync(sessionDir, { recursive: true, force: true }); sessionDir = undefined; }
  });

  test('hammer settings arm the trigger in the open tab; noise settings disarm it; a reload keeps them',
    async ({ page }) => {
      // Opens on Setup, prefilled from the launch settings.
      await openBooted(page);
      await expect(page.getByTestId('setup-fs')).toHaveValue('8000');
      await expect(page.getByTestId('setup-pretrig-arm')).not.toBeChecked();

      // Hammer: 3000 Hz, 2 ch, armed at 0.25 (mock: full-scale units).
      const hammer = await push({ device_driver: 'mock', fs: 3000, channels: 2, stored_time: 6,
        pretrig_samples: 100, pretrig_threshold: 0.25 });
      expect(hammer.end).toBe('OK');
      expect(hammer.printed).toContain(
        'logger settings: 3000 Hz, 2 ch, 6 s, trigger armed on ch 0 at 0.25 × full scale (applied in 1 app tab)');
      await expect(page.getByTestId('setup-fs')).toHaveValue('3000');
      await expect(page.getByRole('spinbutton', { name: 'channel count' })).toHaveValue('2');
      await expect(page.getByTestId('setup-duration')).toHaveValue('6');
      await expect(page.getByTestId('setup-pretrig-arm')).toBeChecked();
      await expect(page.getByTestId('setup-pretrig-threshold')).toHaveValue('0.25');
      await expect(page.getByText(/Settings from the notebook: 3000 Hz · 2 ch · 6 s · trigger armed/))
        .toBeVisible();

      // Noise: pretrig_samples / pretrig_threshold left at None → disarmed, blank threshold.
      const noise = await push({ device_driver: 'mock', fs: 3000, channels: 2, stored_time: 30 });
      expect(noise.end).toBe('OK');
      expect(noise.printed).toContain('trigger off');
      await expect(page.getByTestId('setup-duration')).toHaveValue('30');
      await expect(page.getByTestId('setup-pretrig-arm')).not.toBeChecked();
      await expect(page.getByTestId('setup-pretrig-threshold')).toHaveValue('');

      // A reloaded tab starts from the pushed settings (/config was replaced).
      await page.reload();
      await expect(page.getByTestId('setup-duration')).toHaveValue('30', { timeout: 20000 });
      await expect(page.getByTestId('setup-fs')).toHaveValue('3000');
    });

  test('a push that lands while the tab is still booting wins over the /config it fetched',
    async ({ page }) => {
      // Known state first, from a booted tab.
      await openBooted(page);
      expect((await push({ device_driver: 'mock', fs: 8000, channels: 1, stored_time: 30 })).end).toBe('OK');
      await page.close();

      // A fresh tab fetches /config twice: provider detection, then — with its
      // socket already registered — the prefill. Hold the prefill's reply,
      // read while it still said 30 s, until a push has been applied to this
      // tab; then deliver that stale reply. Without the tab remembering the
      // push, the stale prefill would put Setup back on 30 s.
      const tab = await page.context().newPage();
      let n = 0;
      let pushed: { end: string; printed: string } | null = null;
      await tab.route('**/config', async (route) => {
        n += 1;
        if (n !== 2) { await route.continue(); return; }
        const stale = await route.fetch();
        pushed = await push({ device_driver: 'mock', fs: 3000, channels: 2, stored_time: 7 });
        await route.fulfill({ response: stale });
      });
      await tab.goto(`${ORIGIN}/`);
      await expect(tab.getByRole('combobox', { name: 'input device' }))
        .toContainText('Mock signal generator', { timeout: 20000 });
      await expect.poll(() => pushed?.printed ?? '').toContain('(applied in 1 app tab)');
      await expect(tab.getByTestId('setup-duration')).toHaveValue('7');
      await expect(tab.getByTestId('setup-fs')).toHaveValue('3000');
      await tab.close();
    });

  test('the window / TF averaging defaults reach the next capture', async ({ page }) => {
    await openBooted(page);
    const res = await push({ device_driver: 'mock', fs: 8000, channels: 2, stored_time: 0.5 },
      { window: null, tf_averaging: 'across' });
    expect(res.end).toBe('OK');
    expect(res.printed).toContain('window none, TF averaging across');

    await ribbon(page).getByRole('button', { name: 'Acquire' }).click();
    await page.getByTestId('log-btn').click();
    await expect(ribbon(page).getByRole('button', { name: 'Time' })).toHaveClass(/active/, { timeout: 20000 });

    await ribbon(page).getByRole('button', { name: 'Frequency' }).click();
    await expect(page.getByRole('combobox', { name: 'window' })).toHaveValue('none');
    await ribbon(page).getByRole('button', { name: 'TF', exact: true }).click();
    await expect(page.getByRole('combobox', { name: 'window' })).toHaveValue('none');
    await expect(page.getByRole('combobox', { name: 'averaging' })).toHaveValue('across');
  });

  test('a push while the tab is armed and waiting is refused and changes nothing', async ({ page }) => {
    await openBooted(page);
    // Armed far above anything the mock produces: the capture waits.
    expect((await push({ device_driver: 'mock', fs: 8000, channels: 1, stored_time: 1,
      pretrig_samples: 50, pretrig_threshold: 1000, pretrig_timeout: 30 })).end).toBe('OK');
    await ribbon(page).getByRole('button', { name: 'Acquire' }).click();
    await page.getByTestId('log-btn').click();
    await expect(page.getByTestId('cancel-btn')).toBeVisible();

    const refused = await push({ device_driver: 'mock', fs: 3000, channels: 2, stored_time: 30 });
    expect(refused.end).toBe('ERR RuntimeError a capture is in progress in the app (logging, or armed and '
      + 'waiting for its trigger), so nothing was changed. Let it finish or press Stop, then run this again.');
    await page.getByTestId('cancel-btn').click();

    await ribbon(page).getByRole('button', { name: 'Setup' }).click();
    await expect(page.getByTestId('setup-fs')).toHaveValue('8000');
    await expect(page.getByTestId('setup-pretrig-arm')).toBeChecked();
  });
});
