import { expect, test } from '@playwright/test';

/**
 * @engine — TF out/in labelling on a MULTI-CHANNEL set (Task R4, the E1
 * bug fix). Loads the 3-channel impulse fixture via `?fixture=3ch`,
 * switches to TF, runs Calc TF through the real pyodide worker, and
 * asserts the out/in contract on a >2-channel set:
 *
 *   - exactly 2 lines render (N−1 outputs; the input channel has none),
 *   - the legend shows `ch_1/ch_0` and `ch_2/ch_0` (output/input),
 *   - the input channel (`ch_0`) appears only as the shared `…/ch_0`
 *     denominator — never as its own output line.
 *
 * The pre-R4 bug drew one mislabelled line and silently dropped ch_2, so
 * this fails loudly against the old code path. SLOW: first Calc TF pays
 * the full pyodide boot; tagged `@engine`.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('3-channel fixture → TF → 2 out/in lines, input channel absent', async ({ page }) => {
    await page.goto('/?fixture=3ch');

    // The 3-channel set lands in the tray.
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Switch to TF and estimate.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
    // Coherence defaults ON (adds a dashed right-axis line per output);
    // turn it off so the line count is exactly the TF magnitude lines.
    await page.getByLabel('coherence overlay').uncheck();
    await page.getByRole('button', { name: 'Calc TF' }).click();

    // First compute boots the engine — allow the full boot budget.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    // Exactly two output lines (3 channels − 1 input); ch_0 draws none.
    await expect(page.getByTestId('plot-line')).toHaveCount(2);

    // The legend rows are the SAME lines the plot draws: out/in labels
    // (a "set · " prefix may lead), input channel dropped.
    const labels = await page.getByTestId('legend-entry').allInnerTexts();
    const flat = labels.map((s) => s.trim());
    expect(flat).toHaveLength(2);
    expect(flat.some((l) => l.endsWith('ch_1/ch_0'))).toBe(true);
    expect(flat.some((l) => l.endsWith('ch_2/ch_0'))).toBe(true);
    // No legend row is a bare input-channel line (label ends "ch_0" with
    // no "/" numerator — the input never gets its own output line).
    expect(flat.some((l) => /ch_0$/.test(l) && !l.includes('/'))).toBe(false);

    // Coherence overlay uses the SAME out/in remap: turning it on adds one
    // dashed right-axis line per OUTPUT channel (2 more), not per raw
    // channel — so 4 lines total, input still absent.
    await page.getByLabel('coherence overlay').check();
    await expect(page.getByTestId('plot-line')).toHaveCount(4);
    // Legend is unchanged (2 out/in rows — coherence shares the line).
    await expect(page.getByTestId('legend-entry')).toHaveCount(2);

    // R5: renaming channels in the tray flows into the TF out/in label.
    // Rename ch_0 (the input) → "hammer" and ch_1 (an output) → "accel";
    // the TF line then reads "accel/hammer" (output/input) in the legend.
    const card = page.getByTestId('tray-card-0');
    await card.getByTestId('ch-lab-0').dblclick();
    await card.getByTestId('ch-lab-input-0').fill('hammer');
    await card.getByTestId('ch-lab-input-0').press('Enter');
    await card.getByTestId('ch-lab-1').dblclick();
    await card.getByTestId('ch-lab-input-1').fill('accel');
    await card.getByTestId('ch-lab-input-1').press('Enter');

    const relabelled = await page.getByTestId('legend-entry').allInnerTexts();
    const flat2 = relabelled.map((s) => s.trim());
    // The output/input label uses the custom names on both halves.
    expect(flat2.some((l) => l.endsWith('accel/hammer'))).toBe(true);
    // ch_2 was left unnamed, so it still reads its default numerator over
    // the renamed input: "ch_2/hammer".
    expect(flat2.some((l) => l.endsWith('ch_2/hammer'))).toBe(true);
  });
});
