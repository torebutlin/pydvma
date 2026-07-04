import { statSync } from 'node:fs';
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

test('Export stage → PNG → Save Figure downloads a .png', async ({ page }) => {
  await openExport(page);

  // PNG is the default-checked format; PDF is off. Save Figure → one .png.
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save Figure' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.png$/);
  // Non-empty: a real rasterised figure is tens of KB; a blank/failed export
  // would be near-zero. Floor well under the observed ~150 KB, above trivial.
  expect(await downloadSize(download)).toBeGreaterThan(1000);
});

test('Export stage → PDF only → Save Figure downloads a .pdf', async ({ page }) => {
  await openExport(page);

  // Uncheck PNG, check PDF → the single download is the .pdf.
  await page.getByRole('checkbox', { name: 'PNG' }).uncheck();
  await page.getByRole('checkbox', { name: 'PDF' }).check();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save Figure' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  // A real vector PDF of this figure is tens of KB (~75 KB observed); floor at
  // 1 KB catches an empty/blank-page PDF while staying robust.
  expect(await downloadSize(download)).toBeGreaterThan(1000);
});

test('the Time card Save Figure shortcut opens the Export stage', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  // The Time stage is active by default; its Save Figure jumps to Export.
  await page.getByRole('button', { name: 'Save Figure' }).click();
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toBeVisible();
});
