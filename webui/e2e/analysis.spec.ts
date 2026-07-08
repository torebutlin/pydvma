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
