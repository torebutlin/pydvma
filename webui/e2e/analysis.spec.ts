import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';

/** Absolute path to a checked-in fixture under webui/tests/fixtures. */
function fixturePath(name: string): string {
  return fileURLToPath(new URL(`../tests/fixtures/${name}`, import.meta.url));
}

/** Click Load Data and answer the fallback file chooser with `path`. */
async function loadViaFallback(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

/** Fraction of opaque (alpha>0) pixels in the sono heat canvas. */
function sonoPaintFrac(page: Page) {
  return page.evaluate(() => {
    const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
    const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let painted = 0;
    for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
    return painted / (c.width * c.height);
  });
}

/**
 * Fraction of the VISIBLE plot region — a page screenshot of `.plot-host`,
 * i.e. WHAT A HUMAN SEES — that is viridis-saturated colour. This is the guard
 * the two previous sono verifications lacked. `sonoPaintFrac` above reads the
 * heat CANVAS's OWN backing store (getImageData on the element), which stays
 * fully painted even when an opaque SVG surface is layered ON TOP of it — so it
 * passed in CI while the real app showed a blank white/dark plot (the
 * longstanding bug). This instead round-trips an ELEMENT SCREENSHOT (the fully
 * composited pixels: heat canvas + axis SVG stacked over it) back through an
 * in-page <img>+canvas and scans it. Viridis spans purple→yellow (every stop is
 * saturated), so a visible heat colours most of the data rect (~0.6–0.8);
 * when the heat is hidden behind an opaque `.plot-bg` this collapses to ~0
 * (only a few % of grey axis text). DPR-independent (measures a fraction).
 */
async function sonoVisibleColourFrac(page: Page): Promise<number> {
  return pngColourFrac(page, await page.locator('.plot-host').screenshot());
}

/**
 * Fraction of a PNG buffer that is viridis-saturated colour, scanned by
 * round-tripping the bytes through an in-page <img>+canvas (so it works for a
 * downloaded figure as well as a page screenshot). Viridis stops span
 * purple→yellow, all with max−min channel spread ≫ 25; grey axis chrome and a
 * flat white/dark surface do not. Used for both the on-screen visible-pixel
 * guard and the exported-figure heat guard.
 */
function pngColourFrac(page: Page, buf: Buffer): Promise<number> {
  const dataUrl = 'data:image/png;base64,' + buf.toString('base64');
  return page.evaluate(async (url) => {
    const img = new Image();
    await new Promise((res, rej) => { img.onload = () => res(null); img.onerror = rej; img.src = url; });
    const cv = document.createElement('canvas');
    cv.width = img.naturalWidth;
    cv.height = img.naturalHeight;
    const ctx = cv.getContext('2d')!;
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
    let total = 0, coloured = 0;
    for (let i = 0; i < d.length; i += 4) {
      total++;
      const mx = Math.max(d[i], d[i + 1], d[i + 2]);
      const mn = Math.min(d[i], d[i + 1], d[i + 2]);
      if (mx - mn > 25) coloured++; // saturated => viridis heat, not grey chrome / flat surface
    }
    return coloured / total;
  }, dataUrl);
}

/**
 * The COMPUTED (rendered) fill of the overlay plot-bg rect — the value that
 * must be transparent for the heat behind the SVG to show through. The previous
 * guard read the ATTRIBUTE (`getAttribute('fill')`), which is 'transparent'
 * even when the scoped `.plot-bg` CSS overrode it to the opaque `--surface`
 * colour on screen: a presentation attribute loses to a class rule, so the
 * attribute check was blind to the exact bug that shipped. `getComputedStyle`
 * reports what actually paints; transparent renders as `rgba(0, 0, 0, 0)`.
 */
function sonoPlotBgComputedFill(page: Page): Promise<string> {
  return page.evaluate(() => getComputedStyle(document.querySelector('[data-role="plot-bg"]')!).fill);
}

/**
 * Fraction of pixels that DIFFER between two PNG screenshots (of the SAME
 * region, same size), scanned in-page. Used to prove a control changed the
 * VISIBLE composited image — the standard the engineering note demands: a claim
 * that log-y (or a colour toggle) altered the render is only trusted when the
 * on-screen pixels actually move. Small per-channel jitter (<12) is ignored so
 * antialiasing / theme sub-pixel noise doesn't count as a change.
 */
function pngPixelDiffFrac(page: Page, a: Buffer, b: Buffer): Promise<number> {
  const urlA = 'data:image/png;base64,' + a.toString('base64');
  const urlB = 'data:image/png;base64,' + b.toString('base64');
  return page.evaluate(async ([ua, ub]) => {
    const load = (u: string) => new Promise<HTMLImageElement>((res, rej) => {
      const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = u;
    });
    const [ia, ib] = await Promise.all([load(ua), load(ub)]);
    const w = Math.min(ia.naturalWidth, ib.naturalWidth);
    const h = Math.min(ia.naturalHeight, ib.naturalHeight);
    const draw = (im: HTMLImageElement) => {
      const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
      const ctx = cv.getContext('2d')!; ctx.drawImage(im, 0, 0);
      return ctx.getImageData(0, 0, w, h).data;
    };
    const da = draw(ia), db = draw(ib);
    let total = 0, diff = 0;
    for (let i = 0; i < da.length; i += 4) {
      total++;
      if (Math.abs(da[i] - db[i]) > 12 || Math.abs(da[i + 1] - db[i + 1]) > 12
        || Math.abs(da[i + 2] - db[i + 2]) > 12) diff++;
    }
    return diff / total;
  }, [urlA, urlB]);
}

/**
 * The numeric y-axis tick VALUES of the (single) plot on screen. Y ticks are the
 * `text.tick` elements anchored to the END (right-aligned, left of the data
 * rect); x ticks are middle-anchored, so this selector picks the y axis only.
 * Used to assert log-frequency ticks land on DECADES when the sono y-scale is
 * log (consecutive values in a ~10 ratio).
 */
function sonoYTickValues(page: Page): Promise<number[]> {
  return page.evaluate(() => Array.from(
    document.querySelectorAll('[data-testid="plot-svg"] text.tick[text-anchor="end"]'))
    .map((t) => Number((t.textContent ?? '').trim()))
    .filter((v) => Number.isFinite(v)));
}

/**
 * The ACTIVE view slice's committed range + history length, read through the
 * `?fixture=1` `window.__viewState` dev hook (the axis-nav specs' pattern).
 * On the sono view this is the 'sono' slice — the store the toolbar limit
 * fields, Auto X/Y and box-zoom all commit into (round-7 item 2 guard).
 */
function activeSlice(page: Page): Promise<{
  range: { x: [number, number] | null; y: [number, number] | null };
  historyLen: number;
}> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      current: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('window.__viewState hook missing (need ?fixture=1)');
    let raw: {
      range: { x: [number, number] | null; y: [number, number] | null };
      history: unknown[];
    } | null = null;
    vs.current.subscribe((v) => { raw = v as typeof raw; })();
    if (!raw) throw new Error('view slice unavailable');
    const s = raw as NonNullable<typeof raw>;
    return { range: s.range, historyLen: s.history.length };
  });
}

/**
 * Orphan-only tray (round-6 items 2/3): a TF-only load has NO time signal, so
 * the sonogram cannot run. Fast (no engine): loads the checked-in orphan
 * `.dvma` via the fallback input and asserts Calc Sonogram is DISABLED with a
 * clear note — instead of the opaque deref error + white plot Tore hit.
 */
test('orphan-only tray disables Calc Sonogram with a clear note', async ({ page }) => {
  await page.goto('/');
  await loadViaFallback(page, fixturePath('orphan_tf_3col.dvma'));
  await expect(page.getByTestId('tray-card-0')).toBeVisible();

  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
  const region = page.getByRole('region', { name: 'Sonogram stage controls' });
  // No time-bearing set ⇒ no dataset dropdown, an inline marker, and a note.
  await expect(region.getByTestId('sono-no-time')).toBeVisible();
  await expect(region.getByLabel('dataset', { exact: true })).toHaveCount(0);
  await expect(region.getByText(/needs a time-domain signal/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Calc Sonogram' })).toBeDisabled();
});

/**
 * @engine — the analysis golden path (Task 12). Loads the checked-in
 * impulse.dvma via `?fixture=1`, switches to the TF stage, runs Calc TF
 * end to end through the real pyodide worker, and asserts a plot line
 * renders. Then switches to the Nyquist plot type and asserts the plot
 * SVG's drawing box is ~square (the aspect-locked Nyquist view).
 *
 * SLOW: the first Calc TF pays the full pyodide boot (numpy/scipy +
 * pydvma wheel install) because the app boots the engine lazily on
 * first compute. Tagged `@engine` so it runs/skips with the other
 * engine tests.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('fixture → TF → Calc TF renders a line; Nyquist is square', async ({ page }) => {
    await page.goto('/?fixture=1');

    // The fixture set lands in the tray.
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Switch to the TF stage and run the transfer-function estimate.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
    await page.getByRole('button', { name: 'Calc TF' }).click();

    // First compute boots the engine — allow the full boot budget.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    // Nyquist: pick the plot type and assert a ~square drawing box.
    await page.getByLabel('plot type').selectOption('nyquist');
    // Give the aspect-locked model a beat to re-render.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 20_000 });

    const svg = page.getByTestId('plot-svg');
    const box = await svg.boundingBox();
    expect(box).not.toBeNull();
    // The SVG element fills the host; the SQUARE is the inner drawing
    // area. Assert the frame rect (data-role="axis" .frame) is square.
    const frame = await page.evaluate(() => {
      const f = document.querySelector('[data-testid="plot-svg"] rect.frame') as SVGGraphicsElement | null;
      if (!f) return null;
      const b = f.getBoundingClientRect();
      return { w: b.width, h: b.height };
    });
    expect(frame).not.toBeNull();
    expect(Math.abs(frame!.w - frame!.h)).toBeLessThan(0.2 * frame!.w);
  });

  test('fixture → Sonogram → Calc renders a filled, painted heat canvas', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();

    const canvas = page.getByTestId('sono-canvas');
    await expect(canvas).toBeVisible({ timeout: 200_000 });

    // The canvas element mounts immediately in the sono view; wait until the
    // worker result has actually PAINTED it (non-trivial alpha coverage)
    // before measuring — otherwise we read the empty default buffer.
    await expect.poll(async () => page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let painted = 0;
      for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
      return painted / (c.width * c.height);
    }), { timeout: 200_000 }).toBeGreaterThan(0.9);

    // The three shipped bugs: (1) the canvas rendered at its intrinsic buffer
    // size (a ~38px sliver) instead of filling the data rect; (2) the buffer
    // was empty; (3) — THE longstanding one — the axis SVG's opaque plot-bg hid
    // the (correctly painted) heat on screen. Assert the canvas fills most of
    // the host, the buffer has real viridis structure (>1 distinct colour,
    // spanning floor→peak), and the overlay plot-bg fill is transparent — read
    // as the COMPUTED style, not the attribute (the attribute was 'transparent'
    // even while the scoped CSS painted it opaque, which is why this shipped).
    const info = await page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const host = c.closest('.plot-host') as HTMLElement;
      const r = c.getBoundingClientRect(), hr = host.getBoundingClientRect();
      const ctx = c.getContext('2d')!;
      const img = ctx.getImageData(0, 0, c.width, c.height).data;
      const colours = new Set<string>();
      let painted = 0;
      for (let i = 0; i < img.length; i += 4) {
        if (img[i + 3]) painted++;
        colours.add(`${img[i]},${img[i + 1]},${img[i + 2]}`);
      }
      const bgEl = document.querySelector('[data-role="plot-bg"]')!;
      return {
        fillsHost: r.width > hr.width * 0.7 && r.height > hr.height * 0.6,
        paintedFrac: painted / (c.width * c.height),
        distinctColours: colours.size,
        plotBgAttr: bgEl.getAttribute('fill'),
        plotBgComputed: getComputedStyle(bgEl).fill,
      };
    });
    expect(info.fillsHost).toBe(true);
    expect(info.plotBgAttr).toBe('transparent'); // inline attr (export self-containment)
    expect(info.plotBgComputed).toBe('rgba(0, 0, 0, 0)'); // RENDERED fill — the real on-screen guard
    expect(info.paintedFrac).toBeGreaterThan(0.9);
    expect(info.distinctColours).toBeGreaterThan(3);

    // VISIBLE-pixel guard — what a HUMAN sees. The heat must actually be on
    // screen (composited plot region is mostly viridis), not merely present in
    // the canvas backing store. This is the assertion the prior verifications
    // never made; it would have failed RED against every shipped build.
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);

    // ── sono axis controls: y lin|log + colour dB|lin (verified on VISIBLE
    //    composited pixels, per the layered-canvas engineering note) ──
    // Diff the HEAT element's composited box (data rect), not `.plot-host`: the
    // toolbar's active-button highlight moves on toggle, so a `.plot-host` diff
    // could pass on the highlight alone. The data rect is heat, so a real remap
    // dominates; a broken (no-op) remap would fall well below the threshold.
    const heat = page.getByTestId('sono-canvas');
    const linY = await heat.screenshot();                 // default: linear freq y, dB colour
    const linYTicks = await sonoYTickValues(page);

    // Toggle the frequency y-axis to log. The heat rows remap through log10 and
    // the axis ticks move to decades, so the COMPOSITED image must visibly move.
    await page.getByTestId('sono-yscale-toggle').getByRole('button', { name: 'log' }).click();
    await expect.poll(async () => pngPixelDiffFrac(page, linY, await heat.screenshot()))
      .toBeGreaterThan(0.05);
    // Still a visible heat (didn't blank), and the y ticks are now decades.
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);
    const logYTicks = await sonoYTickValues(page);
    expect(logYTicks.length).toBeGreaterThanOrEqual(2);
    // Consecutive decade ticks sit in a ~10 ratio (the log-spacing proof), and
    // the tick set differs from the linear one.
    for (let i = 1; i < logYTicks.length; i++) {
      expect(logYTicks[i] / logYTicks[i - 1]).toBeCloseTo(10, 0);
    }
    expect(logYTicks).not.toEqual(linYTicks);

    // Toggle the heat COLOUR to linear (over the same 0→peak range): a distinct
    // visible change from the dB mapping, and the dynamic-range control disables.
    const logDb = await heat.screenshot();
    await page.getByTestId('sono-colour-toggle').getByRole('button', { name: 'lin' }).click();
    await expect(page.getByTestId('sono-dynrange-lin-note')).toBeVisible();
    await expect(page.getByLabel('dynamic range dB')).toBeDisabled();
    // dB↔lin is a colour REMAP (same layout), so the visible diff is smaller
    // than the log-y spatial remap: both fill the rect with viridis, only the
    // per-cell colour shifts. ~0.023 measured; 0.012 sits safely above the
    // toolbar-highlight floor (~0.003) yet fails a no-op colour toggle.
    await expect.poll(async () => pngPixelDiffFrac(page, logDb, await heat.screenshot()))
      .toBeGreaterThan(0.012);
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);

    // ── sono axis RANGES (round-7 item 2 — the regression this file never
    //    guarded, which is why it shipped): the limit fields used to seed from
    //    the empty-lines model's [0,1] fallback, and setRange('sono') was
    //    written but never read by the heat painter / axis model. Assert the
    //    fields carry REAL extents, a committed edit moves the store + ticks +
    //    visible pixels, Auto Y restores the full extent, and a box-zoom drag
    //    commits an undoable window. ──
    // Back to linear y + dB colour: the dB map paints structure across the
    // whole window (this fixture's LINEAR-colour heat is near-uniform dark,
    // which would starve a pixel diff of signal).
    await page.getByTestId('sono-yscale-toggle').getByRole('button', { name: 'lin' }).click();
    await page.getByTestId('sono-colour-toggle').getByRole('button', { name: 'dB' }).click();
    await expect(page.getByLabel('dynamic range dB')).toBeEnabled();
    await page.getByTestId('zoom-toolbar').hover();
    await expect(page.getByTestId('axis-popover')).toBeVisible();
    const xMax0 = parseFloat(await page.getByLabel('x max').inputValue());
    const yMax0 = parseFloat(await page.getByLabel('y max').inputValue());
    // Real time/frequency extents, not the dead 0..1 seeds (both maxed at 1).
    expect(yMax0).toBeGreaterThan(2);
    expect(xMax0).not.toBe(1);

    // Commit a tenth-height frequency window: store, y ticks and PIXELS all
    // move. A tenth (not half) because this fixture's spectrum is SPARSE — a
    // low-frequency ridge over a dB floor — so a gentle crop only shifts the
    // ridge a few rows and a pixel diff can't see it; zooming to a tenth
    // relocates the ridge across ~a fifth of the plot height.
    const cropBase = await heat.screenshot();
    await page.getByLabel('y max').fill(String(yMax0 / 10));
    await expect.poll(async () => (await activeSlice(page)).range.y?.[1], { timeout: 4000 })
      .toBe(yMax0 / 10);
    // Ticks first (structure-independent proof the axis consumed the range) …
    await expect.poll(async () => Math.max(...(await sonoYTickValues(page))))
      .toBeLessThanOrEqual(yMax0 * 0.12);
    // … then the visible-pixels guard: the heat itself remapped.
    await expect.poll(async () => pngPixelDiffFrac(page, cropBase, await heat.screenshot()))
      .toBeGreaterThan(0.02);
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);

    // Auto Y restores the full frequency extent (an explicit committed range).
    await page.getByRole('button', { name: 'Auto Y' }).click();
    await expect.poll(async () => {
      const y = (await activeSlice(page)).range.y;
      return y ? y[1] > yMax0 * 0.99 : false;
    }, { timeout: 4000 }).toBe(true);

    // Box-zoom drag on the sono overlay commits BOTH axes and is undoable.
    await page.mouse.move(6, 560); // park the pointer so the popover closes
    await expect(page.getByTestId('axis-popover')).toHaveCount(0);
    const preDrag = await activeSlice(page);
    const box = (await page.getByTestId('plot-svg').boundingBox())!;
    await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.3);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.75, box.y + box.height * 0.65, { steps: 5 });
    await page.mouse.up();
    await expect.poll(async () => (await activeSlice(page)).historyLen, { timeout: 4000 })
      .toBeGreaterThan(preDrag.historyLen);
    const zoomed = await activeSlice(page);
    expect(zoomed.range.x).not.toBeNull();
    expect(zoomed.range.x![1]).toBeLessThanOrEqual(xMax0 * 1.06); // clamp guardrail held
    // Undo (view history) walks the y range back to the pre-drag full window.
    await page.getByRole('button', { name: 'Undo view change' }).click();
    await expect.poll(async () => {
      const y = (await activeSlice(page)).range.y;
      return y ? y[1] > yMax0 * 0.99 : false;
    }, { timeout: 4000 }).toBe(true);
  });

  test('Fit damping opens the interactive panel: decay fits, threshold + start controls, bands mode (round-7 items 3/4)', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();

    // The panel arrives WITHOUT needing Calc Sonogram first — damping can be
    // the session's first compute (this exact path used to park forever: the
    // damping op never kicked engine.boot(), a latent pre-panel bug).
    await page.getByTestId('sono-fit-damping').click();
    const panel = page.getByTestId('damping-panel');
    await expect(panel).toBeVisible({ timeout: 200_000 });
    const legend = page.getByTestId('damping-fit-legend');

    // STFT peaks on this 1 s fixture legitimately fit NO modes (the impulse
    // decays inside a couple of STFT frames) — the panel must say so rather
    // than error, and still show the picking context: the spectrum with its
    // threshold line, and the start line over the sonogram.
    await expect(legend).toContainText('No modes fitted', { timeout: 200_000 });
    await expect(page.getByTestId('damping-spectrum')).toBeVisible();
    // toBeAttached, not toBeVisible: a horizontal SVG <line> has a
    // zero-HEIGHT bounding box, which Playwright's visibility check calls
    // hidden even when it renders perfectly.
    await expect(page.getByTestId('damping-threshold-line')).toBeAttached();
    const thrAuto = parseFloat(await page.getByTestId('damping-threshold-input').inputValue());
    expect(thrAuto).toBeGreaterThan(0);   // engine echoed its auto choice
    expect(Number.isFinite(parseFloat(
      await page.getByTestId('damping-start-input').inputValue()))).toBe(true);

    // The draggable start-time line maps through the sonogram's axes, so it
    // appears once the heat is computed (not over the empty pre-Calc plot).
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();
    await expect.poll(() => sonoPaintFrac(page), { timeout: 200_000 }).toBeGreaterThan(0.9);
    await expect(page.getByTestId('damping-start-line')).toBeVisible();

    // Switch the sonogram method to CWT (full time resolution) and Refit —
    // the fit follows the card's method, and the CWT resolves the fixture's
    // low mode: the decay chart draws the fitted line + × markers, with an
    // `f Hz, Qn=…` legend chip (the Qt DampingFitWindow readout).
    await page.getByTestId('sono-method').getByRole('button', { name: 'CWT' }).click();
    await page.getByTestId('damping-refit').click();
    await expect(legend.locator('.dp-chip').first()).toBeVisible({ timeout: 200_000 });
    await expect(legend.locator('.dp-chip').first()).toContainText('Qn=');
    await expect(page.getByTestId('damping-decay').locator('polyline.dp-fit').first())
      .toBeVisible();

    // A maximal threshold suppresses every candidate (the control is LIVE)…
    await page.getByTestId('damping-threshold-input').fill('1');
    await page.getByTestId('damping-threshold-input').dispatchEvent('change');
    await expect(legend).toContainText('No modes fitted', { timeout: 200_000 });
    // …and a permissive one brings the fit back.
    await page.getByTestId('damping-threshold-input').fill('0.05');
    await page.getByTestId('damping-threshold-input').dispatchEvent('change');
    await expect(legend.locator('.dp-chip').first()).toBeVisible({ timeout: 200_000 });

    // Bands mode: Schroeder EDC chart + the metrics table.
    await page.getByTestId('damping-mode-toggle').getByRole('button', { name: 'bands' }).click();
    const table = page.getByTestId('damping-band-table');
    await expect(table).toBeVisible({ timeout: 200_000 });
    await expect(table.locator('tbody tr').first()).toBeVisible();
    await expect(table.locator('thead')).toContainText('T60');
    // A full octave ladder of EDC polylines, at least one carrying a real
    // curve. Deliberately NOT `.first().toBeVisible()`: the lowest band's
    // ultra-narrow normalized bandpass can go non-finite under WASM scipy,
    // rendering an empty polyline (its metrics legitimately show as `—`).
    const edcs = page.getByTestId('damping-edc').locator('polyline.dp-edc');
    await expect.poll(() => edcs.count()).toBeGreaterThan(3);
    await expect.poll(async () => {
      const lens = await edcs.evaluateAll(
        (els) => els.map((e) => (e.getAttribute('points') ?? '').length));
      return Math.max(0, ...lens);
    }).toBeGreaterThan(100);

    // Close returns the plot area to full height.
    await page.getByTestId('damping-close').click();
    await expect(panel).toHaveCount(0);
  });

  test('Clean Impulse toggles: on, raw restored off, cached back on (round-7b)', async ({ page }) => {
    // Real-engine smoke over the toggle FLOW (button state + no errors).
    // The raw/cleaned array identities are pinned at the unit level
    // (actions.test.ts) — this fixture's impulse is synthetic and nearly
    // noiseless, so cleaned-vs-raw renders pixel-identically and a plotted-
    // path fingerprint cannot discriminate the copies.
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Time' }).click();
    const btn = page.getByTestId('clean-impulse-toggle');
    await expect(btn).toBeEnabled();

    // ON: engine clean runs (first compute of the session — boots too).
    await btn.click();
    await expect(btn).toHaveText('Clean Impulse: on', { timeout: 200_000 });
    await expect(btn).toHaveAttribute('aria-pressed', 'true');

    // OFF: raw restored (no engine op — near-instant).
    await btn.click();
    await expect(btn).toHaveText('Clean Impulse', { timeout: 20_000 });
    await expect(btn).toHaveAttribute('aria-pressed', 'false');

    // ON again: the cached clean reapplies (no engine re-clean).
    await btn.click();
    await expect(btn).toHaveText('Clean Impulse: on', { timeout: 20_000 });

    await expect(page.locator('.ctx-err')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('multiset + orphan: Sonogram targets a time-bearing set, excludes the orphan, paints in BOTH themes (round-6 items 2/3)', async ({ page }) => {
    // grid_data-like: two time-bearing 2-channel sets PLUS one orphan TF (no
    // time series). The exact tray that blanked Tore's sonogram. Load it, and
    // prove the sonogram targets a time set, the orphan is not offered, and the
    // heat paints in light AND dark (the dark-theme white-plot concern).
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto('/');
    await loadViaFallback(page, fixturePath('multiset_orphan.dvma'));
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
    const region = page.getByRole('region', { name: 'Sonogram stage controls' });
    const ds = region.getByLabel('dataset', { exact: true });
    // Only the two TIME-BEARING sets — the orphan TF is filtered out (no 'All
    // sets' either).
    await expect(ds.locator('option')).toHaveText(['ms_a', 'ms_b']);

    // Compute in the initial theme and assert the heat canvas fills with data.
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();
    await expect(page.getByTestId('sono-canvas')).toBeVisible({ timeout: 200_000 });
    await expect.poll(() => sonoPaintFrac(page), { timeout: 200_000 }).toBeGreaterThan(0.9);
    // VISIBLE on screen via the PICKER load path (the maintainer's real flow),
    // not just painted in the canvas buffer. Guards the opaque-overlay bug.
    expect(await sonoPlotBgComputedFill(page)).toBe('rgba(0, 0, 0, 0)');
    expect(await sonoVisibleColourFrac(page), 'heat visible on screen (initial theme)').toBeGreaterThan(0.3);

    // Flip the theme and recompute: the viridis heat is data-driven, so it must
    // paint — AND be visible — just as fully in the other theme (no white/blank
    // plot in dark, where the overlay bg is an opaque dark surface if unfixed).
    const before = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    await page.getByTestId('theme-toggle').click();
    const after = await page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    expect(after).not.toBe(before);
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();
    await expect.poll(() => sonoPaintFrac(page), { timeout: 60_000 }).toBeGreaterThan(0.9);
    expect(await sonoVisibleColourFrac(page), 'heat visible on screen (flipped theme)').toBeGreaterThan(0.3);

    // Log-y works in the FLIPPED theme too (both-themes coverage for the axis
    // controls): toggling y=log visibly moves the composited image and stays a
    // visible heat under the flipped surface.
    const heat = page.getByTestId('sono-canvas');
    const linY = await heat.screenshot();
    await page.getByTestId('sono-yscale-toggle').getByRole('button', { name: 'log' }).click();
    await expect.poll(async () => pngPixelDiffFrac(page, linY, await heat.screenshot()))
      .toBeGreaterThan(0.05);
    expect(await sonoVisibleColourFrac(page), 'log-y heat visible (flipped theme)').toBeGreaterThan(0.3);

    expect(errors, 'no uncaught page errors during the sono flow').toEqual([]);
  });

  test('fixture → Sonogram → CWT method → Calc renders a painted heat canvas (round-5 item 12)', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();

    // Switch the transform to the complex Morlet CWT (constant-Q) via the
    // shared STFT | CWT segmented control, then compute through the real
    // engine (needs the rebuilt wheel that ships analysis.calculate_cwt).
    await page.getByTestId('sono-method').getByRole('button', { name: 'CWT' }).click();
    // The CWT-only controls appear; the STFT nFFT box is hidden.
    await expect(page.getByLabel('voices per octave')).toBeVisible();
    await expect(page.getByLabel('nFFT')).toHaveCount(0);

    await page.getByRole('button', { name: 'Calc Sonogram' }).click();

    const canvas = page.getByTestId('sono-canvas');
    await expect(canvas).toBeVisible({ timeout: 200_000 });
    await expect.poll(async () => page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let painted = 0;
      for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
      return painted / (c.width * c.height);
    }), { timeout: 200_000 }).toBeGreaterThan(0.9);
    // The CWT heat must be VISIBLE on screen too (same overlay path as STFT).
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);

    // Log-y on the CWT's NATIVE log-spaced grid (the standing TODO): the renderer
    // maps each source frequency VALUE to a pixel, so a non-uniform grid remaps
    // correctly. Toggling y=log must visibly move the composited image and land
    // decade ticks — with the wavelet's full low-frequency detail now shown.
    const heat = page.getByTestId('sono-canvas');
    const linY = await heat.screenshot();
    await page.getByTestId('sono-yscale-toggle').getByRole('button', { name: 'log' }).click();
    await expect.poll(async () => pngPixelDiffFrac(page, linY, await heat.screenshot()))
      .toBeGreaterThan(0.05);
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);
    const logYTicks = await sonoYTickValues(page);
    expect(logYTicks.length).toBeGreaterThanOrEqual(2);
    for (let i = 1; i < logYTicks.length; i++) {
      expect(logYTicks[i] / logYTicks[i - 1]).toBeCloseTo(10, 0);
    }
  });

  /**
   * Linked export gap (fixed alongside the on-screen bug): the sonogram heat is
   * a sibling `<canvas>`, invisible to the SVG-string figure exporter, so a
   * sono figure USED to export as blank axes only. App's `getSvg` now composites
   * the heat into the export SVG as a data-URL <image>. Export a PNG through the
   * real Export-stage flow (fallback download) and assert the raster contains
   * viridis colour — not a blank white figure.
   */
  test('fixture → Sonogram → Calc → Export PNG contains the heat map', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();
    await expect(page.getByTestId('sono-canvas')).toBeVisible({ timeout: 200_000 });
    await expect.poll(() => sonoPaintFrac(page), { timeout: 200_000 }).toBeGreaterThan(0.9);

    // Export stage keeps the sono VIEW (its stage has view:null), so getSvg
    // still targets the sono plot. PNG is the default-checked format.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Export' }).click();
    const region = page.getByRole('region', { name: 'Export stage controls' });
    const downloadPromise = page.waitForEvent('download');
    await region.getByRole('button', { name: 'Export', exact: true }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.png$/);
    const path = await download.path();
    expect(path).toBeTruthy();
    // The exported raster must carry the heat, not blank axes on white.
    expect(await pngColourFrac(page, readFileSync(path!))).toBeGreaterThan(0.3);
  });
});

/**
 * DPR 2 (retina). CI Chromium defaults to deviceScaleFactor 1, so the earlier
 * sono verifications never ran at the maintainer's Mac DPR — a scenario where a
 * mis-sized canvas backing store could draw off-view. Pin DPR 2 in its own
 * describe (test.use must be describe/file scoped) and re-run the VISIBLE-pixel
 * guard via the PICKER load path.
 */
test.describe('@engine sono at DPR 2 (retina)', () => {
  test.use({ deviceScaleFactor: 2 });
  test.setTimeout(240_000);

  test('picker load → Sonogram → Calc paints a VISIBLE heat at DPR 2', async ({ page }) => {
    await page.goto('/');
    await loadViaFallback(page, fixturePath('multiset_orphan.dvma'));
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();
    await expect(page.getByTestId('sono-canvas')).toBeVisible({ timeout: 200_000 });
    await expect.poll(() => sonoPaintFrac(page), { timeout: 200_000 }).toBeGreaterThan(0.9);
    expect(await sonoPlotBgComputedFill(page)).toBe('rgba(0, 0, 0, 0)');
    expect(await sonoVisibleColourFrac(page)).toBeGreaterThan(0.3);
  });
});
