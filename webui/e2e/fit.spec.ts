import { expect, test } from '@playwright/test';

/**
 * @engine — the modal-FIT golden path (Wave-A Task A1). Loads the checked-in
 * impulse.dvma via `?fixture=1`, computes the transfer function, then switches
 * to the Fit stage (enabled only once a TF exists — the `fitEngine`
 * capability), fits one mode over the visible window, and asserts:
 *   - a mode row appears in the floating fit chip (`fn = … Hz · ζ = … · Q = …`);
 *   - the pink local-reconstruction overlay (`stroke=#be185d`) renders;
 *   - toggling "Reconstruction" adds the grey dashed global overlay (#66708a).
 *
 * SLOW: the first Calc TF pays the full pyodide boot (numpy/scipy + pydvma +
 * peakutils wheels). Tagged `@engine` so it runs/skips with the other engine
 * tests.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('fixture → TF → Fit 1 renders a mode row + pink recon; toggle adds global', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Compute the transfer function (boots the engine on first compute).
    const stages = page.getByRole('navigation', { name: 'stages' });
    await stages.getByRole('button', { name: 'TF' }).click();
    await page.getByRole('button', { name: 'Calc TF' }).click();
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    // The Fit stage is now enabled (fitEngine flipped on the first TF).
    const fitStage = stages.getByRole('button', { name: 'Fit', exact: true });
    await expect(fitStage).toBeEnabled();
    await fitStage.click();

    // Fit one mode over the visible window.
    await page.getByRole('button', { name: 'Fit 1' }).click();

    // A mode row appears in the floating chip.
    const chip = page.getByLabel('fitted modes');
    await expect(chip).toContainText('mode 1', { timeout: 60_000 });
    await expect(chip).toContainText('Hz');

    // The pink local reconstruction overlay renders.
    await expect(page.locator('path[data-testid="plot-line"][stroke="#be185d"]').first())
      .toBeVisible({ timeout: 20_000 });

    // Toggling "Reconstruction" adds the grey dashed global overlay.
    await page.getByRole('button', { name: 'Reconstruction' }).click();
    await expect(page.locator('path[data-testid="plot-line"][stroke="#66708a"]').first())
      .toBeVisible({ timeout: 20_000 });

    // Fit again: the ACCUMULATE path round-trips the modal matrix M back
    // through the engine (a nested JsProxy payload — the `_get` object-proxy
    // regression). Same window ⇒ the refit REPLACES the mode (no dupe), so
    // the chip still lists exactly one mode and no fit error is shown.
    await page.getByRole('button', { name: 'Fit 1' }).click();
    await expect(chip).toContainText('mode 1', { timeout: 60_000 });
    await expect(chip).not.toContainText('mode 2');
    await expect(page.locator('.ctx-err')).toHaveCount(0);

    // Reject: deleting the LAST remaining mode over the visible window must
    // NOT raise (round-4 bug 2 — glue `delete_mode` crashed with an
    // IndexError as the matrix emptied). The chip returns to "No fit" and no
    // error banner appears on the card or under the plot.
    await page.getByRole('button', { name: 'Reject' }).click();
    await expect(chip).toContainText('No fit', { timeout: 60_000 });
    await expect(chip).not.toContainText('mode 1');
    await expect(page.locator('.ctx-err')).toHaveCount(0);
    await expect(page.locator('.plot-err')).toHaveCount(0);
  });
});
