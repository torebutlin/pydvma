import { expect, test, type Page } from '@playwright/test';
import { fileURLToPath } from 'node:url';

/**
 * @engine — Best Match's reference picker and its prompt (closes TODO W3).
 *
 * Two TF cards, as in the 3C6 lab: `?fixture=1` loads "webui fixture" (a TF
 * with no calibration), and Load Data appends `tf_cal_python.dvma`, whose
 * "mass_cal" TF carries a python-set factor of 7 (the free-mass calibration).
 *
 * The reference is picked BY CARD NAME ("ref TF"), and the prompt:
 *   - appears only when a RESCALED line has a calibrated level to lose,
 *   - names the reference and says it stays as it is,
 *   - lists only the cards that are rescaled.
 * Before the fix the picker offered channels of an unseen set, and the
 * prompt said the reference's own factor would be replaced.
 *
 * The prompt is raised before the engine runs; the rescale itself goes
 * through the real engine, hence @engine.
 */
function fixturePath(name: string): string {
  return fileURLToPath(new URL(`../tests/fixtures/${name}`, import.meta.url));
}

async function loadFile(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('the reference is a card; the prompt names it and asks only when a calibration is lost', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();
    await loadFile(page, fixturePath('tf_cal_python.dvma'));
    await expect(page.getByTestId('tray-card-1')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();

    // The picker lists the TF cards by name, in tray order.
    const ref = page.getByTestId('best-match-ref');
    await expect(ref.locator('option')).toHaveText(['webui fixture', 'mass_cal']);

    // Reference = the raw card → the calibrated mass_cal would lose its 7:
    // the prompt names the reference, says it stays, and lists mass_cal.
    await ref.selectOption({ label: 'webui fixture' });
    await page.getByTestId('best-match').click();
    const overlay = page.getByTestId('best-match-confirm-overlay');
    await expect(overlay).toBeVisible();
    await expect(overlay).toContainText('Best match onto webui fixture');
    await expect(overlay.getByTestId('best-match-confirm-reference'))
      .toContainText('The reference, webui fixture, stays as it is.');
    await expect(overlay.getByTestId('best-match-confirm-reference'))
      .toContainText('rescales mass_cal onto it');
    await expect(overlay.getByTestId('best-match-confirm-risk'))
      .toContainText('mass_cal shows a calibrated level now');
    // Cancel changes nothing and reports nothing.
    await overlay.getByTestId('best-match-confirm-cancel').click();
    await expect(overlay).toBeHidden();
    await expect(page.getByTestId('toast').filter({ hasText: 'Best match' })).toHaveCount(0);

    // Reference = the calibrated card (the 3C6 case) → what is rescaled is
    // raw, nothing is lost, so there is no prompt: it just runs.
    await ref.selectOption({ label: 'mass_cal' });
    await page.getByTestId('best-match').click();
    const done = page.getByTestId('toast').filter({ hasText: 'Best match onto mass_cal' });
    await expect(done).toBeVisible({ timeout: 200_000 });
    await expect(overlay).toHaveCount(0);
    // The reference's own ×1 is not reported; the rescaled card is.
    await expect(done.locator('.msg')).toHaveText(/^Best match onto mass_cal: webui fixture ×\S+$/);
    await expect(done.getByRole('button', { name: 'Undo' })).toBeVisible();
  });
});
