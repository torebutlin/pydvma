import { expect, test } from '@playwright/test';

/**
 * @engine — R3 log/lin axis toggles on the Frequency view. Loads the
 * checked-in impulse.dvma via `?fixture=1`, runs Calc FFT through the
 * real pyodide worker (needed: the toggles are only meaningful once a
 * frequency spectrum exists), then exercises the toolbar's x (lin↔log)
 * and y (dB↔lin) segmented toggles:
 *
 *  - x → log makes the x-axis tick labels DECADES (powers of ten) where
 *    a linear axis showed 1-2-5 "nice" values.
 *  - y → lin changes the y-axis LABEL from "Magnitude (dB)" to
 *    "Magnitude" (a model change, not just an axis re-scale).
 *
 * SLOW: the first Calc FFT pays the full pyodide boot. Tagged `@engine`
 * so it runs/skips with the other engine tests.
 */
const stage = (name: string) => `nav[aria-label="stages"] button:has-text("${name}")`;

/** x-axis tick label texts (the .tick <text> under the plot, bottom axis). */
async function xTickLabels(page: import('@playwright/test').Page): Promise<string[]> {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="plot-svg"]');
    if (!svg) return [];
    // Bottom-axis ticks are text-anchor="middle"; y-axis ticks are "end".
    return [...svg.querySelectorAll('text.tick')]
      .filter((t) => t.getAttribute('text-anchor') === 'middle')
      .map((t) => (t.textContent ?? '').trim())
      .filter(Boolean);
  });
}

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('Frequency → Calc FFT, then x lin↔log and y dB↔lin toggles change ticks + label', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Frequency stage, run the FFT (boots the engine on first compute).
    await page.locator(stage('Freq')).click();
    await page.getByRole('button', { name: 'Calc FFT' }).click();
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    // Default axis label is dB.
    const yLabel = page.locator('[data-testid="plot-svg"] text.axlab').nth(1); // rotated y-label
    await expect(yLabel).toHaveText('Magnitude (dB)');

    // Linear-x ticks: 1-2-5 nice values — NOT strictly powers of ten.
    const linTicks = await xTickLabels(page);
    expect(linTicks.length).toBeGreaterThan(2);

    // Toggle x → log. Ticks become decades (each numeric label is a power of ten).
    await page.getByTestId('xscale-toggle').getByRole('button', { name: 'log' }).click();
    await expect.poll(async () => {
      const ticks = (await xTickLabels(page)).map(Number).filter((n) => Number.isFinite(n) && n > 0);
      if (ticks.length < 2) return false;
      return ticks.every((v) => {
        const e = Math.log10(v);
        return Math.abs(e - Math.round(e)) < 1e-6;   // integer power of ten
      });
    }, { timeout: 10_000 }).toBe(true);

    // Toggle y → lin. The magnitude label drops the "(dB)".
    await page.getByTestId('yscale-toggle').getByRole('button', { name: 'lin' }).click();
    await expect(yLabel).toHaveText('Magnitude');

    // Toggle both back and confirm the round-trip.
    await page.getByTestId('yscale-toggle').getByRole('button', { name: 'dB' }).click();
    await expect(yLabel).toHaveText('Magnitude (dB)');
    await page.getByTestId('xscale-toggle').getByRole('button', { name: 'lin' }).click();
    await expect.poll(async () => {
      const ticks = (await xTickLabels(page)).map(Number).filter((n) => Number.isFinite(n));
      // A linear axis over this data includes at least one non-power-of-ten
      // tick (e.g. 0 or a 1-2-5 value that isn't a decade edge).
      return ticks.some((v) => {
        if (v <= 0) return true;
        const e = Math.log10(v);
        return Math.abs(e - Math.round(e)) > 1e-6;
      });
    }, { timeout: 10_000 }).toBe(true);
  });

  test('box-zoom on a LOG-x frequency axis commits a positive, narrowed x-range', async ({ page }) => {
    // R3 follow-up: the gesture maths runs in LOG space on x then exponentiates
    // the committed range. This asserts a real drag on a log axis commits a
    // sane range — both bounds > 0 (10^v can never be ≤0) and narrower than the
    // full extent — the one path the R2+R3 review flagged as untested.
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await page.locator(stage('Freq')).click();
    await page.getByRole('button', { name: 'Calc FFT' }).click();
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    await page.getByTestId('xscale-toggle').getByRole('button', { name: 'log' }).click();
    await expect.poll(() => page.evaluate(
      () => !!(window as unknown as { __viewState?: unknown }).__viewState,
    )).toBe(true);

    /** Active view's committed x-range, read via the ?fixture=1 hook. */
    const rangeX = () => page.evaluate(() => new Promise<[number, number] | null>((res) => {
      const vs = (window as unknown as { __viewState?: {
        current: { subscribe: (f: (v: { range: { x: [number, number] | null } }) => void) => () => void };
      } }).__viewState!;
      const unsub = vs.current.subscribe((v) => res(v.range.x));
      unsub();
    }));

    expect(await rangeX()).toBeNull();   // starts auto-fit

    const frame = await page.evaluate(() => {
      const f = document.querySelector('[data-testid="plot-svg"] rect.frame') as SVGGraphicsElement | null;
      if (!f) return null;
      const b = f.getBoundingClientRect();
      return { x: b.x, y: b.y, w: b.width, h: b.height };
    });
    expect(frame).not.toBeNull();

    // Drag a rectangle in the RIGHT portion of the log axis (higher, all-positive
    // frequencies) — comfortably larger than the 6 px click dead-zone.
    await page.mouse.move(frame!.x + frame!.w * 0.5, frame!.y + frame!.h * 0.3);
    await page.mouse.down();
    await page.mouse.move(frame!.x + frame!.w * 0.85, frame!.y + frame!.h * 0.7, { steps: 8 });
    await page.mouse.up();

    const after = await rangeX();
    expect(after).not.toBeNull();
    expect(after![0]).toBeGreaterThan(0);          // log commit is always positive
    expect(after![1]).toBeGreaterThan(after![0]);  // a proper (lo < hi) band
  });
});
