import { readFileSync, statSync } from 'node:fs';
import { expect, test, type Download, type Page, type TestInfo } from '@playwright/test';

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
 * Data export (lossless-export round, 2026-10-06): Export CSV and Export
 * Matlab write the very document Save writes, converted by the engine's
 * python writers (`dvma_to_csv` / `dvma_to_mat`), so each is ONE file holding
 * what the .dvma holds — and Load Data reads it back. Both boot the engine.
 * The card's buttons are scoped to the Export region so the ribbon's own
 * "Export" stage button never matches.
 */

/** Click Load Data and answer the fallback file chooser with `path`. */
async function loadViaFallback(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

/** Export with `button`, then load the download back: the sets double. */
async function exportAndReload(
  page: Page, info: TestInfo, button: string, ext: string,
): Promise<string> {
  await openExport(page);
  const region = page.getByRole('region', { name: 'Export stage controls' });
  const btn = region.getByRole('button', { name: button });
  await expect(btn).toBeEnabled();
  const before = await page.getByTestId(/^tray-card-\d+$/).count();

  const downloads: Download[] = [];
  page.on('download', (d) => downloads.push(d));
  await btn.click();
  // The first export boots pyodide — allow the full boot.
  await expect.poll(() => downloads.length, { timeout: 200_000 }).toBe(1);
  await page.waitForTimeout(500);
  expect(downloads).toHaveLength(1);                     // ONE file, not one per kind
  expect(downloads[0].suggestedFilename()).toMatch(new RegExp(`\\.${ext}$`));
  // Keep the file's own name: a .mat is recognised by its extension.
  const path = info.outputPath(downloads[0].suggestedFilename());
  await downloads[0].saveAs(path);

  // Load Data APPENDS: the exported sets come back beside the originals.
  await loadViaFallback(page, path);
  await expect(page.getByTestId(/^tray-card-\d+$/)).toHaveCount(2 * before, { timeout: 200_000 });
  await expect(page.getByTestId('toast').filter({ hasText: /failed|could not/i })).toHaveCount(0);
  // impulse.dvma carries a TF, and it came back too.
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();
  return path;
}

test.describe('@engine', () => {
  test.setTimeout(400_000);

  test('Export CSV writes one pydvma CSV that Load Data reads back', async ({ page }, info) => {
    const path = await exportAndReload(page, info, 'Export CSV', 'csv');
    const lines = readFileSync(path, 'utf8').split('\n');
    expect(lines[0]).toBe('# pydvma dataset (pydvma-csv 1)');
    expect(lines.some((l) => l.startsWith('# manifest: {'))).toBe(true);
    // a readable table per item: heading, column names, rows
    const t = lines.findIndex((l) => l.startsWith('# table 0: item 0, TimeData'));
    expect(t).toBeGreaterThan(0);
    expect(lines[t + 1].startsWith('time_axis,time_data[0]')).toBe(true);
    expect(lines.some((l) => /^freq_axis,tf_data\[0\]\.re,tf_data\[0\]\.im/.test(l))).toBe(true);
  });

  test('Export Matlab writes one pydvma .mat that Load Data reads back', async ({ page }, info) => {
    const path = await exportAndReload(page, info, 'Export Matlab', 'mat');
    expect(statSync(path).size).toBeGreaterThan(100);
  });
});
