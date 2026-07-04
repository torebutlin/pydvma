import { expect, test } from '@playwright/test';

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
});
