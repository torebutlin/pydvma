import { expect, test, type Page } from '@playwright/test';

/**
 * Frequency navigator (dev/plans/2026-07-11-freq-navigator-design.md).
 * NON-ENGINE: `?fixture=1` seeds a TfData on load (several evenly-spaced
 * resonances), so the TF view has real lines without booting pyodide.
 * Covers: the toolbar toggle; band-drag → live re-window + ONE history
 * entry; "zoom to band" scope + ribbon + double-click clear (via the
 * `freqScope` store hook); the ribbon's full-range track actually visible;
 * peak-step keep-width; Fit-stage auto-open.
 */

/** Read {range.x, historyLen} of the tf slice via the ?fixture=1 hook. */
async function tfRange(page: Page): Promise<{ x: [number, number] | null; historyLen: number }> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      current: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('window.__viewState hook missing (need ?fixture=1)');
    let raw: { range: { x: [number, number] | null }; history: unknown[] } | null = null;
    vs.current.subscribe((v) => { raw = v as typeof raw; })();
    if (!raw) throw new Error('view slice unavailable');
    const s = raw as NonNullable<typeof raw>;
    return { x: s.range.x, historyLen: s.history.length };
  });
}

/** Read the shared freqScope store via the hook. */
async function freqScope(page: Page): Promise<[number, number] | null> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      freqScope: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('hook missing');
    let raw: [number, number] | null = null;
    vs.freqScope.subscribe((v) => { raw = v as typeof raw; })();
    return raw;
  });
}

/**
 * Fraction of the PNG's pixels that differ (any channel by > 12) from `rgb`,
 * decoded through a canvas in the page. Measures what is visibly drawn: the
 * pre-fix ribbon passed every attribute check while its track composited to
 * within a few levels of the card's background.
 */
function inkFraction(page: Page, png: Buffer, rgb: [number, number, number]): Promise<number> {
  const url = 'data:image/png;base64,' + png.toString('base64');
  return page.evaluate(async ([u, ref]) => {
    const im = await new Promise<HTMLImageElement>((res, rej) => {
      const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = u as string;
    });
    const cv = document.createElement('canvas');
    cv.width = im.naturalWidth; cv.height = im.naturalHeight;
    const ctx = cv.getContext('2d')!; ctx.drawImage(im, 0, 0);
    const d = ctx.getImageData(0, 0, cv.width, cv.height).data;
    const [r, g, b] = ref as [number, number, number];
    let ink = 0;
    for (let k = 0; k < d.length; k += 4) {
      if (Math.abs(d[k] - r) > 12 || Math.abs(d[k + 1] - g) > 12 || Math.abs(d[k + 2] - b) > 12) ink++;
    }
    return ink / (d.length / 4);
  }, [url, rgb] as const);
}

/** Load the fixture and switch to the TF stage (tf-mag plot, no engine). */
async function openTf(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();
  await expect.poll(() => page.evaluate(() =>
    !!(window as unknown as { __viewState?: unknown }).__viewState)).toBe(true);
}

/** Type an exact window into the navigator's numeric fields. */
async function setWindow(page: Page, lo: number, hi: number): Promise<void> {
  await page.getByTestId('freq-nav-min').fill(String(lo));
  await page.getByTestId('freq-nav-min').press('Enter');
  await page.getByTestId('freq-nav-max').fill(String(hi));
  await page.getByTestId('freq-nav-max').press('Enter');
}

test('hidden by default on TF-mag; toggle shows it; band drag = one undo entry', async ({ page }) => {
  await openTf(page);
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
  await page.getByTestId('freq-nav-toggle').click();
  await expect(page.getByTestId('freq-nav')).toBeVisible();

  // Narrow to a sub-band first: a full-width band spans the whole extent and
  // has nowhere to translate (it clamps straight back), so it is not
  // draggable — same as every axis-nav band-drag test. `before` is captured
  // AFTER the narrowing so the drag alone must add exactly one history entry.
  await setWindow(page, 300, 900);
  const before = await tfRange(page);
  const band = page.getByTestId('freq-nav-band');
  const box = (await band.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  const after = await tfRange(page);
  expect(after.historyLen).toBe(before.historyLen + 1);   // whole drag = ONE entry
  expect(after.x).not.toEqual(before.x);

  await page.getByTestId('freq-nav-toggle').click();
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
});

test('scope: zoom to band scopes to the window, ribbon appears; double-click clears', async ({ page }) => {
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 250, 750);
  await expect(page.getByTestId('freq-nav-ribbon')).not.toBeAttached();
  await page.getByTestId('freq-nav-scope-btn').click();
  await expect(page.getByTestId('freq-nav-ribbon')).toBeVisible();
  const s = await freqScope(page);
  expect(s).not.toBeNull();
  expect(Math.abs(s![0] - 250)).toBeLessThan(1);
  expect(Math.abs(s![1] - 750)).toBeLessThan(1);
  await page.getByTestId('freq-nav-ribbon').dblclick();
  await expect(page.getByTestId('freq-nav-ribbon')).not.toBeAttached();
  expect(await freqScope(page)).toBeNull();
});

test('scope: the head button is a toggle, so a scoped strip can be re-expanded', async ({ page }) => {
  // Lab feedback (2026-09): scoping to a band was "all nice", but the only
  // way back out was a double-click on a thin ribbon nobody finds.
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 250, 750);
  const btn = page.getByTestId('freq-nav-scope-btn');
  await expect(btn).toHaveAttribute('aria-pressed', 'false');

  await btn.click();
  await expect(page.getByTestId('freq-nav-ribbon')).toBeVisible();
  await expect(btn).toHaveAttribute('aria-pressed', 'true');

  // The same button now clears the scope and re-expands to the full extent.
  await btn.click();
  await expect(page.getByTestId('freq-nav-ribbon')).not.toBeAttached();
  await expect(btn).toHaveAttribute('aria-pressed', 'false');
  expect(await freqScope(page)).toBeNull();
});

test('scope: the ribbon shows the full range, not a lone band', async ({ page }) => {
  // Lab feedback (2026-10): zooming to a band left what looked like a stray
  // blue box above the strip. The ribbon's full-range track composited to
  // within a few levels of the card background, so only the scope band
  // showed. Now the track is outlined, carries a faint magnitude trace and
  // its end labels, and a funnel joins the band to the strip below.
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 250, 750);
  await page.getByTestId('freq-nav-scope-btn').click();
  const ribbon = page.getByTestId('freq-nav-ribbon');
  await expect(ribbon).toBeVisible();
  await expect(ribbon.locator('text')).toHaveText(['0', '5000']);   // the fixture's full extent

  // Visible pixels in the track to the RIGHT of the scope band (outside it):
  // the outline, trace and end label must actually show there. Park the
  // pointer first: hovering the toolbar's navigator toggle pops the axis
  // panel over this very region.
  await page.mouse.move(1, 1);
  await expect(page.getByTestId('axis-popover')).toBeHidden();
  const rb = (await ribbon.boundingBox())!;
  const band = (await page.getByTestId('freq-nav-ribbon-band').boundingBox())!;
  const x0 = band.x + band.width + 4;
  const png = await page.screenshot({
    clip: { x: x0, y: rb.y, width: rb.x + rb.width - x0, height: band.height + 2 },
  });
  const bg = await page.getByTestId('freq-nav').evaluate((el) => {
    const m = getComputedStyle(el).backgroundColor.match(/\d+/g)!.map(Number);
    return [m[0], m[1], m[2]] as [number, number, number];
  });
  expect(await inkFraction(page, png, bg)).toBeGreaterThan(0.05);   // pre-fix: 0.00; fixed: ~0.18
});

test('head controls are worded, with distinct names', async ({ page }) => {
  // Lab feedback (2026-10): the bare ‹ › ⤢ glyphs did not say what they did.
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  const nav = page.getByTestId('freq-nav');
  await expect(nav.getByRole('button', { name: 'previous peak' })).toHaveText('‹ peak');
  await expect(nav.getByRole('button', { name: 'next peak' })).toHaveText('peak ›');
  await expect(nav.getByRole('button', { name: 'zoom to band' })).toBeVisible();
});

test('peak-step › keeps the window width and moves it forward', async ({ page }) => {
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 50, 250);                        // width 200, low in the band
  const before = await tfRange(page);
  const width = before.x![1] - before.x![0];
  // The fixture's detected ladder has a mode below the 150 Hz window centre
  // (≈102 Hz) and one above (≈1001 Hz); if impulse.dvma is ever regenerated
  // without that shape, fail HERE clearly instead of as an opaque 30 s
  // click-timeout on a disabled button.
  await expect(page.getByTestId('freq-nav-next')).toBeEnabled();
  await page.getByTestId('freq-nav-next').click();
  const after = await tfRange(page);
  expect(after.x![1] - after.x![0]).toBeCloseTo(width, 3);         // keep-width (structurally exact)
  expect((after.x![0] + after.x![1]) / 2)
    .toBeGreaterThan((before.x![0] + before.x![1]) / 2);           // moved forward
  expect(after.historyLen).toBe(before.historyLen + 1);            // one undo per press
  // And back:
  await expect(page.getByTestId('freq-nav-prev')).toBeEnabled();
  await page.getByTestId('freq-nav-prev').click();
  const back = await tfRange(page);
  expect((back.x![0] + back.x![1]) / 2).toBeLessThan((after.x![0] + after.x![1]) / 2);
});

test('auto-opens in the Fit stage (navigator override unset)', async ({ page }) => {
  await openTf(page);
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Fit' }).click();
  await expect(page.getByTestId('freq-nav')).toBeVisible();
});
