import { expect, test } from '@playwright/test';

/**
 * Wave-A Task A2 — per-set calibration. Non-@engine: exercises the tray
 * Calibrate dialog + the display-time cal seam on the checked-in 2-channel
 * fixture (`?fixture=1`), no pyodide compute needed (the Time view draws the
 * decoded lines immediately on load and the cal factor is applied in
 * `buildPlotModel`, not the worker).
 *
 * Asserts:
 *   - the tray card's Calibrate button opens a per-set dialog with one row per
 *     channel, the four preset units, a preserved non-standard unit ('m/s' on
 *     the fixture's ch1), and the disabled known-input button;
 *   - entering a sensitivity and hitting Apply scales the plotted amplitude:
 *     both channels get sensitivity 0.1 → cal factor 10, so the auto-fit
 *     y-axis tick magnitudes grow ~10× (the display-time cal, applied to the
 *     time trace, is visible on the axis).
 *
 * Persistence is covered by the vitest codec round-trip (writeDvma → readDvma
 * preserves the edited channel_cal_factors); a full autosave/restore reload is
 * not cheap in headless e2e (IndexedDB + File System Access permission), so it
 * is intentionally left to the unit layer.
 */

const card0 = (page: import('@playwright/test').Page) => page.getByTestId('tray-card-0');

/** Largest |value| among the auto-fit y-axis tick labels (text-anchor="end"). */
async function yTickMaxAbs(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => {
    const svg = document.querySelector('[data-testid="plot-svg"]');
    if (!svg) return 0;
    const vals = [...svg.querySelectorAll('text.tick')]
      .filter((t) => t.getAttribute('text-anchor') === 'end')
      .map((t) => parseFloat((t.textContent ?? '').trim()))
      .filter((n) => Number.isFinite(n))
      .map(Math.abs);
    return vals.length ? Math.max(...vals) : 0;
  });
}

test('Calibrate dialog opens per set with channel rows, preset + preserved units', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  // The Calibrate button is revealed on card hover (like the delete ×).
  await card.hover();
  const calBtn = card.getByTestId('cal-open');
  await expect(calBtn).toBeVisible();
  await calBtn.click();

  // Dialog is up with one row per channel and the channels' labels.
  const overlay = page.getByTestId('cal-overlay');
  await expect(overlay).toBeVisible();
  await expect(overlay.getByTestId('cal-row-0')).toBeVisible();
  await expect(overlay.getByTestId('cal-row-1')).toBeVisible();

  // ch0's stored unit ('N') is a preset → exactly the four preset options.
  const unit0 = overlay.getByTestId('cal-unit-0');
  const opts0 = await unit0.evaluate((el) => [...(el as HTMLSelectElement).options].map((o) => o.value));
  expect(opts0).toEqual(['V', 'm/s²', 'N', 'Pa']);
  // ch1's stored unit ('m/s') is NOT a preset → preserved, prepended as an
  // extra option so Apply never silently rewrites it.
  const unit1 = overlay.getByTestId('cal-unit-1');
  const opts1 = await unit1.evaluate((el) => [...(el as HTMLSelectElement).options].map((o) => o.value));
  expect(opts1).toEqual(['m/s', 'V', 'm/s²', 'N', 'Pa']);
  await expect(unit1).toHaveValue('m/s');

  // The known-input calibration button is present but disabled (roadmap stub).
  await expect(overlay.getByRole('button', { name: /known-input calibration/i })).toBeDisabled();

  // Cancel closes without applying.
  await overlay.getByTestId('cal-cancel').click();
  await expect(overlay).toBeHidden();
});

test('Apply a sensitivity → the time-view amplitude scales (display-time cal)', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();
  await expect(page.getByTestId('plot-line').first()).toBeVisible();

  // Baseline auto-fit y-axis magnitude (Time view, drawn on load).
  const before = await yTickMaxAbs(page);
  expect(before).toBeGreaterThan(0);

  // Open the dialog and give BOTH channels sensitivity 0.1 (→ cal factor 10).
  await card.hover();
  await card.getByTestId('cal-open').click();
  const overlay = page.getByTestId('cal-overlay');
  await expect(overlay).toBeVisible();
  await overlay.getByTestId('cal-sens-0').fill('0.1');
  await overlay.getByTestId('cal-sens-1').fill('0.1');
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();

  // The plotted trace is now ×10, so the auto-fit y-axis magnitude grows.
  await expect.poll(() => yTickMaxAbs(page), { timeout: 5_000 })
    .toBeGreaterThan(before * 3);
});
