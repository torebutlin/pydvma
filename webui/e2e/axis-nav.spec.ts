import { expect, test, type Page } from '@playwright/test';

/**
 * Round-5 axis-navigation for the special TF plot contexts (items 4-6).
 * NON-ENGINE: `?fixture=1` seeds a TfData (+ coherence) on load, so the TF
 * view has a real transfer function WITHOUT booting pyodide — every assertion
 * here reads that seeded TF. Covers:
 *   4. Nyquist — the x/y controls mean Real/Imag (drive `nyquistRange`, not the
 *      frequency window); a `freq` group + the magnitude brush both scrub the
 *      shared committed frequency range through the history mechanism.
 *   5. Bode   — the phase pane owns its y (`phaseRange`, default ±180° lock); a
 *      phase-pane box-zoom moves shared x + phase y in ONE undo step and leaves
 *      the magnitude pane's y untouched.
 *   6. Coherence — the right axis gets an auto | 0–1 control (drives
 *      `coherenceAuto`) in the expanded panel.
 *
 * Reads live state via the `?fixture=1` `window.__viewState` hook (App.svelte).
 */

interface TfSlice {
  range: { x: [number, number] | null; y: [number, number] | null };
  nyquistRange: { x: [number, number] | null; y: [number, number] | null };
  phaseRange: { x: [number, number] | null; y: [number, number] | null };
  coherenceAuto: boolean;
  historyLen: number;
}

/** Read the active (tf) view slice through the dev hook. */
async function tfSlice(page: Page): Promise<TfSlice> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      current: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('window.__viewState hook missing (need ?fixture=1)');
    let raw: {
      range: TfSlice['range']; nyquistRange: TfSlice['nyquistRange'];
      phaseRange: TfSlice['phaseRange']; coherenceAuto: boolean; history: unknown[];
    } | null = null;
    const unsub = vs.current.subscribe((v) => { raw = v as typeof raw; });
    unsub();
    if (!raw) throw new Error('view slice unavailable');
    const s = raw as NonNullable<typeof raw>;
    return {
      range: s.range, nyquistRange: s.nyquistRange, phaseRange: s.phaseRange,
      coherenceAuto: s.coherenceAuto, historyLen: s.history.length,
    };
  });
}

/** Load the fixture and switch to the TF stage (seeded TF, no engine). */
async function openTf(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  // The seeded TF renders a line with no Calc.
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  await expect.poll(() => page.evaluate(() => !!(window as unknown as { __viewState?: unknown }).__viewState)).toBe(true);
}

/** Hover the zoom toolbar to reveal its expanded panel. */
async function openPanel(page: Page): Promise<void> {
  await page.getByTestId('zoom-toolbar').hover();
  await expect(page.getByTestId('axis-popover')).toBeVisible();
}
async function closePanel(page: Page): Promise<void> {
  await page.mouse.move(6, 560);
  await expect(page.getByTestId('axis-popover')).toHaveCount(0);
}

test.describe('Nyquist axis navigation (item 4)', () => {
  test('x/y controls relabel Real/Imag; a linked freq group + Auto Re/Im appear', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    await expect(page.getByTestId('freq-nav')).toBeVisible();

    // Auto buttons relabel for the Real/Imag axes.
    await expect(page.getByRole('button', { name: 'Auto Re' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Auto Im' })).toBeVisible();

    await openPanel(page);
    // The limit groups now mean Real/Imag, plus a bordered freq group.
    await expect(page.getByLabel('Real min')).toBeVisible();
    await expect(page.getByLabel('Imag max')).toBeVisible();
    await expect(page.getByTestId('nyquist-freq-group')).toBeVisible();
    await expect(page.getByLabel('Frequency min')).toBeVisible();
  });

  test('the freq group commits the shared frequency window (range.x)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    await openPanel(page);

    await page.getByLabel('Frequency min').fill('200');
    await page.getByLabel('Frequency max').fill('800');
    // Debounced commit lands on range.x (the same range Calc/Fit read).
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([200, 800]);
  });

  test('Real/Imag limits drive nyquistRange (NOT the frequency window)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    // Pin a freq window first so we can prove the Real/Imag edit leaves it alone.
    await openPanel(page);
    await page.getByLabel('Frequency min').fill('100');
    await page.getByLabel('Frequency max').fill('900');
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([100, 900]);

    await page.getByLabel('Real min').fill('-1');
    await page.getByLabel('Real max').fill('1');
    await page.getByLabel('Imag min').fill('-2');
    await page.getByLabel('Imag max').fill('2');
    await expect.poll(async () => (await tfSlice(page)).nyquistRange, { timeout: 4000 })
      .toEqual({ x: [-1, 1], y: [-2, 2] });
    // The frequency window is untouched by the Real/Imag edit.
    expect((await tfSlice(page)).range.x).toEqual([100, 900]);

    // Auto Re resets just the Real axis to auto-fit; Imag stays pinned.
    await page.getByRole('button', { name: 'Auto Re' }).click();
    await expect.poll(async () => (await tfSlice(page)).nyquistRange.x).toBeNull();
    expect((await tfSlice(page)).nyquistRange.y).toEqual([-2, 2]);
  });

  test('dragging the brush band scrubs the committed freq window (one history step)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    // Narrow to a sub-band so the band is draggable (not full-width).
    await openPanel(page);
    await page.getByLabel('Frequency min').fill('400');
    await page.getByLabel('Frequency max').fill('900');
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([400, 900]);
    await closePanel(page);

    const before = await tfSlice(page);
    const band = page.getByTestId('freq-nav-band');
    const bb = await band.boundingBox();
    if (!bb) throw new Error('brush band has no box');
    // Drag the band leftward → lower frequencies.
    await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2);
    await page.mouse.down();
    await page.mouse.move(bb.x + bb.width / 2 - 40, bb.y + bb.height / 2, { steps: 8 });
    await page.mouse.up();

    const after = await tfSlice(page);
    expect(after.range.x).not.toBeNull();
    expect(after.range.x![0]).toBeLessThan(before.range.x![0]);   // translated to lower freq
    expect(after.historyLen).toBe(before.historyLen + 1);         // exactly one commit
  });

  test('the brush numeric min/max fields commit the shared freq window (item 6b)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    await expect(page.getByTestId('freq-nav')).toBeVisible();

    // Typing a min then a max (each committed on Enter) lands on range.x — the
    // SAME window Calc/Fit read — same as dragging the band, but exact.
    await page.getByTestId('freq-nav-min').fill('250');
    await page.getByTestId('freq-nav-min').press('Enter');
    await page.getByTestId('freq-nav-max').fill('750');
    await page.getByTestId('freq-nav-max').press('Enter');
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([250, 750]);
  });

  test('dragging the brush band re-windows LIVE and records ONE history step (item 6c)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    // Narrow to a sub-band so the body is draggable (not full width).
    await openPanel(page);
    await page.getByLabel('Frequency min').fill('400');
    await page.getByLabel('Frequency max').fill('900');
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([400, 900]);
    await closePanel(page);

    const before = await tfSlice(page);
    const band = page.getByTestId('freq-nav-band');
    const bb = await band.boundingBox();
    if (!bb) throw new Error('brush band has no box');
    // Press and move the band leftward WITHOUT releasing yet.
    await page.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2);
    await page.mouse.down();
    await page.mouse.move(bb.x + bb.width / 2 - 30, bb.y + bb.height / 2, { steps: 8 });

    // LIVE: the committed window has ALREADY moved to lower frequencies mid-drag…
    await expect
      .poll(async () => (await tfSlice(page)).range.x![0], { timeout: 2000 })
      .toBeLessThan(before.range.x![0]);
    // …but no history was pushed yet (the live frames are transient).
    expect((await tfSlice(page)).historyLen).toBe(before.historyLen);

    await page.mouse.up();
    // The whole gesture commits exactly ONE undo step.
    await expect.poll(async () => (await tfSlice(page)).historyLen).toBe(before.historyLen + 1);
    const after = await tfSlice(page);
    expect(after.range.x![0]).toBeLessThan(before.range.x![0]);

    // A single Undo returns straight to the pre-drag window (past all live frames).
    await page.getByTitle('Undo view change (previous axis range)').click();
    await expect.poll(async () => (await tfSlice(page)).range.x).toEqual([400, 900]);
  });

  test('double-clicking the brush strip resets to the full frequency range', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('nyquist');
    await openPanel(page);
    await page.getByLabel('Frequency min').fill('400');
    await page.getByLabel('Frequency max').fill('600');
    await expect.poll(async () => (await tfSlice(page)).range.x, { timeout: 4000 }).toEqual([400, 600]);
    await closePanel(page);

    await page.locator('[data-testid="freq-nav"] svg').dblclick();
    // The committed window widens well past the narrow [400,600] we set.
    await expect.poll(async () => {
      const r = (await tfSlice(page)).range.x;
      return r ? r[1] - r[0] : 0;
    }, { timeout: 4000 }).toBeGreaterThan(300);
  });
});

test.describe('Bode two-pane axis navigation (item 5)', () => {
  test('phase pane gets its own y control (auto | ±180° lock)', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('bode');
    await expect(page.locator('.bode-pane')).toHaveCount(2);

    await openPanel(page);
    await expect(page.getByTestId('phase-y-control')).toBeVisible();

    // Default is the ±180° lock.
    expect((await tfSlice(page)).phaseRange.y).toEqual([-180, 180]);
    await page.getByTestId('phase-y-toggle').getByRole('button', { name: 'auto' }).click();
    await expect.poll(async () => (await tfSlice(page)).phaseRange.y).toBeNull();
    await page.getByTestId('phase-y-toggle').getByRole('button', { name: '±180°' }).click();
    await expect.poll(async () => (await tfSlice(page)).phaseRange.y).toEqual([-180, 180]);
  });

  test('a phase-pane box-zoom moves shared x + phase y in ONE step, preserving magnitude y', async ({ page }) => {
    await openTf(page);
    await page.getByLabel('plot type').selectOption('bode');
    await expect(page.locator('.bode-pane')).toHaveCount(2);

    // Give the magnitude pane an explicit y so we can prove it survives.
    await page.evaluate(() => (window as unknown as {
      __viewState: { setRange: (id: string, r: unknown) => void };
    }).__viewState.setRange('tf', { x: null, y: [-50, 20] }));

    const before = await tfSlice(page);
    // Box-zoom inside the PHASE pane (the second bode-pane).
    const frame = await page.evaluate(() => {
      const panes = document.querySelectorAll('.bode-pane');
      const f = panes[1]?.querySelector('[data-testid="plot-svg"] rect.frame') as SVGGraphicsElement | null;
      if (!f) return null;
      const b = f.getBoundingClientRect();
      return { x: b.x, y: b.y, w: b.width, h: b.height };
    });
    if (!frame) throw new Error('phase pane frame not found');

    await page.mouse.move(frame.x + frame.w * 0.3, frame.y + frame.h * 0.3);
    await page.mouse.down();
    await page.mouse.move(frame.x + frame.w * 0.7, frame.y + frame.h * 0.7, { steps: 8 });
    await page.mouse.up();

    const after = await tfSlice(page);
    expect(after.range.y).toEqual([-50, 20]);                    // magnitude y untouched
    expect(after.range.x).not.toBeNull();                        // shared frequency x zoomed
    expect(after.phaseRange.y).not.toEqual([-180, 180]);         // phase axis zoomed
    expect(after.phaseRange.y).not.toBeNull();
    expect(after.historyLen).toBe(before.historyLen + 1);        // one undo step

    // A single Undo reverts BOTH the shared x and the phase y together.
    await page.getByTitle('Undo view change (previous axis range)').click();
    const undone = await tfSlice(page);
    expect(undone.range.x).toBeNull();
    expect(undone.phaseRange.y).toEqual([-180, 180]);
  });
});

test.describe('Coherence overlay axis control (item 6)', () => {
  test('the coherence right axis gets an auto | 0–1 control in the panel', async ({ page }) => {
    await openTf(page);
    // Default TF plotType is magnitude with the coherence overlay on.
    await openPanel(page);
    const ctl = page.getByTestId('coherence-control');
    await expect(ctl).toBeVisible();

    expect((await tfSlice(page)).coherenceAuto).toBe(false);      // default fixed [0,1]
    await page.getByTestId('coherence-toggle').getByRole('button', { name: 'auto' }).click();
    await expect.poll(async () => (await tfSlice(page)).coherenceAuto).toBe(true);
    // Back to the fixed 0–1 axis (first segmented button).
    await page.getByTestId('coherence-toggle').getByRole('button').first().click();
    await expect.poll(async () => (await tfSlice(page)).coherenceAuto).toBe(false);
  });
});
