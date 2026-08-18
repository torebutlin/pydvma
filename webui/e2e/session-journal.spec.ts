import { expect, test, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Session-journal e2e (stage 3): the WHOLE restore flow through a REAL
 * `pydvma-serve` serving the REAL built `webui/dist` — capture, analysis,
 * tab close, reopen, restore.
 *
 * This also closes a long-standing coverage gap recorded in TODO.md: until
 * now NO spec drove the REAL APP's calc path over the native `/engine`
 * socket. `engine-native.spec.ts` drives the socket through the
 * `EngineProbe` self-test (`?engine=1`), which is deliberately a
 * store-level harness, and every other analysis spec runs the in-browser
 * pyodide worker. The FFT in the first test below is the app's own
 * `actions.calcFft` — clicked in the real UI, on a set captured by a real
 * bridge log — resolving the native engine BY DEFAULT (served origin, no
 * `?enginehost=` param) and returning a drawn line.
 *
 * SKIPPED unless `BRIDGE_E2E` is set (needs pydvma + websockets + a built
 * `webui/dist`). Run:
 *
 *     BRIDGE_E2E=1 npx playwright test e2e/session-journal.spec.ts --workers=1
 *
 * Structure: every test gets its OWN freshly spawned serve and its own
 * scratch `--session-dir` (`withServe` below). That is not tidiness — the
 * journal is server-state, so a shared server would leak test 1's posted
 * document into test 2's "nothing was posted yet" premise, and the crash-
 * recovery offer is only ever raised at a server's START, from a spill file
 * that has to be in place before it boots.
 *
 * Repo gotchas honoured: Playwright only from `webui/`; SVG plot lines have
 * a zero-height bbox and fail `toBeVisible`, so line assertions use
 * `toBeAttached`.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// This file's port claim — the full cross-spec register lives in the
// `PORT` comment in engine-native.spec.ts (8763/8764 bridge, 8765 bla,
// 8766 engine-native, 8767 here). Only ONE serve is alive at a time here:
// `withServe` spawns and kills per test, and Playwright runs a file's tests
// sequentially in one worker.
const PORT = Number(process.env.JOURNAL_PORT ?? 8767);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST_DIR = path.join(REPO_ROOT, 'webui', 'dist');
// A checked-in, real `.dvma` (the same one files.spec.ts loads) used as a
// previous run's spill file in the crash-recovery tests. It has to be a REAL
// container, not a `PK`-prefixed stub: serve's adoption scan only checks the
// magic, but the app's Restore actually PARSES the bytes.
const FIXTURE_DVMA = fileURLToPath(new URL('../tests/fixtures/impulse.dvma', import.meta.url));
// The port a seeded spill file CLAIMS to come from. Recovery adoption only
// offers a file whose port is dead (a live one belongs to a running serve),
// so this must be a port nothing binds — deliberately outside the 8763-8767
// block every bridge-flavoured spec spawns into.
const DEAD_SPILL_PORT = 8759;

/** A spawned `pydvma serve` plus its last lines of stdout+stderr. */
interface Serve {
  proc: ChildProcessWithoutNullStreams;
  output: string[];
}

const MAX_OUTPUT_LINES = 50;

/** Poll the loopback TCP port until the server accepts a connection. */
function waitForPort(port: number, output: string[], timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() > deadline) {
          // Self-reporting, as in engine-native.spec.ts: a missing
          // `websockets`, the wrong PYDVMA_PYTHON or a port collision all
          // explain themselves in the server's own output.
          const tail = output.length ? output.join('\n') : '(no server output captured)';
          reject(new Error(`serve port ${port} never opened. serve output:\n${tail}`));
        } else {
          setTimeout(attempt, 200);
        }
      });
    };
    attempt();
  });
}

/** Whether anything is currently listening on a loopback port. */
function portIsLive(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = net.connect(port, '127.0.0.1');
    sock.once('connect', () => { sock.destroy(); resolve(true); });
    sock.once('error', () => { sock.destroy(); resolve(false); });
  });
}

/** Spawn `pydvma serve --driver mock` on `port`, serving the built dist. */
async function startServe(port: number, sessionDir: string): Promise<Serve> {
  const output: string[] = [];
  const proc = spawn(PYTHON, [
    '-m', 'pydvma.serve', '--driver', 'mock', '--port', String(port),
    '--session-dir', sessionDir,
  ], { cwd: REPO_ROOT, stdio: 'pipe' });
  const ingest = (chunk: Buffer | string) => {
    for (const line of chunk.toString().split('\n')) {
      if (!line) continue;
      output.push(line);
      if (output.length > MAX_OUTPUT_LINES) output.shift();
    }
  };
  proc.stdout.on('data', ingest);
  proc.stderr.on('data', ingest);
  await waitForPort(port, output);
  return { proc, output };
}

/** SIGINT the server and give it a moment to release the port. */
async function stopServe(serve: Serve | undefined): Promise<void> {
  if (!serve) return;
  serve.proc.kill('SIGINT');
  await new Promise((r) => setTimeout(r, 300));
}

/**
 * Run `body` against a freshly spawned serve with an empty scratch session
 * dir, tearing both down afterwards (including on failure).
 *
 * `seedSpillFrom` writes a previous run's spill file into the session dir
 * BEFORE the server starts — the only moment recovery adoption looks, so it
 * cannot be done from inside the body.
 */
async function withServe(
  body: (ctx: { sessionDir: string; spillPath: string }) => Promise<void>,
  opts: { seedSpillFrom?: string } = {},
): Promise<void> {
  const sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-e2e-journal-'));
  if (opts.seedSpillFrom) {
    fs.copyFileSync(
      opts.seedSpillFrom,
      path.join(sessionDir, `pydvma-session-${DEAD_SPILL_PORT}.dvma`),
    );
  }
  let serve: Serve | undefined;
  try {
    serve = await startServe(PORT, sessionDir);
    await body({
      sessionDir,
      // Where THIS server mirrors its posted document — an observable that
      // says "a journal_set actually landed", used instead of sleeping out
      // the app's 2 s autosave debounce.
      spillPath: path.join(sessionDir, `pydvma-session-${PORT}.dvma`),
    });
  } finally {
    await stopServe(serve);
    fs.rmSync(sessionDir, { recursive: true, force: true });
  }
}

/** Collect this page's console text, for the native-engine greeting wait. */
function collectConsole(page: Page): string[] {
  const lines: string[] = [];
  page.on('console', (m) => lines.push(m.text()));
  return lines;
}

const ribbon = (page: Page) => page.getByRole('navigation', { name: 'stages' });

/**
 * Open the served app and wait until the NATIVE engine has greeted —
 * `socketClient`'s `[engine-socket] native engine: pydvma <version>` info
 * line, the same signal engine-native.spec.ts waits on (it reads it through
 * the probe's `data-engine-host`, which is unavailable here: `?engine=1`
 * deliberately suppresses the journal offer, so this spec must not use it).
 *
 * Waiting for it matters beyond documentation: the journal offer is gated on
 * engine resolution, so a session that fell back to pyodide would raise no
 * journal toast at all and the failure would read as "no offer" rather than
 * "no native engine".
 */
async function openApp(page: Page): Promise<void> {
  const consoleLines = collectConsole(page);
  await page.goto(`${ORIGIN}/`);
  await expect
    .poll(() => consoleLines.some((l) => l.includes('[engine-socket] native engine: pydvma')),
          { timeout: 60_000 })
    .toBe(true);
}

/** Setup → mock device, short capture → Acquire → Log Data → one tray card. */
async function logOnce(page: Page): Promise<void> {
  await expect(ribbon(page).getByRole('button', { name: 'Setup' }))
    .not.toHaveClass(/gated/, { timeout: 20000 });
  await ribbon(page).getByRole('button', { name: 'Setup' }).click();
  const deviceSelect = page.getByRole('combobox', { name: 'input device' });
  await expect(deviceSelect).toContainText('Mock signal generator');
  await deviceSelect.selectOption({ label: 'Mock signal generator' });
  await page.getByRole('combobox', { name: 'duration' }).selectOption('0.5');
  await ribbon(page).getByRole('button', { name: 'Acquire' }).click();
  await page.getByTestId('log-btn').click();
  await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 20000 });
}

const journalToast = (page: Page) =>
  page.getByTestId('toast').filter({ hasText: 'Restore session from pydvma-serve?' });
const recoveryToast = (page: Page) =>
  page.getByTestId('toast').filter({ hasText: 'Recover session from a previous pydvma-serve run?' });
const idbToast = (page: Page) =>
  page.getByTestId('toast').filter({ hasText: 'Restore last session?' });

test.describe('pydvma-serve session journal', () => {
  test.skip(!BRIDGE_E2E,
    'set BRIDGE_E2E=1 (needs pydvma + websockets + a built webui/dist; spawns python3 -m pydvma.serve)');
  // Each test spawns a server, boots the app, runs a real capture and a real
  // engine round-trip — well past Playwright's 30 s default.
  test.setTimeout(180_000);

  test.beforeAll(() => {
    if (!BRIDGE_E2E) return;
    if (!fs.existsSync(path.join(DIST_DIR, 'index.html'))) {
      throw new Error(`webui/dist not built (${DIST_DIR}); run \`npm run build\` first`);
    }
  });

  test('capture + FFT, tab close, reopen → the journal offers the session back', async ({ page, context }) => {
    await withServe(async ({ spillPath }) => {
      await openApp(page);

      // ---- capture, through the real bridge ----
      await logOnce(page);
      await expect(page.getByTestId('plot-line').first()).toBeAttached();

      // ---- analysis, through the real /engine socket ----
      // The TODO gap this spec closes: this is the APP's own calc action
      // (FrequencyCard -> actions.calcFft), not a probe harness, running on
      // the native engine because the page is SERVED by pydvma-serve.
      await ribbon(page).getByRole('button', { name: 'Frequency' }).click();
      await expect(page.getByTestId('plot-line')).toHaveCount(0);   // nothing computed yet
      await page.getByRole('button', { name: 'Calc FFT' }).click();
      await expect(page.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });

      // ---- the autosave reaching the journal ----
      // The server mirrors every posted document to its spill file, so that
      // file appearing IS a journal_set landing — a real observable, used
      // instead of sleeping out the app's 2 s autosave debounce.
      await expect.poll(() => (fs.existsSync(spillPath) ? fs.statSync(spillPath).size : 0),
                        { timeout: 30_000 }).toBeGreaterThan(0);

      // ---- close the tab, reopen the app ----
      await page.close();
      const reopened = await context.newPage();
      await openApp(reopened);

      // The journal answers first: its offer is up, and the IndexedDB offer
      // ("Restore last session?" — page A autosaved there too, so it WOULD
      // have fired) never appears, because a raised journal offer returns
      // before `bootFileRestore` ever reads IndexedDB.
      await expect(journalToast(reopened)).toBeVisible({ timeout: 60_000 });
      await expect(idbToast(reopened)).toHaveCount(0);

      await journalToast(reopened).getByRole('button', { name: 'Restore' }).click();

      // The captured set is back, drawn on the Time view it focuses.
      await expect(reopened.getByTestId('tray-card-0')).toBeVisible();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached();

      // The SPECTRUM is deliberately NOT asserted here: it is a DERIVED
      // array (`actions.setDerived`), not a dataset item, so it is outside
      // the session document `writeDvma` serialises and is recomputed from
      // the restored time data on demand — the same as the IndexedDB
      // restore path. What IS asserted is that the restored set can be
      // re-analysed over the same socket, which is the useful half.
      await ribbon(reopened).getByRole('button', { name: 'Frequency' }).click();
      await reopened.getByRole('button', { name: 'Calc FFT' }).click();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });
    });
  });

  test('a capture is journalled at BIRTH — a tab closed inside the autosave debounce loses nothing', async ({ page, context }) => {
    await withServe(async ({ spillPath }) => {
      await openApp(page);
      await logOnce(page);
      // Close immediately: the app's autosave is debounced by 2 s and the
      // tray card lands within ~100 ms of `log_result`, so nothing has been
      // posted. Deterministic server-side regardless of that margin —
      // `_Connection._on_log` calls `journal.add_capture` BEFORE it sends
      // `log_result`, so the capture is registered before the client can
      // even know the log finished.
      await page.close();

      // The proof the offer below can ONLY come from the capture: no
      // document was ever posted, so the server never wrote a spill file.
      expect(fs.existsSync(spillPath)).toBe(false);

      const reopened = await context.newPage();
      await openApp(reopened);
      await expect(journalToast(reopened)).toBeVisible({ timeout: 60_000 });
      await journalToast(reopened).getByRole('button', { name: 'Restore' }).click();

      await expect(reopened.getByTestId('tray-card-0')).toBeVisible();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached();
    });
  });

  test('a previous run\'s spill file is offered for crash recovery and restores', async ({ page }) => {
    expect(await portIsLive(DEAD_SPILL_PORT),
           `port ${DEAD_SPILL_PORT} must be free: recovery only adopts a spill file whose port is dead`)
      .toBe(false);
    await withServe(async () => {
      await openApp(page);
      // No live journal (fresh server, nothing logged), so the adopted
      // previous-run document is what gets offered.
      await expect(recoveryToast(page)).toBeVisible({ timeout: 60_000 });
      await expect(journalToast(page)).toHaveCount(0);
      await recoveryToast(page).getByRole('button', { name: 'Restore' }).click();

      await expect(page.getByTestId('tray-card-0')).toBeVisible();
      await expect(page.getByTestId('plot-line').first()).toBeAttached();
    }, { seedSpillFrom: FIXTURE_DVMA });
  });

  test('dismissing the crash-recovery offer deletes the spill file', async ({ page }) => {
    await withServe(async ({ sessionDir }) => {
      const seeded = path.join(sessionDir, `pydvma-session-${DEAD_SPILL_PORT}.dvma`);
      expect(fs.existsSync(seeded)).toBe(true);

      await openApp(page);
      await expect(recoveryToast(page)).toBeVisible({ timeout: 60_000 });
      await recoveryToast(page).getByRole('button', { name: 'Dismiss' }).click();

      // Dismiss is server-side here (unlike the live-journal offer's, which
      // is a no-op): `journal_discard_recovered` drops the offer AND unlinks
      // the file, so it is never offered again.
      await expect.poll(() => fs.existsSync(seeded), { timeout: 15_000 }).toBe(false);
    }, { seedSpillFrom: FIXTURE_DVMA });
  });
});
