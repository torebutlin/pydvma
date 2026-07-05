import { expect, test } from '@playwright/test';

/**
 * Task R5 — per-line (channel) relabel. Non-@engine: exercises the
 * selection store / tray / legend wiring on the checked-in 2-channel
 * fixture (`?fixture=1`), no pyodide compute needed (the Time view draws
 * the decoded lines and their legend immediately on load).
 *
 * Asserts:
 *   - double-clicking a channel label opens an inline input; typing a
 *     name + Enter renames the line in the tray AND the legend
 *     (`webui fixture · hammer`);
 *   - a SINGLE click on the row still cycles the tri-state (on → fade),
 *     i.e. the rename handling did not break the whole-row toggle;
 *   - Esc cancels an edit (no rename); blank commits a reset to default.
 */

const card0 = (page: import('@playwright/test').Page) => page.getByTestId('tray-card-0');

test('double-click a channel label → rename flows to tray + legend', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  // The 2-channel fixture card is expanded; ch_0 shows its default label.
  const lab0 = card.getByTestId('ch-lab-0');
  await expect(lab0).toHaveText('ch_0');

  // Double-click opens the inline input; type a name and commit on Enter.
  await lab0.dblclick();
  const input = card.getByTestId('ch-lab-input-0');
  await expect(input).toBeVisible();
  await input.fill('hammer');
  await input.press('Enter');

  // Tray shows the custom label; the sibling channel is untouched.
  await expect(card.getByTestId('ch-lab-0')).toHaveText('hammer');
  await expect(card.getByTestId('ch-lab-1')).toHaveText('ch_1');

  // The legend (Time view, rendered on fixture load) shows it too.
  const legend = page.getByTestId('legend');
  await expect(legend.getByTestId('legend-entry').filter({ hasText: 'webui fixture · hammer' }))
    .toBeVisible();
});

test('single click still cycles the tri-state (rename did not break toggling)', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  const row = card.getByTestId('ch-row-0');
  // Starts ON; a single click cycles on → fade → off.
  await expect(row.locator('.state-badge')).toHaveText('on');
  await row.click();
  await expect(row.locator('.state-badge')).toHaveText('fade');
  await row.click();
  await expect(row.locator('.state-badge')).toHaveText('off');
});

test('Esc cancels an edit; blank resets to the default label', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  // Rename, then reset by committing a blank field.
  await card.getByTestId('ch-lab-0').dblclick();
  let input = card.getByTestId('ch-lab-input-0');
  await input.fill('accel');
  await input.press('Enter');
  await expect(card.getByTestId('ch-lab-0')).toHaveText('accel');

  // Esc mid-edit does NOT rename.
  await card.getByTestId('ch-lab-0').dblclick();
  input = card.getByTestId('ch-lab-input-0');
  await input.fill('scrapped');
  await input.press('Escape');
  await expect(card.getByTestId('ch-lab-0')).toHaveText('accel');   // unchanged

  // Commit a blank field → reset to the default ch_0.
  await card.getByTestId('ch-lab-0').dblclick();
  input = card.getByTestId('ch-lab-input-0');
  await input.fill('');
  await input.press('Enter');
  await expect(card.getByTestId('ch-lab-0')).toHaveText('ch_0');
});
