import { expect, test } from '@playwright/test';

/**
 * @engine — the modal-FIT golden path (Wave-A Task A1; round-4 items 9-10).
 * Loads the checked-in impulse.dvma via `?fixture=1`, computes the transfer
 * function, switches to the Fit stage (enabled once a TF exists — the
 * `fitEngine` capability), and exercises:
 *   - Fit 2 → two mode rows in the floating chip (the fixture has several
 *     evenly-spaced resonances, so the peak-split finds two);
 *   - the pink local-reconstruction overlay (`stroke=#be185d`) renders, and
 *     toggling "Global" adds the grey dashed global overlay (`#66708a`);
 *   - Refine (round-4 item 10): simultaneously refines both modes and either
 *     improves or auto-reverts — either way NO error banner and the model
 *     stays valid (two modes);
 *   - per-mode delete via the chip's × (round-4 item 9) drops to one mode with
 *     no error (this also covers round-4 bug 2 — deleting a mode as the matrix
 *     shrinks must not raise the old `delete_mode` IndexError);
 *   - Undo restores the deleted mode.
 *
 * SLOW: the first Calc TF pays the full pyodide boot (numpy/scipy + pydvma +
 * peakutils wheels); Refine adds a least_squares solve. Tagged `@engine`.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('fixture → TF → Fit 2, Refine, per-mode delete + undo (no errors)', async ({ page }) => {
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

    // Set the fit window (= the committed 'tf' view x-range, which
    // `sharedFreqRange` reads) to span two of the fixture's resonances
    // (~1000 + ~1500 Hz) so the peak-split finds two modes. The fixture
    // otherwise loads with a narrow low-frequency committed view.
    await page.evaluate(() => {
      (window as unknown as { __viewState: { setRange: (id: string, r: unknown) => void } })
        .__viewState.setRange('tf', { x: [900, 1700], y: null });
    });

    // Fit TWO modes over the visible window (peak-split at the two strongest).
    await page.getByRole('button', { name: 'Fit 2' }).click();
    const chip = page.getByLabel('fitted modes');
    await expect(chip).toContainText('mode 1', { timeout: 60_000 });
    await expect(chip).toContainText('mode 2');

    // The pink local reconstruction overlay renders.
    await expect(page.locator('path[data-testid="plot-line"][stroke="#be185d"]').first())
      .toBeVisible({ timeout: 20_000 });

    // Toggling "Global" adds the grey dashed global overlay.
    await page.getByRole('button', { name: 'Global', exact: true }).click();
    await expect(page.locator('path[data-testid="plot-line"][stroke="#66708a"]').first())
      .toBeVisible({ timeout: 20_000 });

    // Refine both modes simultaneously. Whether it improves or auto-reverts,
    // there must be no error and the model stays valid (two modes).
    const refine = page.getByRole('button', { name: 'Refine' });
    await expect(refine).toBeEnabled();
    await refine.click();
    await expect(chip).toContainText('mode 2', { timeout: 60_000 });
    await expect(page.locator('.ctx-err')).toHaveCount(0);
    await expect(page.locator('.plot-err')).toHaveCount(0);

    // Delete the first mode via the chip's × (per-mode delete). Drops to one
    // mode with no error (round-4 bug 2 — the shrinking-matrix delete path).
    await page.getByRole('button', { name: 'delete mode 1' }).click();
    await expect(chip).not.toContainText('mode 2', { timeout: 60_000 });
    await expect(chip).toContainText('mode 1');
    await expect(page.locator('.ctx-err')).toHaveCount(0);
    await expect(page.locator('.plot-err')).toHaveCount(0);

    // Undo restores the deleted mode (two modes again).
    await chip.getByRole('button', { name: /Undo/ }).click();
    await expect(chip).toContainText('mode 2', { timeout: 60_000 });
    await expect(page.locator('.ctx-err')).toHaveCount(0);
  });
});
