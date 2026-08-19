import { expect, test, type Download, type Page } from '@playwright/test';
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Derived-data save e2e (2026-08-19 round): Save Dataset materialising the
 * app's COMPUTED analysis views into real `.dvma` items, through a REAL
 * `pydvma-serve` serving the REAL built `webui/dist`.
 *
 * What only an end-to-end run can prove, and each test proves one of:
 *
 *  1. **The round trip.** Capture → Calc FFT + TF → Save → a FRESH page →
 *     Load → the Frequency and TF views draw WITHOUT anyone pressing Calc.
 *     The file is additionally read back BY PYTHON (`container.load`), so the
 *     cross-language claim — the browser wrote items pydvma understands — is
 *     checked against the actual reader rather than asserted.
 *  2. **The stale chain.** A file whose time data was edited AFTER the
 *     spectrum was stamped (done here exactly as the lab would: the app saves
 *     it, python edits it) loads with the ⚠ badge up; clicking it rederives
 *     and the badge goes.
 *  3. **The subset picker.** Two captures, "Choose sets…", one unticked →
 *     the file holds exactly one measurement. Plus the target-hop rule: a
 *     picker opened on a DIFFERENT split control starts all-ticked again.
 *  4. **The sonogram prompt.** No sonogram computed ⇒ no dialog at all; one
 *     computed ⇒ the dialog, and "This channel" stores a real `SonoData` that
 *     seeds the sono view on reload; a second Save of the unchanged session
 *     does NOT ask again (the freshness gate).
 *
 * SKIPPED unless `BRIDGE_E2E` is set (needs pydvma + websockets + a built
 * `webui/dist`). Run:
 *
 *     BRIDGE_E2E=1 npx playwright test e2e/derived-save.spec.ts --workers=1
 *
 * Structure copied from `session-journal.spec.ts`, including its hardened
 * teardown (module-scoped live server so an `afterEach` can reach it, an exit
 * barrier before the port is rebound): every test gets its OWN serve and its
 * own scratch `--session-dir`, because the server owns session state and a
 * shared one would leak one test's document into the next test's premise.
 *
 * Repo gotchas honoured: Playwright only from `webui/`; SVG plot lines have a
 * zero-height bbox and fail `toBeVisible`, so line assertions use
 * `toBeAttached`.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// See bridge.spec.ts: `python3` is the MS-Store stub on Windows.
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// This file's port claim — the full cross-spec register lives in the `PORT`
// comment in engine-native.spec.ts (8763/8764 bridge, 8765 bla, 8766
// engine-native, 8767 session-journal, 8768 here). Only ONE serve is alive at
// a time: `withServe` spawns and kills per test, and Playwright runs a file's
// tests sequentially in one worker.
const PORT = Number(process.env.DERIVED_SAVE_PORT ?? 8768);
const ORIGIN = `http://127.0.0.1:${PORT}`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST_DIR = path.join(REPO_ROOT, 'webui', 'dist');

/** A spawned `pydvma serve` plus its last lines of stdout+stderr. */
interface Serve {
  proc: ChildProcessWithoutNullStreams;
  output: string[];
}

const MAX_OUTPUT_LINES = 50;

/**
 * The serve and scratch dir currently owned by this file, tracked at MODULE
 * scope rather than in `withServe`'s closure — see session-journal.spec.ts's
 * `live` docstring for the two silent failure modes that forces (a test
 * TIMEOUT unwinds no `finally`; a rejected `waitForPort` can leave a child
 * nobody holds a reference to, still bound to this file's one port).
 */
let live: Serve | undefined;
let liveDir: string | undefined;

/** Resolve true when `proc` has exited, false if `timeoutMs` elapses first. */
function onceExit(proc: ChildProcessWithoutNullStreams, timeoutMs: number): Promise<boolean> {
  if (proc.exitCode !== null || proc.signalCode !== null) return Promise.resolve(true);
  return new Promise<boolean>((resolve) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let settled = false;
    const finish = (exited: boolean) => {
      if (settled) return;
      settled = true;
      if (timer !== undefined) clearTimeout(timer);
      resolve(exited);
    };
    timer = setTimeout(() => finish(false), timeoutMs);
    proc.once('exit', () => finish(true));
  });
}

/** Poll the loopback TCP port until the server accepts a connection. */
function waitForPort(port: number, output: string[], timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const sock = net.connect(port, '127.0.0.1');
      sock.once('connect', () => { sock.destroy(); resolve(); });
      sock.once('error', () => {
        sock.destroy();
        if (Date.now() > deadline) {
          // Self-reporting: a missing `websockets`, the wrong PYDVMA_PYTHON or
          // a port collision all explain themselves in the server's output.
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
async function startServe(port: number, sessionDir: string): Promise<void> {
  // Bind only once the port is demonstrably FREE, so a straggler from the
  // previous test cannot answer this test's `waitForPort`.
  await expect.poll(() => portIsLive(port), { timeout: 30_000 }).toBe(false);

  const output: string[] = [];
  const proc = spawn(PYTHON, [
    '-m', 'pydvma.serve', '--driver', 'mock', '--port', String(port),
    '--session-dir', sessionDir,
  ], { cwd: REPO_ROOT, stdio: 'pipe' });
  live = { proc, output };            // BEFORE anything that can throw
  const ingest = (chunk: Buffer | string) => {
    for (const line of chunk.toString().split('\n')) {
      if (!line) continue;
      output.push(line);
      if (output.length > MAX_OUTPUT_LINES) output.shift();
    }
  };
  proc.stdout.on('data', ingest);
  proc.stderr.on('data', ingest);
  try {
    await waitForPort(port, output);
  } catch (e) {
    proc.kill('SIGKILL');
    await onceExit(proc, 2000);
    live = undefined;
    throw e;
  }
}

/** Stop the live serve and WAIT for it to exit (this file rebinds the port). */
async function stopServe(): Promise<void> {
  const serve = live;
  live = undefined;
  if (!serve) return;
  const { proc } = serve;
  if (proc.exitCode !== null || proc.signalCode !== null) return;
  proc.kill('SIGINT');
  // Short grace, then SIGKILL: teardown runs while the browser still holds an
  // `/engine` websocket (Playwright disposes the page fixture after our
  // hooks), so an idle-exit assumption would hang here every time.
  if (!(await onceExit(proc, 1500))) {
    proc.kill('SIGKILL');
    await onceExit(proc, 2000);
  }
}

/** Stop any live serve and remove its scratch dir. Idempotent (afterEach net). */
async function teardown(): Promise<void> {
  await stopServe();
  if (liveDir) {
    fs.rmSync(liveDir, { recursive: true, force: true });
    liveDir = undefined;
  }
}

/**
 * Run `body` against a freshly spawned serve with an empty scratch session
 * dir. `outDir` is a scratch directory for the `.dvma` files a test saves and
 * re-loads; it lives inside the session dir so teardown takes it too.
 */
async function withServe(
  body: (ctx: { sessionDir: string; outDir: string }) => Promise<void>,
): Promise<void> {
  const sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-e2e-derived-'));
  liveDir = sessionDir;                       // teardown owns it from here
  const outDir = path.join(sessionDir, 'files');
  fs.mkdirSync(outDir);
  try {
    await startServe(PORT, sessionDir);
    await body({ sessionDir, outDir });
  } finally {
    await teardown();
  }
}

/** Collect this page's console text, for the native-engine greeting wait. */
function collectConsole(page: Page): string[] {
  const lines: string[] = [];
  page.on('console', (m) => lines.push(m.text()));
  return lines;
}

const ribbon = (page: Page) => page.getByRole('navigation', { name: 'stages' });
const journalToast = (page: Page) =>
  page.getByTestId('toast').filter({ hasText: 'Restore session from pydvma-serve?' });
/** The HEADER's Save Dataset (the Export card carries a second one). */
const saveBtn = (page: Page) => page.getByRole('banner').getByRole('button', { name: 'Save Dataset' });

/**
 * Open the served app and wait until the NATIVE engine has greeted — the same
 * `[engine-socket] native engine: pydvma <version>` line session-journal.spec
 * waits on. Beyond documentation: a session that fell back to pyodide would
 * still pass most assertions here but take minutes, and the failure would read
 * as a timeout rather than "no native engine".
 */
async function openApp(page: Page): Promise<void> {
  const consoleLines = collectConsole(page);
  await page.goto(`${ORIGIN}/`);
  await expect
    .poll(() => consoleLines.some((l) => l.includes('[engine-socket] native engine: pydvma')),
          { timeout: 60_000 })
    .toBe(true);
}

/**
 * Open a SECOND page on the same server and clear the journal's restore offer.
 *
 * The offer is unavoidable here and must be answered explicitly: every test
 * captures first, and `pydvma-serve` registers a capture in its journal AT
 * BIRTH, so reopening always raises "Restore session from pydvma-serve?".
 * Dismissing it (client-side only) leaves the page empty, which is the premise
 * every reload assertion below needs — the data must come from the FILE.
 */
async function reopenEmpty(page: Page): Promise<void> {
  await openApp(page);
  await expect(journalToast(page)).toBeVisible({ timeout: 60_000 });
  await journalToast(page).getByRole('button', { name: 'Dismiss' }).click();
  await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(0);
}

/**
 * Setup → mock device, short capture → Acquire → Log Data → one more card.
 *
 * `channels` defaults to the app's own default (1). A transfer function needs
 * at least one response channel BESIDES the input, so any test that computes
 * one has to ask for 2 — the mock recorder then fills channel k with a 100·(k+1)
 * Hz sine, which is distinct content per channel.
 */
async function logOnce(page: Page, opts: { cards?: number; channels?: number } = {}): Promise<void> {
  await expect(ribbon(page).getByRole('button', { name: 'Setup' }))
    .not.toHaveClass(/gated/, { timeout: 20000 });
  await ribbon(page).getByRole('button', { name: 'Setup' }).click();
  const deviceSelect = page.getByRole('combobox', { name: 'input device' });
  await expect(deviceSelect).toContainText('Mock signal generator');
  await deviceSelect.selectOption({ label: 'Mock signal generator' });
  if (opts.channels !== undefined) {
    // `fill` alone only raises `input`; the card commits on `change`, so the
    // value has to be blurred out of the field (bla.spec.ts does the same).
    const chans = page.getByRole('spinbutton', { name: 'channel count' });
    await chans.fill(String(opts.channels));
    await chans.blur();
  }
  await page.getByRole('combobox', { name: 'duration' }).selectOption('0.5');
  await ribbon(page).getByRole('button', { name: 'Acquire' }).click();
  await page.getByTestId('log-btn').click();
  await expect(page.locator('[data-testid^="tray-card-"]'))
    .toHaveCount(opts.cards ?? 1, { timeout: 20000 });
}

/**
 * Fraction of the sonogram heat canvas that carries painted pixels.
 *
 * The canvas element MOUNTS WITH THE VIEW, empty, so `toBeVisible` says
 * nothing about whether a sonogram has been computed — waiting on visibility
 * alone and then saving raced the calc and found no sonogram to offer (the
 * first cut of this spec did exactly that). Reading the backing store is the
 * honest "the result has landed" signal, and it is the same probe
 * analysis.spec.ts uses.
 */
function sonoPaintFrac(page: Page): Promise<number> {
  return page.evaluate(() => {
    const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement | null;
    if (!c) return 0;
    const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let painted = 0;
    for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
    return painted / (c.width * c.height);
  });
}

/** Click Load Data and answer the fallback file chooser with `file`. */
async function loadViaFallback(page: Page, file: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(file);
}

/**
 * Answer the ONE `window.prompt` the save handler raises for the filename.
 *
 * Playwright's default dialog handling DISMISSES, which returns null and makes
 * `onsave` return before it writes anything — a save armed without this fails
 * as a download that never arrives, with nothing on screen to explain it.
 */
function armSaveName(page: Page, name: string): void {
  page.once('dialog', (d) => { void d.accept(name); });
}

/**
 * Run one Save to `dest`: arm the name prompt, click (the header button by
 * default), optionally answer a mid-flight dialog, and keep the download.
 *
 * `midway` runs BETWEEN the click and the download landing — the only place
 * the "Include sonogram data?" dialog can be answered, since the save awaits
 * that answer before it serialises anything.
 */
async function saveDataset(
  page: Page,
  dest: string,
  opts: { click?: () => Promise<void>; midway?: (dl: Promise<Download>) => Promise<void> } = {},
): Promise<void> {
  armSaveName(page, path.basename(dest));
  const dl = page.waitForEvent('download', { timeout: 180_000 });
  await (opts.click ?? (() => saveBtn(page).click()))();
  if (opts.midway) await opts.midway(dl);
  await (await dl).saveAs(dest);
  expect(fs.statSync(dest).size).toBeGreaterThan(0);
}

/** What `pydvma.container.load` finds in a `.dvma` the browser wrote. */
interface DvmaSummary {
  time: number;
  freq: number;
  tf: number;
  sono: number;
  /** `source_signature` of each FreqData, or null when unstamped. */
  freq_sig: (string | null)[];
  /**
   * The same signature RECOMPUTED by `pydvma._signature` from the linked
   * TimeData's samples — the cross-language check: equal means Python's hash
   * of the source agrees with the browser's, digit for digit.
   */
  freq_sig_recomputed: (string | null)[];
  /** `source_settings['calc']` of each TfData (the provenance discriminator). */
  tf_calc: (string | null)[];
  /** Shape of each stored sonogram cube: (n_freq, n_frames, n_channels). */
  sono_shape: number[][];
}

/**
 * Read a saved `.dvma` back WITH PYTHON and report what pydvma sees in it.
 *
 * The point is the reader, not the convenience: everything under test here is
 * written by the browser, and "the container round-trips" is only a claim
 * until the OTHER language's loader agrees. Synchronous by design — these are
 * sub-second, and an await here would interleave with page work for nothing.
 */
function inspectDvma(file: string): DvmaSummary {
  const script = `
import json, sys
from pydvma import container, _signature

d = container.load(sys.argv[1])
# Keyed by STRING: a browser-authored item's id_link and the capture's own
# unique_id are the same identifier but need not be the same python type
# (uuid.UUID vs str, depending on which side minted it).
by_id = {str(getattr(t, 'unique_id', None)): t for t in d.time_data_list}

def recomputed(item):
    src = by_id.get(str(getattr(item, 'id_link', None)))
    return None if src is None else _signature.source_signature(src)

print(json.dumps({
    'time': len(d.time_data_list),
    'freq': len(d.freq_data_list),
    'tf': len(d.tf_data_list),
    'sono': len(d.sono_data_list),
    'freq_sig': [getattr(x, 'source_signature', None) for x in d.freq_data_list],
    'freq_sig_recomputed': [recomputed(x) for x in d.freq_data_list],
    'tf_calc': [(getattr(x, 'source_settings', None) or {}).get('calc') for x in d.tf_data_list],
    'sono_shape': [list(x.sono_data.shape) for x in d.sono_data_list],
}))
`;
  const res = spawnSync(PYTHON, ['-c', script, file], { cwd: REPO_ROOT, encoding: 'utf8' });
  if (res.status !== 0) {
    throw new Error(`python could not read ${file}:\n${res.stdout}\n${res.stderr}`);
  }
  return JSON.parse(res.stdout) as DvmaSummary;
}

/**
 * Copy `src` to `dst`, scaling its first measurement's samples — "someone
 * edited the time data in a notebook after the spectrum was computed".
 *
 * Done in PYTHON on purpose: it is the real lab path (pull → edit → save /
 * push), it leaves the FreqData's stamped `source_signature` untouched exactly
 * as an outside edit would, and it exercises the container's lossless
 * round-trip of browser-authored keys on the way through.
 */
function editSourceSamples(src: string, dst: string): void {
  const script = `
import sys
from pydvma import container
d = container.load(sys.argv[1])
td = d.time_data_list[0]
td.time_data = td.time_data * 2.0
container.save(d, sys.argv[2])
`;
  const res = spawnSync(PYTHON, ['-c', script, src, dst], { cwd: REPO_ROOT, encoding: 'utf8' });
  if (res.status !== 0) {
    throw new Error(`python could not edit ${src}:\n${res.stdout}\n${res.stderr}`);
  }
}

test.describe('derived-data save', () => {
  test.skip(!BRIDGE_E2E,
    'set BRIDGE_E2E=1 (needs pydvma + websockets + a built webui/dist; spawns python3 -m pydvma.serve)');
  // Each test spawns a server, boots the app, runs a real capture and several
  // real engine round-trips — well past Playwright's 30 s default.
  test.setTimeout(240_000);

  test.beforeAll(() => {
    if (!BRIDGE_E2E) return;
    if (!fs.existsSync(path.join(DIST_DIR, 'index.html'))) {
      throw new Error(`webui/dist not built (${DIST_DIR}); run \`npm run build\` first`);
    }
  });

  // The teardown net: `withServe`'s own `finally` handles a failing assertion,
  // but a test TIMEOUT unwinds nothing, and a leaked serve holds PORT.
  test.afterEach(teardown);

  test('Save materialises FFT + TF; a fresh load draws both with no recompute', async ({ page, context }) => {
    await withServe(async ({ outDir }) => {
      await openApp(page);
      await logOnce(page, { channels: 2 });      // 2 ch: a TF needs a response

      // ---- compute both views over the real /engine socket ----
      await ribbon(page).getByRole('button', { name: 'Frequency' }).click();
      await page.getByRole('button', { name: 'Calc FFT' }).click();
      await expect(page.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });
      await ribbon(page).getByRole('button', { name: 'TF' }).click();
      await page.getByRole('button', { name: 'Calc TF' }).click();
      await expect(page.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });

      const file = path.join(outDir, 'derived.dvma');
      await saveDataset(page, file);
      // No sonogram was computed, so the include prompt must never have
      // appeared — the download landing at all already proves it (the save
      // awaits that dialog), and this says so explicitly.
      await expect(page.getByTestId('sono-include-overlay')).toHaveCount(0);

      // ---- pydvma's own reader agrees the items are there and stamped ----
      const summary = inspectDvma(file);
      expect(summary).toMatchObject({ time: 1, freq: 1, tf: 1, sono: 0 });
      expect(summary.freq_sig[0]).toMatch(/^[0-9a-f]{16}$/);   // FNV-1a-64 hex
      expect(summary.tf_calc).toEqual(['tf']);
      // The cross-language pin, on a real file rather than a fixed vector:
      // `pydvma._signature` rehashes the stored samples and reaches the same
      // 16 hex digits the browser stamped. If the two implementations ever
      // diverge — a stride rule, a byte order, the fs tail — this fails.
      expect(summary.freq_sig_recomputed[0]).toBe(summary.freq_sig[0]);

      // ---- fresh page, load the file, and DO NOT press Calc ----
      await page.close();
      const reopened = await context.newPage();
      await reopenEmpty(reopened);
      await loadViaFallback(reopened, file);
      await expect(reopened.locator('[data-testid^="tray-card-"]')).toHaveCount(1);

      // Both analysis views draw straight off the file. The Calc buttons are
      // deliberately untouched: these lines exist because the document now
      // CARRIES the results, which is the whole feature.
      await ribbon(reopened).getByRole('button', { name: 'Frequency' }).click();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached({ timeout: 20_000 });
      await ribbon(reopened).getByRole('button', { name: 'TF' }).click();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached({ timeout: 20_000 });

      // …and the chain is INTACT: nothing edited the source, so no badge.
      await expect(reopened.getByTestId('stale-chain-badge')).toHaveCount(0);
    });
  });

  test('a source edited after stamping loads flagged; the badge rederives it', async ({ page, context }) => {
    await withServe(async ({ outDir }) => {
      await openApp(page);
      await logOnce(page);
      await ribbon(page).getByRole('button', { name: 'Frequency' }).click();
      await page.getByRole('button', { name: 'Calc FFT' }).click();
      await expect(page.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });

      const saved = path.join(outDir, 'intact.dvma');
      await saveDataset(page, saved);

      // The edit that breaks the chain, made OUTSIDE the app (see the helper).
      const edited = path.join(outDir, 'edited.dvma');
      editSourceSamples(saved, edited);
      const before = inspectDvma(saved);
      const after = inspectDvma(edited);
      // The stamp survived the edit untouched — that is precisely why it can
      // catch it — while the samples it names now hash to something else.
      expect(before.freq_sig_recomputed[0]).toBe(before.freq_sig[0]);  // intact
      expect(after.freq_sig[0]).toBe(before.freq_sig[0]);              // stamp kept
      expect(after.freq_sig_recomputed[0]).not.toBe(after.freq_sig[0]);

      await page.close();
      const reopened = await context.newPage();
      await reopenEmpty(reopened);
      await loadViaFallback(reopened, edited);
      await expect(reopened.locator('[data-testid^="tray-card-"]')).toHaveCount(1);

      // Flagged on load: the stored spectrum was computed from samples this
      // file no longer contains.
      const badge = reopened.getByTestId('stale-chain-badge');
      await expect(badge).toBeVisible();

      // Clicking it reruns exactly the flagged kind through the engine; the
      // flag clears on the fresh compute (not on the next save).
      await badge.click();
      await expect(badge).toHaveCount(0, { timeout: 60_000 });
      await ribbon(reopened).getByRole('button', { name: 'Frequency' }).click();
      await expect(reopened.getByTestId('plot-line').first()).toBeAttached({ timeout: 60_000 });
    });
  });

  test('Choose sets… saves one measurement; each picker target starts all-ticked', async ({ page, context }) => {
    await withServe(async ({ outDir }) => {
      await openApp(page);
      await logOnce(page);
      await logOnce(page, { cards: 2 });          // two independent measurements

      await ribbon(page).getByRole('button', { name: 'Export' }).click();
      const popover = page.getByTestId('choose-sets-popover');

      // ---- the target-hop rule (Task 5's review find) ----
      // Open Save's picker, untick a row, then jump STRAIGHT to another split
      // control's picker without closing: `pick` never goes falsy, so without
      // the `{#key pick}` remount the same instance (and its ticks) would be
      // reused and "all ticked on every open" would quietly be a lie.
      await page.getByRole('button', { name: 'Choose sets to save' }).click();
      await expect(popover).toContainText('Save Dataset');
      await popover.getByTestId('choose-set-0').getByRole('checkbox').uncheck();
      await page.getByRole('button', { name: 'Choose sets to export as Matlab' }).click();
      await expect(popover).toContainText('Export Matlab');
      await expect(popover.getByTestId('choose-set-0').getByRole('checkbox')).toBeChecked();
      await expect(popover.getByTestId('choose-set-1').getByRole('checkbox')).toBeChecked();
      await popover.getByTestId('choose-sets-cancel').click();
      await expect(popover).toHaveCount(0);

      // ---- the subset save itself: keep the SECOND measurement only ----
      const file = path.join(outDir, 'subset.dvma');
      await saveDataset(page, file, {
        click: async () => {
          await page.getByRole('button', { name: 'Choose sets to save' }).click();
          await popover.getByTestId('choose-set-0').getByRole('checkbox').uncheck();
          await popover.getByTestId('choose-sets-ok').click();
        },
      });
      expect(inspectDvma(file)).toMatchObject({ time: 1 });

      await page.close();
      const reopened = await context.newPage();
      await reopenEmpty(reopened);
      await loadViaFallback(reopened, file);
      await expect(reopened.locator('[data-testid^="tray-card-"]')).toHaveCount(1);
    });
  });

  test('the sonogram prompt: absent with none computed, stores This channel, never re-asked when fresh', async ({ page, context }) => {
    await withServe(async ({ outDir }) => {
      await openApp(page);
      await logOnce(page);

      // ---- (a) nothing computed → no prompt, and no SonoData in the file ----
      const noSono = path.join(outDir, 'no-sono.dvma');
      await saveDataset(page, noSono);
      await expect(page.getByTestId('sono-include-overlay')).toHaveCount(0);
      expect(inspectDvma(noSono).sono).toBe(0);

      // ---- (b) compute one → the prompt appears → "This channel" ----
      await ribbon(page).getByRole('button', { name: 'Sonogram' }).click();
      await page.getByRole('button', { name: 'Calc Sonogram' }).click();
      // PAINTED, not merely mounted — see `sonoPaintFrac`. Saving before the
      // calc lands means there is no sonogram to offer and no prompt.
      await expect.poll(() => sonoPaintFrac(page), { timeout: 120_000 }).toBeGreaterThan(0.9);

      const withSono = path.join(outDir, 'with-sono.dvma');
      await saveDataset(page, withSono, {
        midway: async () => {
          await expect(page.getByTestId('sono-include-overlay')).toBeVisible({ timeout: 30_000 });
          await page.getByTestId('sono-include-channel').click();
        },
      });
      // One stored plane: "This channel" saves the channel on screen, not the
      // whole cube (the single-channel cost fix — see the round doc).
      const stored = inspectDvma(withSono);
      expect(stored.sono).toBe(1);
      expect(stored.sono_shape[0][2]).toBe(1);

      // ---- (c) save again, nothing changed → the freshness gate holds ----
      const again = path.join(outDir, 'again.dvma');
      await saveDataset(page, again);
      await expect(page.getByTestId('sono-include-overlay')).toHaveCount(0);
      expect(inspectDvma(again).sono).toBe(1);   // still stored, not re-derived

      // ---- (d) reload: the sono view seeds from the stored cube ----
      await page.close();
      const reopened = await context.newPage();
      await reopenEmpty(reopened);
      await loadViaFallback(reopened, withSono);
      await expect(reopened.locator('[data-testid^="tray-card-"]')).toHaveCount(1);
      await ribbon(reopened).getByRole('button', { name: 'Sonogram' }).click();

      // Painted WITHOUT pressing Calc Sonogram, read from the heat canvas's own
      // backing store — the canvas mounts with the view and would be "visible"
      // while still blank.
      await expect(reopened.getByTestId('sono-canvas')).toBeVisible({ timeout: 20_000 });
      await expect.poll(() => sonoPaintFrac(reopened), { timeout: 30_000 }).toBeGreaterThan(0.9);
    });
  });
});
