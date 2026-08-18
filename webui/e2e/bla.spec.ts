import { expect, test, type Page } from '@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Schoukens BLA ("Nonlin" stage) e2e — Task 10.
 *
 * Two halves, deliberately split by what each capture path can actually
 * prove:
 *
 *  - **bridge half** (`BRIDGE_E2E=1`, its own spawned `pydvma.serve --driver
 *    mock`) — the FULL pipeline: design → M x n_exc bridge captures with a
 *    multisine stimulus → `calc_bla` in the real pyodide engine → BLA sets in
 *    the tray, both σ-overlay TOGGLES (TF card + the in-stage BLA card one)
 *    reachable and functional. The mock driver's data is a deterministic
 *    per-channel sine, NOT the multisine that was played, so every NUMBER
 *    the run produces is meaningless — EXCEPT the σ overlay's PRESENCE,
 *    which turns out to be a genuine (if accidental) exercise of both halves
 *    of the zero-floor fix: `MockRecorder` regenerates its buffer from
 *    sample 0 on every capture (`streams.py`), so it is bit-identical across
 *    the M realisations ⇒ realisation scatter is EXACTLY 0 ⇒ σ_NL floors to
 *    0 and correctly draws NOTHING. But the mock's fixed per-channel tone
 *    (`100·(ch+1)` Hz) is not period-locked to the design's N-sample period,
 *    so the P period-slices WITHIN one capture are genuinely NOT identical
 *    ⇒ σ_n (period-to-period scatter) is honestly non-zero and DOES draw.
 *    See the comment at the assertion for the verified count. The
 *    exhaustive proof that σ data draws (and gaps) correctly under
 *    controlled numbers lives in `tests/plot/model.test.ts`, which can
 *    hand-craft arrays a deterministic mock never will.
 *  - **browser half** (default project, fake media device) — the UI truths
 *    that need no real audio. A full run on this path would capture the fake
 *    mic's tone, i.e. silence as far as the excitation is concerned, so the
 *    run itself is NOT driven here (see the comment on that describe block).
 *
 * Repo gotchas honoured: SVG plot lines have a zero-height bbox and fail
 * `toBeVisible`, so line assertions use `toBeAttached`/`toHaveCount` on the
 * path attributes instead; Playwright must be run from `webui/`.
 */

const BRIDGE_E2E = !!process.env.BRIDGE_E2E;
// Interpreter for the spawned server — same override bridge.spec.ts uses
// (bare `python3` is the Microsoft Store stub on Windows).
const PYTHON = process.env.PYDVMA_PYTHON ?? 'python3';
// A port of its own: bridge.spec.ts owns 8763/8764 and Playwright runs spec
// files in parallel workers, so sharing one would race.
const PORT = Number(process.env.BLA_BRIDGE_PORT ?? 8765);
const WS_URL = `ws://127.0.0.1:${PORT}/ws`;
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

let server: ChildProcessWithoutNullStreams | undefined;
// Scratch session dir for the spawned serve (`--session-dir`). Hermeticity:
// without it, every e2e run leaves a real, PK-valid `pydvma-session-*.dvma`
// in the SYSTEM temp dir, which a later REAL `pydvma-serve` would adopt and
// offer the user as "Recover session from a previous pydvma-serve run?" —
// and, in the other direction, a stray file from an earlier real serve would
// raise that recovery toast over this spec's own clicks. Created in beforeAll
// (so a non-BRIDGE_E2E run leaves nothing) and removed in afterAll.
let sessionDir: string | undefined;

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

/** Ribbon helper — the stage buttons live in the `stages` navigation. */
const ribbon = (page: Page) => page.getByRole('navigation', { name: 'stages' });

/**
 * Type a value into one of the design fields and COMMIT it. The card's number
 * inputs are `onchange` (not `oninput`) so a half-typed "1" never rewrites the
 * design mid-keystroke — and Playwright's `fill()` only dispatches `input`, so
 * the field has to be blurred exactly as a real user leaving it would.
 */
async function setField(page: Page, testId: string, value: string) {
  const field = page.getByTestId(testId);
  await field.fill(value);
  await field.blur();
}

// ---------------------------------------------------------------------------
// browser path (default project)
// ---------------------------------------------------------------------------

/**
 * The Web Audio path can render and validate the whole Nonlin stage, but it
 * cannot MEASURE anything: Chromium's fake device plays a built-in tone into
 * the capture, so a real run would analyse a signal that has no relation to
 * the multisine that was played — a singular/garbage BLA. The run itself is
 * therefore covered on the bridge half below; here we cover the truths that
 * need no audio at all (reachability, preflight gating, the period readout).
 */
test.describe('BLA — browser path (no bridge)', () => {
  /** Open the app and switch to the Nonlin stage. */
  async function gotoNonlin(page: Page) {
    await page.goto('/');
    await ribbon(page).getByRole('button', { name: 'Nonlin' }).click();
  }

  test('the Nonlin stage renders and preflight refuses a run with no response channel', async ({ page }) => {
    await gotoNonlin(page);

    // All three card groups render (results is gated on a landed run).
    await expect(page.getByTestId('bla-design')).toBeVisible();
    await expect(page.getByTestId('bla-run')).toBeVisible();
    await expect(page.getByTestId('bla-results')).toHaveCount(0);

    // Default capture is 1 channel, and the default excitation measures its
    // drive on ch 0 — so nothing is left to be a response and the run is
    // refused, with the reason next to the responses readout AND on Start.
    await expect(page.getByTestId('bla-responses')).toContainText('none');
    await expect(page.getByRole('alert').filter({ hasText: 'No response channels' })).toBeVisible();
    await expect(page.getByTestId('bla-start')).toBeDisabled();
    await expect(page.getByTestId('bla-blocked')).toContainText('No response channels');

    // Commanded x needs a hardware-synced NI output; on the browser path the
    // option is disabled and carries the reason as its tooltip.
    const source = page.getByTestId('bla-out-source-0');
    const commanded = source.locator('option[value="commanded"]');
    await expect(commanded).toBeDisabled();
    await expect(commanded).toHaveAttribute('title', /hardware-synced|NI/i);

    // Capture a second channel in Setup → ch 1 becomes the response and the
    // refusal clears (gating works in BOTH directions).
    await ribbon(page).getByRole('button', { name: 'Setup' }).click();
    await page.getByRole('spinbutton', { name: 'channel count' }).fill('2');
    await ribbon(page).getByRole('button', { name: 'Nonlin' }).click();
    await expect(page.getByTestId('bla-responses')).toContainText('ch 1');
    await expect(page.getByRole('alert').filter({ hasText: 'No response channels' })).toHaveCount(0);
    await expect(page.getByTestId('bla-start')).toBeEnabled();
  });

  test('Δf and the period are LINKED — editing either resolves the other', async ({ page }) => {
    await gotoNonlin(page);

    // Read the rate the design resolves against rather than assuming it — the
    // browser path adopts whatever the granted device reports.
    await ribbon(page).getByRole('button', { name: 'Setup' }).click();
    const fs = Number(await page.getByTestId('setup-fs').inputValue());
    expect(fs).toBeGreaterThan(0);
    await ribbon(page).getByRole('button', { name: 'Nonlin' }).click();

    const period = page.getByTestId('bla-period');
    const periodS = page.getByTestId('bla-period-s');

    // Δf → period (round-11 P6: the coupling the user could not see before).
    for (const dfHz of [10, 25]) {
      await setField(page, 'bla-df', String(dfHz));
      const n = Math.round(fs / dfHz);
      await expect(period).toContainText(`N = ${n} samples`);
      expect(Number(await periodS.inputValue())).toBeCloseTo(n / fs, 6);
    }

    // …and back the other way: a typed PERIOD quantises to whole samples and
    // rewrites Δf, which is the half that did not exist at all before.
    const targetN = Math.round(fs / 20);
    await setField(page, 'bla-period-s', String(targetN / fs));
    await expect(period).toContainText(`N = ${targetN} samples`);
    expect(Number(await page.getByTestId('bla-df').inputValue())).toBeCloseTo(fs / targetN, 3);
  });

  test('the total run time is the card headline, live from the design', async ({ page }) => {
    await gotoNonlin(page);
    await ribbon(page).getByRole('button', { name: 'Setup' }).click();
    await page.getByRole('spinbutton', { name: 'channel count' }).fill('2');
    await ribbon(page).getByRole('button', { name: 'Nonlin' }).click();

    // The primary slot leads with the wall-clock total and backs it with the
    // count it is the product of.
    const status = page.getByTestId('bla-status');
    await expect(page.getByTestId('bla-total-time')).toContainText('≈');
    await setField(page, 'bla-m', '4');
    await expect(status).toContainText('4 captures ×');
    // Doubling the realisations doubles the run: the headline follows the
    // design, it is not a one-off readout.
    await setField(page, 'bla-m', '8');
    await expect(status).toContainText('8 captures ×');
    // And the design row says the capture length is the RUN's to set.
    await expect(page.getByTestId('bla-duration-note')).toContainText('overrides the Acquire duration');
  });
});

// ---------------------------------------------------------------------------
// bridge path (BRIDGE_E2E) — the full-pipeline proof
// ---------------------------------------------------------------------------

test.describe('BLA — bridge run (mock driver)', () => {
  test.skip(!BRIDGE_E2E, 'set BRIDGE_E2E=1 (needs pydvma + websockets; spawns python3 -m pydvma.serve)');
  // A run is M x n_exc real captures plus a first-compute pyodide boot.
  test.setTimeout(300_000);

  test.beforeAll(async () => {
    if (!BRIDGE_E2E) return;
    sessionDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pydvma-e2e-'));
    server = spawn(PYTHON, ['-m', 'pydvma.serve', '--driver', 'mock', '--port', String(PORT),
                            '--session-dir', sessionDir], {
      cwd: REPO_ROOT,
      stdio: 'pipe',
    });
    server.stdout.on('data', () => { /* drain */ });
    server.stderr.on('data', () => { /* drain */ });
    await waitForPort(PORT);
  });

  test.afterAll(async () => {
    if (server) {
      server.kill('SIGINT');
      server = undefined;
      await new Promise((r) => setTimeout(r, 300));
    }
    if (sessionDir) {
      fs.rmSync(sessionDir, { recursive: true, force: true });
      sessionDir = undefined;
    }
  });

  /**
   * Setup against the mock device (8 kHz, 2 channels — one measured drive on
   * ch 0 leaves ch 1 as the response), then the Nonlin stage with a SMALL
   * design: N = 1600 samples, 4 periods per capture (~0.83 s) and M = 2, so
   * the whole run is 2 captures. Everything is asserted on the readouts the
   * card publishes, so a changed default cannot silently change the run.
   */
  async function gotoNonlinWithMock(page: Page, opts: { M?: number } = {}) {
    await page.goto(`/?bridge=${encodeURIComponent(WS_URL)}`);
    await expect(ribbon(page).getByRole('button', { name: 'Setup' }))
      .not.toHaveClass(/gated/, { timeout: 20000 });
    await ribbon(page).getByRole('button', { name: 'Setup' }).click();

    const deviceSelect = page.getByRole('combobox', { name: 'input device' });
    await expect(deviceSelect).toContainText('Mock signal generator');
    await deviceSelect.selectOption({ label: 'Mock signal generator' });
    // The fs control is a typed combo (round 11) — fill + Enter, not selectOption.
    await page.getByTestId('setup-fs').fill('8000');
    await page.getByTestId('setup-fs').press('Enter');
    await page.getByRole('spinbutton', { name: 'channel count' }).fill('2');

    await ribbon(page).getByRole('button', { name: 'Nonlin' }).click();
    await setField(page, 'bla-f1', '20');
    await setField(page, 'bla-f2', '500');
    await setField(page, 'bla-df', '5');
    await setField(page, 'bla-m', String(opts.M ?? 2));
    await setField(page, 'bla-p', '2');
    await setField(page, 'bla-transient', '2');

    // The design resolved as intended: 8000/5 = 1600-sample periods, one
    // excitation on ao0 measured on ch 0, ch 1 left as the response.
    await expect(page.getByTestId('bla-period')).toContainText('N = 1600 samples');
    await expect(page.getByTestId('bla-out-enable-0')).toBeChecked();
    await expect(page.getByTestId('bla-out-source-0')).toHaveValue('m0');
    await expect(page.getByTestId('bla-responses')).toContainText('ch 1');
    await expect(page.getByTestId('bla-start')).toBeEnabled();
  }

  test('a full run captures, analyses, lands hidden raw sets + a BLA set, and draws the σ overlay', async ({ page }) => {
    await gotoNonlinWithMock(page);
    // The headline is the run's wall-clock cost, backed by the capture count
    // (round-11 P6) — 2 captures of (2 transient + 2 steady) × 1600 samples
    // at 8 kHz, so ~0.83 s each.
    await expect(page.getByTestId('bla-status')).toContainText('2 captures ×');

    await page.getByTestId('bla-start').click();

    // Progress counts CAPTURES (not realisation/experiment indices the user
    // has to multiply out) and carries a remaining estimate, beside a grid
    // with one cell per capture.
    const progress = page.getByTestId('bla-progress');
    await expect(progress).toContainText('capture 1/2');
    await expect(page.getByTestId('bla-grid')).toBeVisible();
    await expect(progress).toContainText('capture 2/2');

    // Then the single analysis call (first compute of the session, so this
    // also boots pyodide + micropip-installs the vendored pydvma wheel).
    await expect(page.getByTestId('bla-analysing')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('bla-status')).toContainText('1 BLA set', { timeout: 240_000 });

    // The tray holds the 2 raw captures plus the BLA set. NB the numbers in
    // the result are meaningless (the mock returns a fixed sine, not the
    // multisine it was asked to play) — only the plumbing is asserted.
    await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(3);
    // Raw captures land HIDDEN so M x n_exc sets cannot flood the legend; the
    // BLA set itself is shown.
    for (const i of [0, 1]) {
      await expect(page.getByTestId(`tray-card-${i}`).getByTestId('set-name'))
        .toHaveAttribute('aria-label', /set hidden/);
    }
    await expect(page.getByTestId('tray-card-2').getByTestId('set-name'))
      .toHaveAttribute('aria-label', /set shown/);
    // …and the card's toggle reveals them.
    await page.getByTestId('bla-show-raw').click();
    await expect(page.getByTestId('tray-card-0').getByTestId('set-name'))
      .toHaveAttribute('aria-label', /set shown/);
    await page.getByTestId('bla-show-raw').click();

    // A verdict line per excitation, with the σ explainer + docs link beside
    // it (round-11 P6: the results used to arrive with no text at all saying
    // what the new lines and channels were).
    await expect(page.getByTestId('bla-verdict')).toHaveCount(1);
    await expect(page.getByTestId('bla-explain')).toContainText('σ_NL');
    await expect(page.getByTestId('bla-docs-link')).toHaveAttribute('target', '_blank');
    // The run is now a "previous run", so Start offers replace-vs-keep.
    await expect(page.getByTestId('bla-run-mode')).toBeVisible();
    await expect(page.locator('text.axlab').first()).toHaveText('Frequency (Hz)');
    await expect(page.getByTestId('plot-line').first()).toBeAttached();

    // σ overlay: the HONEST zero-floor rendering (review follow-up on Task 9),
    // verified against the actual mock behaviour rather than assumed —
    // `streams.MockRecorder.__init__` regenerates its buffer from sample 0
    // on EVERY capture (bit-identical across the M realisations), so the
    // realisation scatter is EXACTLY 0 ⇒ σ_NL floors to 0 by construction ⇒
    // NO line (the honest "nothing resolvable" gap). But the mock's fixed
    // per-channel tone (`0.1·sin(2π·100·(ch+1)·t)`) is NOT period-locked to
    // this design's N-sample period, so the P period-slices taken from ONE
    // capture are genuinely NOT identical to each other ⇒ σ_n (period-to-
    // period scatter) is honestly non-zero here ⇒ its ONE line legitimately
    // draws. So this run happens to exercise BOTH halves of the fix at once:
    // one σ line correctly suppressed, one correctly drawn — confirmed by
    // inspecting the surviving path's stroke colour (`#6b7280`, σ_n's
    // neutral grey) during development of this assertion. (SVG paths have a
    // zero-height bbox and fail `toBeVisible`, so attribute/count
    // assertions, not visibility, as elsewhere in this file.) The
    // exhaustive proof of the zero-floor behaviour under CONTROLLED numbers
    // (both lines present, both absent, one of each) lives in vitest
    // (`tests/plot/model.test.ts`), which can hand-craft arrays a
    // deterministic mock never will.
    const dashed = page.locator('[data-testid="plot-line"][stroke-dasharray]');
    await expect(dashed).toHaveCount(1);
    await page.screenshot({ path: test.info().outputPath('bla-tf-sigma.png') });

    // The in-card σ KEY (round-11 P6) — the overlay lines carry no legend
    // entry of their own, so the card names which dash is which.
    await expect(page.getByTestId('bla-sigma-key')).toContainText('σ_n');

    // The BLA card's OWN "σ lines" toggle (review item 5: the TF card's
    // toggle below is unreachable from here in practice — the run parks the
    // VIEW on tf but the active STAGE stays 'bla', so a user reading the
    // verdict had no path to a σ toggle without first switching stages) is
    // reachable right here in the results group, without leaving the Nonlin
    // stage, and drives the identical store.
    await expect(page.getByTestId('bla-sigma-toggle-card')).toBeVisible();
    await expect(page.getByTestId('bla-sigma-toggle-card')).toBeChecked();

    // The σ toggle ALSO lives on the TF card, reachable from the TF STAGE
    // (the Nonlin stage shows the BLA card over the same TF view). It still
    // renders — self-gated on the σ ARRAYS EXISTING, not on them having a
    // resolvable value — and toggling it off/on removes/restores the one
    // real (σ_n) line without erroring.
    await ribbon(page).getByRole('button', { name: 'TF' }).click();
    await expect(page.getByTestId('bla-sigma-toggle')).toBeVisible();
    await page.getByTestId('bla-sigma-toggle').uncheck();
    await expect(dashed).toHaveCount(0);
    await page.getByTestId('bla-sigma-toggle').check();
    await expect(dashed).toHaveCount(1);
  });

  test('cancelling mid-run stops after the capture in flight and keeps the raw captures', async ({ page }) => {
    await gotoNonlinWithMock(page, { M: 3 });

    await page.getByTestId('bla-start').click();
    await expect(page.getByTestId('bla-progress')).toContainText('capture 1/3');
    // The button says what it does — the capture in flight always finishes.
    await expect(page.getByTestId('bla-cancel')).toHaveText('stop after this capture');
    await page.getByTestId('bla-cancel').click();

    // The capture in flight completes, then the loop stops: phase 'cancelled',
    // no analysis, and what landed is kept and reachable.
    await expect(page.getByTestId('bla-cancelled')).toBeVisible({ timeout: 60_000 });
    // The grid stays up after a cancel, so the user can see exactly which
    // captures they came away with.
    await expect(page.getByTestId('bla-grid')).toBeVisible();
    await expect(page.getByTestId('bla-analysing')).toHaveCount(0);
    await expect(page.getByTestId('bla-verdict')).toHaveCount(0);
    const cards = page.locator('[data-testid^="tray-card-"]');
    expect(await cards.count()).toBeLessThan(3);
    expect(await cards.count()).toBeGreaterThan(0);
    await expect(page.getByTestId('bla-show-raw')).toBeVisible();
    await page.getByTestId('bla-show-raw').click();
    await expect(page.getByTestId('tray-card-0').getByTestId('set-name'))
      .toHaveAttribute('aria-label', /set shown/);
  });
});
