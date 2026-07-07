import { expect, test } from '@playwright/test';

/**
 * @engine — the app must work when served from a SUB-PATH, not just the
 * server root. The deployed GitHub Pages site lives at
 * `…github.io/pydvma/app/`, and the engine's vendored-asset base URL was
 * resolved against the bare ORIGIN, so the worker fetched `/pyodide/…`
 * from the domain root and the engine failed to boot ("Importing a module
 * script failed") on the live site ONLY — every dev/preview/e2e server
 * sits at the root, which is why nothing caught it (Tore did, round 4).
 *
 * This spec drives the identical dist through the /pydvma/app/ mount
 * (playwright.config.ts webServer #2) and boots the REAL engine: fixture →
 * Frequency → Calc FFT → a plot line renders. A root-absolute asset path
 * anywhere in the boot chain (worker chunk, pyodide runtime, wheels)
 * fails this test. SLOW (pyodide boot); tagged @engine.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('served under /pydvma/app/, the engine boots and computes an FFT', async ({ page }) => {
    await page.goto('http://localhost:4175/pydvma/app/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' })
      .getByRole('button', { name: 'Frequency' }).click();
    await page.getByRole('button', { name: /^Calc/ }).click();

    // First compute boots pyodide — allow the full boot budget. A regression
    // to root-absolute paths surfaces here as the engine-boot error banner
    // instead of a line.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });
    await expect(page.getByText(/engine failed to boot/i)).toHaveCount(0);
  });
});
