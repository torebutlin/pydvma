import { expect, test } from '@playwright/test';

/**
 * Round-3 item 3 — whole-set tri-state by clicking the tray card TITLE.
 * Non-@engine: exercises the selection store / tray wiring on the
 * checked-in 2-channel fixture (`?fixture=1`), no pyodide compute needed
 * (the Time view draws the decoded lines immediately on load).
 *
 * Asserts:
 *   - a SINGLE click on the set title cycles the WHOLE set together
 *     (both rows on → fade → off → on), and reflects the group state on
 *     the header (struck when all-off);
 *   - a DOUBLE click on the title opens the inline rename and does NOT
 *     also cycle the set (rows stay 'on'); Enter commits the new name.
 */

const card0 = (page: import('@playwright/test').Page) => page.getByTestId('tray-card-0');

test('single click on the title cycles the whole set together', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  const badge0 = card.getByTestId('ch-row-0').locator('.state-badge');
  const badge1 = card.getByTestId('ch-row-1').locator('.state-badge');
  const title = card.getByTestId('set-name');
  const header = card.getByTestId('set-header');

  // Both channels start ON.
  await expect(badge0).toHaveText('on');
  await expect(badge1).toHaveText('on');

  // Click the title → whole set advances to FADE (deferred-click timer, so
  // the assertion auto-retries until it fires). Asserting between clicks
  // also spaces them past the dblclick window so no rename is triggered.
  await title.click();
  await expect(badge0).toHaveText('fade');
  await expect(badge1).toHaveText('fade');

  // Again → OFF; the header is struck-through for an all-off set.
  await title.click();
  await expect(badge0).toHaveText('off');
  await expect(badge1).toHaveText('off');
  await expect(header).toHaveClass(/struck/);

  // Again → back to ON (wrap).
  await title.click();
  await expect(badge0).toHaveText('on');
  await expect(badge1).toHaveText('on');
  await expect(header).not.toHaveClass(/struck/);
});

test('double click on the title renames WITHOUT cycling the set', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card = card0(page);
  await expect(card).toBeVisible();

  const badge0 = card.getByTestId('ch-row-0').locator('.state-badge');
  const badge1 = card.getByTestId('ch-row-1').locator('.state-badge');
  const title = card.getByTestId('set-name');

  await expect(title).toHaveText('webui fixture');
  await expect(badge0).toHaveText('on');
  await expect(badge1).toHaveText('on');

  // Double-click opens the inline rename; the pending single-click cycle is
  // cancelled, so the set must NOT advance.
  await title.dblclick();
  const input = card.getByTestId('set-name-input');
  await expect(input).toBeVisible();
  await input.fill('shaker run');
  await input.press('Enter');

  // Name committed; set state unchanged (still fully ON — no cycle fired).
  await expect(card.getByTestId('set-name')).toHaveText('shaker run');
  await expect(badge0).toHaveText('on');
  await expect(badge1).toHaveText('on');
});
