import { readFileSync, statSync } from 'node:fs';
import { expect, test, type Download, type Page } from '@playwright/test';

/**
 * Task 14 (figure export) e2e — the FALLBACK download path (Playwright's
 * Chromium has no File System Access API, so `workdir` stays null and every
 * Save Figure goes through an `<a download>`, which Playwright surfaces as a
 * download event).
 *
 * `?fixture=1` loads the checked-in impulse.dvma and the Time view renders
 * immediately from it (no engine needed — this is NOT an @engine test), so
 * the plot's <svg> is ready to export. The card is reached from the Export
 * stage in the ribbon.
 *
 * These assert both the plumbing (a download of the right name fires per
 * checked format) AND that the written file is non-trivially sized — so a
 * valid-named-but-BLANK export (exactly where a rendering regression lands)
 * fails here rather than passing on the filename alone. The pixel-level proof
 * (white / transparent / dark actually render + differ) is the browser live
 * smoke done during development; these size floors are the cheap CI guard.
 */

/** Byte size of a completed download's saved file (fallback path). */
async function downloadSize(download: Download): Promise<number> {
  const path = await download.path();
  expect(path).toBeTruthy();
  return statSync(path!).size;
}

/** Load the fixture and open the Export stage; returns once the plot is up. */
async function openExport(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  // The Time plot renders straight from the loaded fixture.
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Export' }).click();
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toBeVisible();
}

test('Export stage → PNG → Export downloads a .png', async ({ page }) => {
  await openExport(page);

  // PNG is the default-checked format; PDF is off. Export → one .png. The
  // card's execute button is "Export" (scoped to the card; the ribbon also
  // has an "Export" stage button).
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('region', { name: 'Export stage controls' }).getByRole('button', { name: 'Export', exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.png$/);
  // Non-empty: a real rasterised figure is tens of KB; a blank/failed export
  // would be near-zero. Floor well under the observed ~150 KB, above trivial.
  expect(await downloadSize(download)).toBeGreaterThan(1000);
});

test('Export stage → PDF only → Export downloads a .pdf', async ({ page }) => {
  await openExport(page);

  // Uncheck PNG, check PDF → the single download is the .pdf.
  await page.getByRole('checkbox', { name: 'PNG' }).uncheck();
  await page.getByRole('checkbox', { name: 'PDF' }).check();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('region', { name: 'Export stage controls' }).getByRole('button', { name: 'Export', exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  // A real vector PDF of this figure is tens of KB (~75 KB observed); floor at
  // 1 KB catches an empty/blank-page PDF while staying robust.
  expect(await downloadSize(download)).toBeGreaterThan(1000);
});

test('the top-bar Save Figure opens the Export stage from any view', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  // Save Figure now lives in the top bar (works from every view); Time is the
  // default view. Clicking it jumps to the Export stage.
  await page.getByRole('button', { name: 'Save Figure' }).click();
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toBeVisible();
});

/**
 * Data export (Task A3): CSV (pure TS) + Matlab (engine `scipy.io.savemat`).
 *
 * These need the `exporter` accessor wired into the card
 * (`ContextCard` passing `exporter={actions}`, a one-line Wave-A integration
 * step). Until that lands the Matlab/CSV buttons are DISABLED by design, so
 * each test skips itself when the button is disabled rather than failing —
 * they activate automatically once the wiring + `actions.exportArrays` /
 * `actions.exportMat` are in place. The card's execute buttons are scoped to
 * the Export region so the ribbon's own "Export" stage button never matches.
 */
test('Export stage → Export CSV downloads a raw-values .csv (first line is real %.18e)', async ({
  page,
}) => {
  await openExport(page);
  const region = page.getByRole('region', { name: 'Export stage controls' });
  const csvBtn = region.getByRole('button', { name: 'Export CSV' });
  await expect(csvBtn).toBeVisible();
  test.skip(
    await csvBtn.isDisabled(),
    'exporter not wired yet — ContextCard must pass exporter={actions}',
  );

  const downloadPromise = page.waitForEvent('download');
  await csvBtn.click();
  const download = await downloadPromise;
  // fixture=1 has only time data → one file, named <base>-time.csv.
  expect(download.suggestedFilename()).toMatch(/-time\.csv$/);
  const text = readFileSync((await download.path())!, 'utf8');
  const firstLine = text.split('\n')[0];
  // The time axis starts at 0; every cell is numpy's %.18e (no complex parens).
  expect(firstLine.startsWith('0.000000000000000000e+00,')).toBe(true);
  expect(firstLine).toMatch(/^-?\d\.\d{18}e[+-]\d{2}(,-?\d\.\d{18}e[+-]\d{2})+$/);
});

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('Export stage → Export Matlab downloads a non-empty .mat', async ({ page }) => {
    await openExport(page);
    const region = page.getByRole('region', { name: 'Export stage controls' });
    const matBtn = region.getByRole('button', { name: 'Export Matlab' });
    await expect(matBtn).toBeVisible();
    test.skip(
      await matBtn.isDisabled(),
      'exporter not wired yet — ContextCard must pass exporter={actions}',
    );

    // First .mat export boots pyodide (scipy.io.savemat) — allow the full boot.
    const downloadPromise = page.waitForEvent('download', { timeout: 200_000 });
    await matBtn.click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.mat$/);
    // A real .mat with a time array is comfortably > 100 bytes; a blank/failed
    // export would be near-zero.
    expect(await downloadSize(download)).toBeGreaterThan(100);
  });
});
