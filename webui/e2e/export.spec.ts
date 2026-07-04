import { expect, test } from '@playwright/test';

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
 * These assert the plumbing (a download of the right name fires per checked
 * format). The proof that the exported figure actually RENDERS — white /
 * transparent / dark backgrounds, data line preserved — is the browser live
 * smoke done during development (string tests + a download event do not, on
 * their own, prove pixels).
 */

/** Load the fixture and open the Export stage; returns once the plot is up. */
async function openExport(page: import('@playwright/test').Page): Promise<void> {
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
});

test('the Time card Save Figure shortcut opens the Export stage', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  // The Time stage is active by default; its Save Figure jumps to Export.
  await page.getByRole('button', { name: 'Save Figure' }).click();
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toBeVisible();
});
