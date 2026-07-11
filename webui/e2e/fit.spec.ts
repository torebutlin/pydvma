import { expect, test } from '@playwright/test';

/**
 * @engine — the modal-FIT golden path (Wave-A Task A1; round-4 items 9-10;
 * round-5 item 13 fit-as-tray-card + .dvma round-trip; round-7 item 6
 * fit-lines local|global toggle).
 *
 * Loads the checked-in impulse.dvma via `?fixture=1`, computes the transfer
 * function, switches to the Fit stage (enabled once a TF exists — the
 * `fitEngine` capability), and exercises:
 *   - Fit 2 → two mode rows in the floating chip (the fixture has several
 *     evenly-spaced resonances, so the peak-split finds two);
 *   - round-5 item 13: the reconstruction becomes a "Modal fit" TRAY CARD
 *     whose recon lines draw DASHED through the normal visible pipeline
 *     (default mode 'global' → the card is named "Modal fit global (…)");
 *   - round-7 item 6: the Fit card's fit-lines toggle (local | global) swaps
 *     WHICH reconstruction the pseudo-set carries — the legend/tray name
 *     follows the mode ("Modal fit local (…)" ↔ "Modal fit global (…)") and
 *     the dashed lines persist across the flip (the old primary-set-only pink
 *     local overlay is gone — local lines are ordinary pseudo-set lines for
 *     all channels now);
 *   - Refine (round-4 item 10): simultaneously refines both modes and either
 *     improves or auto-reverts — either way NO error banner and the model
 *     stays valid (two modes);
 *   - per-mode delete via the chip's × (round-4 item 9) drops to one mode with
 *     no error (this also covers round-4 bug 2 — deleting a mode as the matrix
 *     shrinks must not raise the old `delete_mode` IndexError);
 *   - Undo restores the deleted mode;
 *   - round-5 item 13: autosave → reload → Restore round-trips the ModalData
 *     item so the "Modal fit" card is rebuilt from the saved model.
 *
 * SLOW: the first Calc TF pays the full pyodide boot (numpy/scipy + pydvma +
 * peakutils wheels); Refine adds a least_squares solve; the reload pays a
 * SECOND boot for the restore recon. Tagged `@engine`.
 */
test.describe('@engine', () => {
  test.setTimeout(320_000);

  test('fixture → TF → Fit 2 → tray card + dashed recon, Refine, delete + undo, reload restores', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Compute the transfer function (boots the engine on first compute).
    const stages = page.getByRole('navigation', { name: 'stages' });
    await stages.getByRole('button', { name: 'TF' }).click();
    await page.getByRole('button', { name: 'Calc TF' }).click();
    // Round-8: the header "computing" chip shows while the calc (here
    // including the first-calc engine boot) is in flight, and clears after.
    await expect(page.getByTestId('busy-chip')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });
    await expect(page.getByTestId('busy-chip')).toHaveCount(0, { timeout: 15_000 });

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

    // Freq-navigator mode ticks (2026-07-11 design): the Fit stage auto-opens
    // the navigator and each fitted fn marks the strip.
    await expect(page.getByTestId('freq-nav')).toBeVisible();
    await expect(page.getByTestId('freq-nav-tick')).toHaveCount(2);

    // Round-8: the chip is draggable by its header strip and minimisable.
    // Drag by an explicit delta from the grab point (the header centre).
    const chipHead = chip.locator('.chip-head');
    const before = (await chip.boundingBox())!;
    const head = (await chipHead.boundingBox())!;
    const grabX = head.x + head.width / 2;
    const grabY = head.y + head.height / 2;
    await page.mouse.move(grabX, grabY);
    await page.mouse.down();
    await page.mouse.move(grabX + 140, grabY - 90, { steps: 6 });
    await page.mouse.up();
    const after = (await chip.boundingBox())!;
    expect(after.x - before.x).toBeGreaterThan(100);
    expect(before.y - after.y).toBeGreaterThan(50);

    // Minimise: the mode rows hide, the header keeps a "fit · 2 modes"
    // summary; expand restores the rows.
    await page.getByRole('button', { name: 'minimise fit summary' }).click();
    await expect(chip).not.toContainText('mode 1');
    await expect(chip).toContainText('2 modes');
    await page.getByRole('button', { name: 'expand fit summary' }).click();
    await expect(chip).toContainText('mode 1');

    // Round-5 item 13: the reconstruction is a "Modal fit" TRAY CARD whose
    // recon lines draw DASHED at the measured line-width (1.5) — named for the
    // DEFAULT reconstruction mode, 'global' (round-7 item 6). (The coherence
    // overlay is also dashed but drawn at width 1, so match width 1.5 to
    // isolate the recon.)
    await expect(page.getByText(/Modal fit global/).first()).toBeVisible({ timeout: 20_000 });
    const recon = page.locator('path[data-testid="plot-line"][stroke-dasharray="4 3"][stroke-width="1.5"]');
    await expect(recon.first()).toBeVisible({ timeout: 20_000 });

    // Round-7 item 6: the fit-lines toggle swaps the pseudo-set between the
    // LOCAL (just-fitted, non-empty right after a Fit) and GLOBAL recon — the
    // legend/tray names follow the mode, and the lines stay dashed pseudo-set
    // lines throughout (no separate pink overlay any more).
    await expect(page.getByTestId('fit-lines-toggle')).toBeVisible();
    await page.getByTestId('fit-lines-local').click();
    await expect(page.getByText(/Modal fit local/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/Modal fit global/)).toHaveCount(0);
    await expect(recon.first()).toBeVisible({ timeout: 20_000 });
    await page.getByTestId('fit-lines-global').click();
    await expect(page.getByText(/Modal fit global/).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/Modal fit local/)).toHaveCount(0);
    await expect(recon.first()).toBeVisible({ timeout: 20_000 });

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

    // ---- Round-5 item 13: .dvma round-trip via autosave → reload → Restore ----
    // The modal edits re-emit the dataset, so the debounced autosave persists a
    // ModalData item alongside the TimeData/TF. Wait until the autosaved bytes
    // actually CONTAIN the ModalData member (`arrays/NNNN_M.npy`) — polling only
    // `byteLength > 0` could pass on an earlier autosave written before the fit.
    await expect
      .poll(
        () =>
          page.evaluate(
            () =>
              new Promise<boolean>((resolve) => {
                const open = indexedDB.open('keyval-store');
                open.onsuccess = () => {
                  const db = open.result;
                  if (!db.objectStoreNames.contains('keyval')) return resolve(false);
                  const req = db.transaction('keyval').objectStore('keyval').get('pydvma:autosave');
                  req.onsuccess = () => {
                    const v = req.result as Uint8Array | undefined;
                    if (!v) return resolve(false);
                    // Zip stores member names uncompressed in local headers, so a
                    // raw-bytes scan finds the ModalData M array without unzipping.
                    const txt = new TextDecoder('latin1').decode(v);
                    resolve(/arrays\/\d{4}_M\.npy/.test(txt));
                  };
                  req.onerror = () => resolve(false);
                };
                open.onerror = () => resolve(false);
              }),
          ),
        { timeout: 15_000 },
      )
      .toBe(true);

    // Reload WITHOUT the fixture flag so the boot-time restore offer is not
    // skipped; accept it. loadDataset seeds the modal store from the saved
    // ModalData and refires the recon (the TF is present) to rebuild the card.
    await page.goto('/');
    const toast = page.getByTestId('toast').filter({ hasText: 'Restore last session?' });
    await expect(toast).toBeVisible();
    await toast.getByRole('button', { name: 'Restore' }).click();
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // The modes restore IMMEDIATELY from the saved matrix M (no engine): the
    // Fit stage's chip lists both modes right away — the core persistence proof.
    await stages.getByRole('button', { name: 'Fit', exact: true }).click();
    const restoredChip = page.getByLabel('fitted modes');
    await expect(restoredChip).toContainText('mode 1', { timeout: 30_000 });
    await expect(restoredChip).toContainText('mode 2');

    // The "Modal fit" tray card is rebuilt once the restore recon completes
    // (the engine reboots from cached wheels on the reloaded page). The restore
    // recon produces only a GLOBAL slice (a 'recon' recompute has no just-fitted
    // modes) and the mode defaults to 'global', so the card carries that name.
    await expect(page.getByText(/Modal fit global/).first()).toBeVisible({ timeout: 200_000 });
  });
});
