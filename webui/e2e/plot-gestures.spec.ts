import { expect, test, type Page } from '@playwright/test';

/**
 * Plot-gesture e2e (Task 13b). Drives the real `?fixture=1`-mounted plot
 * (impulse.dvma → Time view with lines + a populated legend) with mouse
 * actions and locks in behaviours that previously had NO automated
 * coverage (verified only by manual smoke in Tasks 7 & 8).
 *
 * ZOOM — proves the Task-13b PlotSurface hardening + core Task-7:
 *   - box-zoom narrows the active view's range,
 *   - a pan gesture pushes EXACTLY ONE history entry (A3 coalescing),
 *   - a pan-mode CLICK (no travel) pushes NOTHING (pan dead-zone fix),
 *   - double-click auto-fits (range → null),
 *   - pointercancel aborts a box drag cleanly (band gone, range
 *     unchanged) and a subsequent box-zoom still works (no stranded
 *     state).
 * LEGEND — asserts the already-shipped Task-8 behaviours:
 *   - a row click cycles the tri-state (row + plot line change),
 *   - a drag-on-a-row does NOT cycle,
 *   - dragging across the x=0.5 midline stays left-anchored (no flip),
 *   - the NE / outside-right presets snap the card flush right.
 *
 * Test hook (dev-only, gated on `?fixture=1`): `window.__viewState`
 * exposes the live view-state store so range / history assertions read
 * real state rather than scraping tick labels. See App.svelte.
 */

/** The live view-state store, exposed by App.svelte under ?fixture=1. */
interface ViewSnap {
  range: { x: [number, number] | null; y: [number, number] | null };
  historyLen: number;
  futureLen: number;
}

/** Read the active view's range + history/future lengths from the hook. */
async function snap(page: Page): Promise<ViewSnap> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      current: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('window.__viewState hook missing (need ?fixture=1)');
    let slice: {
      range: { x: [number, number] | null; y: [number, number] | null };
      history: unknown[]; future: unknown[];
    } | null = null;
    const unsub = vs.current.subscribe((v) => { slice = v as typeof slice; });
    unsub();
    if (!slice) throw new Error('view slice unavailable');
    const s = slice as NonNullable<typeof slice>;
    return { range: s.range, historyLen: s.history.length, futureLen: s.future.length };
  });
}

/** Inner data-rect (the `.frame`) in viewport px — the drag target area. */
async function frameBox(page: Page): Promise<{ x: number; y: number; w: number; h: number }> {
  const b = await page.evaluate(() => {
    const f = document.querySelector('[data-testid="plot-svg"] rect.frame') as SVGGraphicsElement | null;
    if (!f) return null;
    const r = f.getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height };
  });
  if (!b) throw new Error('plot frame rect not found');
  return b;
}

/** Set the drag tool via the ZoomToolbar (box ◱ / pan ✥). */
async function setMode(page: Page, mode: 'box' | 'pan'): Promise<void> {
  const title = mode === 'box' ? 'Box zoom — drag a rectangle on the plot' : 'Pan — drag to move the axes';
  await page.getByTitle(title).click();
}

/**
 * Move the legend to the SW corner (bottom-left) via the toolbar popover,
 * clear of the top-right ZoomToolbar which otherwise intercepts clicks on
 * the default NE-placed legend rows.
 */
async function legendToSW(page: Page): Promise<void> {
  await page.getByTitle('Manual axis limits').click();
  await expect(page.getByTestId('axis-popover')).toBeVisible();
  await page.getByTitle('Move legend: SW').click();
  await page.getByTitle('Manual axis limits').click(); // close the popover
  await expect(page.getByTestId('axis-popover')).toHaveCount(0);
}

/** Goto the fixture plot and wait for a real line + a legend entry. */
async function openFixture(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  await expect(page.getByTestId('legend-entry').first()).toBeVisible();
  // The hook is attached synchronously in onMount; make sure it is there.
  await expect.poll(() => page.evaluate(() => !!(window as unknown as { __viewState?: unknown }).__viewState)).toBe(true);
}

test.describe('plot zoom gestures', () => {
  test('box-zoom narrows the active range', async ({ page }) => {
    await openFixture(page);
    const before = await snap(page);
    expect(before.range.x).toBeNull(); // fixture starts auto-fit

    await setMode(page, 'box');
    const f = await frameBox(page);
    // Drag a rectangle well inside the data area (comfortably > 6 px).
    await page.mouse.move(f.x + f.w * 0.3, f.y + f.h * 0.3);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.7, f.y + f.h * 0.7, { steps: 8 });
    await page.mouse.up();

    const after = await snap(page);
    expect(after.range.x).not.toBeNull(); // range now explicit (narrowed)
    expect(after.range.y).not.toBeNull();
    expect(after.historyLen).toBe(before.historyLen + 1); // one commit
  });

  test('a pan gesture pushes exactly ONE history entry (A3 coalescing)', async ({ page }) => {
    await openFixture(page);
    // Establish a non-null range + a history entry via a box-zoom first.
    await setMode(page, 'box');
    const f = await frameBox(page);
    await page.mouse.move(f.x + f.w * 0.25, f.y + f.h * 0.25);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.75, f.y + f.h * 0.75, { steps: 8 });
    await page.mouse.up();
    const zoomed = await snap(page);
    expect(zoomed.range.x).not.toBeNull();

    // Pan once (many intermediate moves → must coalesce to a single commit).
    await setMode(page, 'pan');
    const cx = f.x + f.w * 0.5, cy = f.y + f.h * 0.5;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let i = 1; i <= 10; i++) await page.mouse.move(cx - i * 5, cy - i * 3);
    await page.mouse.up();

    const panned = await snap(page);
    expect(panned.historyLen).toBe(zoomed.historyLen + 1); // exactly one, not ten

    // And Back returns fully to the pre-pan range; Forward re-applies the pan.
    await page.getByTitle('Back (previous axis range)').click();
    const back = await snap(page);
    expect(back.range.x![0]).toBeCloseTo(zoomed.range.x![0], 6);
    expect(back.range.x![1]).toBeCloseTo(zoomed.range.x![1], 6);
    await page.getByTitle('Forward').click();
    const fwd = await snap(page);
    expect(fwd.range.x![0]).toBeCloseTo(panned.range.x![0], 6);
    expect(fwd.range.x![1]).toBeCloseTo(panned.range.x![1], 6);
  });

  test('a pan-mode click (no travel) adds NO history (dead-zone fix)', async ({ page }) => {
    await openFixture(page);
    // Give the pan a real (non-null) range to act on, so a bug would commit.
    await setMode(page, 'box');
    const f = await frameBox(page);
    await page.mouse.move(f.x + f.w * 0.25, f.y + f.h * 0.25);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.75, f.y + f.h * 0.75, { steps: 8 });
    await page.mouse.up();
    const before = await snap(page);

    await setMode(page, 'pan');
    // A pointer down+up with zero movement: a click, not a pan.
    await page.mouse.move(f.x + f.w * 0.5, f.y + f.h * 0.5);
    await page.mouse.down();
    await page.mouse.up();

    const after = await snap(page);
    expect(after.historyLen).toBe(before.historyLen); // nothing pushed
  });

  test('double-click auto-fits the range', async ({ page }) => {
    await openFixture(page);
    // Zoom in first so there is something to reset.
    await setMode(page, 'box');
    const f = await frameBox(page);
    await page.mouse.move(f.x + f.w * 0.3, f.y + f.h * 0.3);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.7, f.y + f.h * 0.7, { steps: 8 });
    await page.mouse.up();
    expect((await snap(page)).range.x).not.toBeNull();

    await page.mouse.dblclick(f.x + f.w * 0.5, f.y + f.h * 0.5);
    const after = await snap(page);
    expect(after.range.x).toBeNull(); // auto-fit
    expect(after.range.y).toBeNull();
  });

  test('pointercancel aborts a box drag cleanly; a later box-zoom still works', async ({ page }) => {
    await openFixture(page);
    const before = await snap(page);

    await setMode(page, 'box');
    const f = await frameBox(page);
    // Start a box drag and paint the rubber band.
    await page.mouse.move(f.x + f.w * 0.3, f.y + f.h * 0.3);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.6, f.y + f.h * 0.6, { steps: 6 });
    await expect(page.getByTestId('rubber-band')).toBeVisible();

    // Fire pointercancel on the capture rect (the browser delivers no
    // pointerup after this). Dispatch a real PointerEvent so the Svelte
    // onpointercancel handler runs; use the active pointerId if we can.
    await page.evaluate(() => {
      const cap = document.querySelector('[data-testid="plot-svg"] rect.capture') as Element | null;
      if (!cap) throw new Error('capture rect not found');
      cap.dispatchEvent(new PointerEvent('pointercancel', { bubbles: true, pointerId: 1 }));
    });
    // Release the physical button so Playwright's mouse state is clean.
    await page.mouse.up();

    // Band gone, range unchanged (no commit).
    await expect(page.getByTestId('rubber-band')).toHaveCount(0);
    const afterCancel = await snap(page);
    expect(afterCancel.range.x).toBe(before.range.x); // both null → unchanged
    expect(afterCancel.historyLen).toBe(before.historyLen);

    // A subsequent normal box-zoom still commits (no stranded state).
    await page.mouse.move(f.x + f.w * 0.35, f.y + f.h * 0.35);
    await page.mouse.down();
    await page.mouse.move(f.x + f.w * 0.65, f.y + f.h * 0.65, { steps: 8 });
    await page.mouse.up();
    const afterZoom = await snap(page);
    expect(afterZoom.range.x).not.toBeNull();
    expect(afterZoom.historyLen).toBe(before.historyLen + 1);
  });
});

test.describe('plot legend gestures', () => {
  test('a row click cycles the tri-state (row + plot line)', async ({ page }) => {
    await openFixture(page);
    await legendToSW(page); // clear of the top-right toolbar so clicks land
    const row = page.getByTestId('legend-entry').first();
    await expect(row).toBeVisible();
    const linesBefore = await page.getByTestId('plot-line').count();
    const rowsBefore = await page.getByTestId('legend-entry').count();

    // on → fade: the row goes to 40% opacity (via the .fade class).
    await row.click();
    await expect(row).toHaveClass(/fade/);
    // fade → off: the row STAYS in the legend (struck-through, .off) so it
    // can be re-enabled — but its plot line is removed (round-2 feedback:
    // off lines must not vanish from the legend).
    await page.getByTestId('legend-entry').first().click();
    await expect(page.getByTestId('legend-entry').first()).toHaveClass(/off/);
    await expect
      .poll(() => page.getByTestId('legend-entry').count())
      .toBe(rowsBefore); // the off entry is still listed
    await expect
      .poll(() => page.getByTestId('plot-line').count())
      .toBeLessThan(linesBefore); // but its plot line was removed
    // off → on: clicking the struck-through row brings the line back.
    await page.getByTestId('legend-entry').first().click();
    await expect(page.getByTestId('legend-entry').first()).not.toHaveClass(/off/);
    await expect
      .poll(() => page.getByTestId('plot-line').count())
      .toBe(linesBefore); // line restored
  });

  test('a drag on a row does NOT cycle it', async ({ page }) => {
    await openFixture(page);
    await legendToSW(page); // clear of the toolbar so the press lands on a row
    const row = page.getByTestId('legend-entry').first();
    await expect(row).toBeVisible();
    const cls = (await row.getAttribute('class')) ?? '';
    const wasFaded = cls.includes('fade');

    const box = await row.boundingBox();
    if (!box) throw new Error('legend row has no box');
    // Press on the row, drag well past the 3 px threshold, release.
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2 + 40, { steps: 8 });
    await page.mouse.up();

    // State unchanged: the card moved instead of cycling the row.
    const clsAfter = (await page.getByTestId('legend-entry').first().getAttribute('class')) ?? '';
    expect(clsAfter.includes('fade')).toBe(wasFaded);
  });

  test('dragging the card across x=0.5 stays left-anchored (no flip)', async ({ page }) => {
    await openFixture(page);
    // Start from SW (bottom-left): a left-anchored position with room to
    // drag rightward across the host midline.
    await legendToSW(page);
    const card = page.getByTestId('legend');
    await expect(card).toBeVisible();
    // Sweep across the LEGEND host's midline (its offsetParent = plot-host),
    // which is where the committed x>0.5 anchor flip would trigger.
    const host = await card.evaluate((el) => {
      const r = (el.offsetParent as HTMLElement).getBoundingClientRect();
      return { x: r.x, y: r.y, w: r.width, h: r.height };
    });

    // Grab the card and press, then promote to a real drag (past the 3 px
    // threshold) BEFORE sampling — until promotion the card still shows its
    // committed placement.
    const cb0 = await card.boundingBox();
    if (!cb0) throw new Error('legend card has no box');
    const startX = cb0.x + 12, startY = cb0.y + 12;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 8, startY, { steps: 2 }); // promote to drag
    await expect(card).toHaveClass(/dragging/);

    const hostMid = host.x + host.w * 0.5;
    let lastLeft = -Infinity;
    let monotonic = true;
    // Sweep from left of centre to right of centre, sampling the card's
    // left offset each step. The INLINE `left` (Svelte's `style:left`) must
    // stay a real length string (never 'auto') and its computed px must move
    // monotonically with the cursor — a mid-drag anchor flip would swap
    // inline left→'auto' and jump the card by ~its own width.
    for (let i = 0; i <= 12; i++) {
      const tx = hostMid - host.w * 0.3 + (i / 12) * host.w * 0.6;
      await page.mouse.move(tx, startY, { steps: 2 });
      const s = await card.evaluate((el) => ({
        inlineLeft: (el as HTMLElement).style.left,
        computedLeftPx: parseFloat(getComputedStyle(el).left),
      }));
      expect(s.inlineLeft).not.toBe('auto'); // stays left-anchored throughout
      if (s.computedLeftPx + 0.5 < lastLeft) monotonic = false; // allow clamp jitter
      lastLeft = s.computedLeftPx;
    }
    await page.mouse.up();
    expect(monotonic).toBe(true);
  });

  test('presets snap the legend flush (NE / outside-right)', async ({ page }) => {
    await openFixture(page);
    // Open the ⋯ popover and click the NE preset.
    await page.getByTitle('Manual axis limits').click();
    await expect(page.getByTestId('axis-popover')).toBeVisible();
    await page.getByTitle('Move legend: NE').click();

    const card = page.getByTestId('legend');
    // NE → right-anchored flush. Read the INLINE style for the anchor flag
    // (Svelte's `style:left` sets the keyword 'auto'; getComputedStyle would
    // resolve it to a used px value), and computed `right` for the fraction.
    const ne = await card.evaluate((el) => {
      const host = (el.offsetParent as HTMLElement).getBoundingClientRect();
      return {
        inlineLeft: (el as HTMLElement).style.left,
        rightPx: parseFloat(getComputedStyle(el).right),
        hostW: host.width,
      };
    });
    expect(ne.inlineLeft).toBe('auto');            // right-anchored, not left
    expect(ne.rightPx).toBeGreaterThan(0);         // inside the plot
    expect(ne.rightPx / ne.hostW).toBeLessThan(0.05); // flush to the right edge

    // outside-right → the card sits JUST PAST the right edge: its right
    // offset goes negative (right = (1 - 1.02)*100% = -2% of host).
    await page.getByTitle('Move legend: Out ▸').click();
    const out = await card.evaluate((el) => ({
      inlineLeft: (el as HTMLElement).style.left,
      rightPx: parseFloat(getComputedStyle(el).right),
    }));
    expect(out.inlineLeft).toBe('auto');
    expect(out.rightPx).toBeLessThan(0);           // past the right edge
    expect(out.rightPx).toBeLessThan(ne.rightPx);  // further right than NE
  });
});
