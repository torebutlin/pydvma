import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { writeDvma } from '../src/lib/codec/dvma';

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
 *     a ref tone button on each channel row;
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

  // Each channel row offers the reference-tone step.
  await expect(overlay.getByTestId('cal-ref-0')).toBeVisible();
  await expect(overlay.getByTestId('cal-ref-1')).toBeVisible();

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

// ---- Calibration provenance ---------------------------------------------- //

test('the dialog offers a calibration note field', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();
  await card.hover();
  await card.getByTestId('cal-open').click();
  const overlay = page.getByTestId('cal-overlay');
  await overlay.getByTestId('cal-note').fill('spec sheet');
  await overlay.getByTestId('cal-sens-0').fill('0.1');
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();
});

test('a recording that does not name its device cannot carry its calibration', async ({ page }) => {
  // The fixture's settings say only device_driver 'soundcard': no capture is
  // ever filed under that, so the tick is replaced by a note.
  await page.goto('/?fixture=1');
  await expect(card0(page)).toBeVisible();
  const overlay = await openCalibrate(page);
  await expect(overlay.getByTestId('cal-carry-unavailable')).toContainText('does not name its device');
  await expect(overlay.getByTestId('cal-carry')).toHaveCount(0);
});

test('"use for new recordings too" is unticked by default and, ticked, keeps every calibrated channel', async ({ page }) => {
  await page.goto('/');
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  await (await chooserPromise).setFiles(
    toneDvma(0.03, { device_name: 'Audient iD44', device_driver: 'soundcard' }, 'named.dvma'));
  await expect(card0(page)).toBeVisible();
  const key = 'pydvma.carriedCal.v1';
  const stored = async () => JSON.parse(await page.evaluate((k) => localStorage.getItem(k) ?? 'null', key));

  // Ticked on an uncalibrated recording: nothing to carry, and it says so.
  let overlay = await openCalibrate(page);
  await expect(overlay.getByTestId('cal-carry')).not.toBeChecked();
  await overlay.getByTestId('cal-carry').check();
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();
  await expect(page.getByText('nothing to carry: no channel is calibrated')).toBeVisible();
  expect(await stored()).toBeNull();

  // Unticked (the default each time): calibrating keeps nothing for new recordings.
  overlay = await openCalibrate(page);
  await expect(overlay.getByTestId('cal-carry')).not.toBeChecked();
  await overlay.getByTestId('cal-sens-0').fill('0.0335');
  await overlay.getByTestId('cal-unit-0').selectOption('Pa');
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();
  expect(await stored()).toBeNull();

  // Ticked with no edit: the calibrated channel is carried, with its saved
  // provenance and the units it is per (this file states no full scale: FS).
  overlay = await openCalibrate(page);
  await overlay.getByTestId('cal-carry').check();
  await overlay.getByTestId('cal-apply').click();
  await expect(overlay).toBeHidden();
  const kept = await stored();
  expect(Object.keys(kept)).toEqual(['Audient iD44']);
  expect(kept['Audient iD44']['0']).toMatchObject({ sensitivity: 0.0335, unit: 'Pa', basis: 'FS' });
  expect(kept['Audient iD44']['0'].provenance).toMatchObject({ method: 'sensitivity', carried: false });
});

test('Setup says what the selected device carries, and clear stops it', async ({ page }) => {
  // A calibration carried for browser captures from the Default row, which
  // are filed under their driver, 'web_audio'. Visiting Setup only
  // enumerates devices; nothing is opened.
  const provenance = {
    method: 'sensitivity', date: '2026-11-06T10:00:00.000Z', sensitivity: 0.0335, unit: 'Pa',
    reference: null, gain_db: null, input_mode: null, pad: null, device: null, note: '', carried: false,
  };
  await page.addInitScript((value) => {
    if (!sessionStorage.getItem('seeded')) {
      localStorage.setItem('pydvma.carriedCal.v1', value);
      sessionStorage.setItem('seeded', '1');
    }
  }, JSON.stringify({ web_audio: {
    0: { sensitivity: 0.0335, unit: 'Pa', basis: 'FS', provenance },
    1: { sensitivity: 0.05, unit: 'Pa', basis: 'FS', provenance: { ...provenance, sensitivity: 0.05 } },
  } }));
  await page.goto('/');
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Setup' }).click();
  const note = page.getByTestId('setup-carried-cal-note');
  await expect(note).toContainText('calibration carried for channels 1, 2 (Pa)');
  await note.getByTestId('setup-carried-cal-clear').click();
  await expect(page.getByTestId('setup-carried-cal-note')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('pydvma.carriedCal.v1'))).toBeNull();
});

// ---- Reference tone ------------------------------------------------------ //

/** A one-channel 1 kHz tone whose rms is `rms`, as a loadable `.dvma`. */
function toneDvma(rms: number, extra: Record<string, unknown> = {}, name = 'tone.dvma'): { name: string; mimeType: string; buffer: Buffer } {
  const fs = 8000;
  const n = 8000;
  const axis = new Float64Array(n);
  const data = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    axis[i] = i / fs;
    data[i] = rms * Math.SQRT2 * Math.sin(2 * Math.PI * 1000 * i / fs);
  }
  const bytes = writeDvma({
    formatVersion: 1, pydvmaVersion: '2.8.4',
    items: [{
      kind: 'TimeData',
      arrays: {
        time_axis: { shape: [n], isComplex: false, data: axis },
        time_data: { shape: [n, 1], isComplex: false, data: data },
      },
      meta: { test_name: 'calibrator', timestring: 't0', unique_id: 'TONE0' },
      settings: { fs, ...extra },
    }],
  });
  return { name, mimeType: 'application/octet-stream', buffer: Buffer.from(bytes) };
}

test('the reference tone panel defaults follow the row unit and refuse a bad level', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(card0(page)).toBeVisible();
  const overlay = await openCalibrate(page);
  // Row 0 is in N: a unit rms of 1 at 1 kHz.
  await overlay.getByTestId('cal-ref-0').click();
  await expect(overlay.getByTestId('cal-ref-level')).toHaveValue('1');
  await expect(overlay.getByTestId('cal-ref-level-unit')).toHaveText('N');
  // Switch the row to Pa: 94 dB SPL.
  await overlay.getByTestId('cal-unit-0').selectOption('Pa');
  await expect(overlay.getByTestId('cal-ref-level')).toHaveValue('94');
  await expect(overlay.getByTestId('cal-ref-level-unit')).toHaveText('dB SPL');
  // Accelerometer: 10 m/s2 at 159.2 Hz.
  await overlay.getByTestId('cal-unit-0').selectOption('m/s²');
  await expect(overlay.getByTestId('cal-ref-level')).toHaveValue('10');
  await expect(overlay.getByTestId('cal-ref-freq')).toHaveValue('159.2');
  // A non-positive level cannot be measured, and the stop note shows for an
  // unstated gain.
  await overlay.getByTestId('cal-ref-level').fill('0');
  await expect(overlay.getByTestId('cal-ref-measure')).toBeDisabled();
  await expect(overlay.getByTestId('cal-ref-invalid')).toBeVisible();
  await expect(overlay.getByTestId('cal-ref-stop-note')).toContainText('gain knob and −10 dB switch');
});

test('a tone recorded in volts is refused for a full-scale recording', async ({ page }) => {
  await page.goto('/');
  // Set 0: full-scale units (no rail stated); set 1: volts (VmaxSC 2).
  for (const f of [toneDvma(0.03, {}, 'a.dvma'), toneDvma(0.03, { VmaxSC: 2 }, 'b.dvma')]) {
    const chooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Load Data' }).click();
    await (await chooserPromise).setFiles(f);
    await page.waitForTimeout(300);
  }
  await expect(page.getByTestId('tray-card-1')).toBeVisible();
  const overlay = await openCalibrate(page);   // set 0, full-scale
  await overlay.getByTestId('cal-ref-0').click();
  await expect(overlay.getByTestId('cal-ref-basis')).toHaveCount(0);   // its own recording
  const options = await overlay.getByTestId('cal-ref-set').evaluate(
    (el) => [...(el as HTMLSelectElement).options].map((o) => o.value));
  await overlay.getByTestId('cal-ref-set').selectOption(options[1]);
  await expect(overlay.getByTestId('cal-ref-basis')).toContainText('full-scale units');
  await expect(overlay.getByTestId('cal-ref-measure')).toBeDisabled();
  await expect(overlay.getByTestId('cal-sens-0')).toHaveValue('1');
});

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('a 94 dB SPL reference tone sets the sensitivity and the PSD reads dB re (20 µPa)²/Hz', async ({ page }) => {
    await page.goto('/');
    const chooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Load Data' }).click();
    // rms chosen so that rms / 1.0024 Pa = 0.0335 per Pa.
    await (await chooserPromise).setFiles(toneDvma(0.0335 * 1.0024));
    await expect(card0(page)).toBeVisible();

    const overlay = await openCalibrate(page);
    await overlay.getByTestId('cal-unit-0').selectOption('Pa');
    await overlay.getByTestId('cal-ref-0').click();
    await expect(overlay.getByTestId('cal-ref-level')).toHaveValue('94');
    await overlay.getByTestId('cal-ref-measure').click();
    await expect.poll(
      async () => Number(await overlay.getByTestId('cal-sens-0').inputValue()),
      { timeout: 200_000 },
    ).toBeCloseTo(0.0335, 3);
    await expect(overlay.getByTestId('cal-ref-warning')).toHaveCount(0);
    await overlay.getByTestId('cal-apply').click();
    await expect(overlay).toBeHidden();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Freq' }).click();
    await page.locator('[data-spec="density"]').click();
    await page.getByRole('button', { name: 'Calc PSD' }).click();
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });
    await expect(yLabel(page)).toContainText('dB re (20 µPa)²/Hz');
  });

  test('a unit changed after Measure records a plain sensitivity, not the tone', async ({ page }) => {
    // `?fixture=1` for the `window.__dataset` hook: the tone loads beside
    // the fixture set, and its saved calibration provenance is read back.
    await page.goto('/?fixture=1');
    await expect(card0(page)).toBeVisible();
    const chooserPromise = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: 'Load Data' }).click();
    await (await chooserPromise).setFiles(toneDvma(0.0335 * 1.0024));
    const card = page.locator('[data-testid^="tray-card-"]').filter({ hasText: 'calibrator' });
    await expect(card).toBeVisible();
    await card.hover();
    await card.getByTestId('cal-open').click();
    const overlay = page.getByTestId('cal-overlay');
    await expect(overlay).toBeVisible();

    await overlay.getByTestId('cal-unit-0').selectOption('Pa');
    await overlay.getByTestId('cal-ref-0').click();
    await overlay.getByTestId('cal-ref-measure').click();
    await expect.poll(
      async () => Number(await overlay.getByTestId('cal-sens-0').inputValue()),
      { timeout: 200_000 },
    ).toBeCloseTo(0.0335, 3);
    // The measured number stays, but it is no longer a pascal calibration.
    await overlay.getByTestId('cal-unit-0').selectOption('m/s²');
    await overlay.getByTestId('cal-apply').click();
    await expect(overlay).toBeHidden();

    const cal = await page.evaluate(() => {
      type Item = { kind: string; meta: Record<string, unknown> };
      type Store = { subscribe(fn: (d: { items: Item[] } | null) => void): () => void };
      let out: unknown = null;
      (window as unknown as { __dataset: Store }).__dataset.subscribe((d) => {
        const tone = d?.items.find((i) => i.kind === 'TimeData' && i.meta.unique_id === 'TONE0');
        out = tone?.meta.channel_calibration ?? null;
      })();
      return out as { method: string; unit: string; reference: unknown }[] | null;
    });
    expect(cal?.[0]).toMatchObject({ method: 'sensitivity', unit: 'm/s²', reference: null });
  });
});
