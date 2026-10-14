import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';

/**
 * Wave-A Task A2 — per-set calibration. Non-@engine: exercises the tray
 * Calibrate dialog + the display-time cal seam on the checked-in 2-channel
 * fixture (`?fixture=1`), no pyodide compute needed (the Time view draws the
 * decoded lines immediately on load and the cal factor is applied in
 * `buildPlotModel`, not the worker).
 *
 * Asserts:
 *   - the tray card's Calibrate button opens a per-set dialog with one row per
 *     channel, the preset units with each channel's stored unit selected, and
 *     the disabled known-input button;
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

  // Both stored units ('N', 'm/s') are presets → exactly the preset options,
  // each channel's own unit selected. (A non-preset stored unit is prepended
  // instead, so Apply never silently rewrites it — `unitOptions`.)
  const presets = ['V', 'm', 'm/s', 'm/s²', 'N', 'Pa'];
  const unit0 = overlay.getByTestId('cal-unit-0');
  const opts0 = await unit0.evaluate((el) => [...(el as HTMLSelectElement).options].map((o) => o.value));
  expect(opts0).toEqual(presets);
  await expect(unit0).toHaveValue('N');
  const unit1 = overlay.getByTestId('cal-unit-1');
  const opts1 = await unit1.evaluate((el) => [...(el as HTMLSelectElement).options].map((o) => o.value));
  expect(opts1).toEqual(presets);
  await expect(unit1).toHaveValue('m/s');

  // The fixture carries its TF, uncalibrated: the TF line follows the
  // channel ratio (blank factor) and its unit pickers sit on the channels'.
  const tf = overlay.getByTestId('cal-tf-section');
  await expect(tf).toBeVisible();
  await expect(tf.getByTestId('cal-tf-factor-1')).toHaveValue('');
  await expect(tf.getByTestId('cal-tf-num-1')).toHaveValue('m/s');
  await expect(tf.getByTestId('cal-tf-den-1')).toHaveValue('N');
  await expect(tf.getByTestId('cal-tf-num-1')).toBeDisabled();

  // The known-input calibration button is present but disabled (roadmap stub).
  await expect(overlay.getByRole('button', { name: /known-input calibration/i })).toBeDisabled();

  // Cancel closes without applying.
  await overlay.getByTestId('cal-cancel').click();
  await expect(overlay).toBeHidden();
});

test('a set with no TF yet says how to calibrate its transfer function', async ({ page }) => {
  await page.goto('/?fixture=3ch');
  await expect(card0(page)).toBeVisible();
  await card0(page).hover();
  await card0(page).getByTestId('cal-open').click();
  const overlay = page.getByTestId('cal-overlay');
  await expect(overlay.getByTestId('cal-tf-section')).toHaveCount(0);
  await expect(overlay.getByTestId('cal-tf-pending')).toBeVisible();
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

// ---- Transfer-function calibration --------------------------------------- //
//
// `tf_cal_python.dvma` is a 2-channel NI capture (volts, uncalibrated) plus
// its TF, calibrated the way a notebook does it — written by pydvma itself:
//
//   ds.tf_data_list.set_calibration_factor(7.0, units=('m/s', 'N'))
//   container.save(ds, 'webui/tests/fixtures/tf_cal_python.dvma')
//
// so loading it checks that the app honours a python-set TF factor, and the
// dialog then edits it. Non-@engine: the TF comes off disk, nothing computes.

function fixturePath(name: string): string {
  return fileURLToPath(new URL(`../tests/fixtures/${name}`, import.meta.url));
}

async function loadFile(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

const yLabel = (page: Page) => page.locator('[data-testid="plot-svg"] text.axlab').nth(1);

async function openCalibrate(page: Page) {
  const card = card0(page);
  await card.hover();
  await card.getByTestId('cal-open').click();
  const overlay = page.getByTestId('cal-overlay');
  await expect(overlay).toBeVisible();
  return overlay;
}

test('a TF factor set in python shows, edits, and resets in the Calibrate dialog', async ({ page }) => {
  await page.goto('/');
  await loadFile(page, fixturePath('tf_cal_python.dvma'));
  await expect(card0(page)).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();

  // The stored factor is honoured, and so is its unit.
  await expect(yLabel(page)).toHaveText('|H| ((m/s)/N, dB)');

  let overlay = await openCalibrate(page);
  // Channel rows stay (the sensors are uncalibrated volts)...
  await expect(overlay.getByTestId('cal-row-0')).toBeVisible();
  // ...and the TF line carries the python factor and unit.
  const section = overlay.getByTestId('cal-tf-section');
  await expect(section).toBeVisible();
  await expect(section.getByTestId('cal-tf-row-1')).toContainText('ch_1/ch_0');
  await expect(section.getByTestId('cal-tf-factor-1')).toHaveValue('7');
  await expect(section.getByTestId('cal-tf-num-1')).toHaveValue('m/s');
  await expect(section.getByTestId('cal-tf-den-1')).toHaveValue('N');

  // A typo cannot be applied.
  await section.getByTestId('cal-tf-factor-1').fill('7x');
  await expect(overlay.getByTestId('cal-apply')).toBeDisabled();

  // A new factor and unit: the axis follows the unit.
  await section.getByTestId('cal-tf-factor-1').fill('14');
  await section.getByTestId('cal-tf-num-1').selectOption('m/s²');
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();
  await expect(yLabel(page)).toHaveText('|H| ((m/s²)/N, dB)');

  overlay = await openCalibrate(page);
  await expect(overlay.getByTestId('cal-tf-factor-1')).toHaveValue('14');

  // ↺ goes back to the channel calibration: blank factor showing the
  // channel ratio as its placeholder, unit pickers on the channel units.
  await overlay.getByTestId('cal-tf-reset-1').click();
  await expect(overlay.getByTestId('cal-tf-factor-1')).toHaveValue('');
  await expect(overlay.getByTestId('cal-tf-factor-1')).toHaveAttribute('placeholder', '1');
  await expect(overlay.getByTestId('cal-tf-num-1')).toHaveValue('V');
  await expect(overlay.getByTestId('cal-tf-num-1')).toBeDisabled();
  await overlay.getByTestId('cal-apply').click();
  // An NI capture's channels really are volts, so the ratio reads V/V.
  await expect(yLabel(page)).toHaveText('|H| (V/V, dB)');
});

test('a TF factor scales the TF line without touching the time view', async ({ page }) => {
  await page.goto('/');
  await loadFile(page, fixturePath('tf_cal_python.dvma'));
  await expect(card0(page)).toBeVisible();
  // Time view first: its scale must not move when the TF is calibrated.
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  const timeBefore = await yTickMaxAbs(page);

  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await page.getByLabel('coherence overlay').uncheck();
  // Linear magnitude, so the tick labels scale with the factor.
  await page.getByTestId('yscale-toggle').getByRole('button', { name: 'lin' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();
  const tfBefore = await yTickMaxAbs(page);
  expect(tfBefore).toBeGreaterThan(0);

  const overlay = await openCalibrate(page);
  await overlay.getByTestId('cal-tf-factor-1').fill('700');   // ×100 on the stored 7
  await overlay.getByTestId('cal-apply').click();
  await expect.poll(() => yTickMaxAbs(page), { timeout: 5_000 }).toBeGreaterThan(tfBefore * 30);

  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Time' }).click();
  await expect.poll(() => yTickMaxAbs(page), { timeout: 5_000 }).toBe(timeBefore);
});
