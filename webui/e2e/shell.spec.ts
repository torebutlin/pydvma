import { expect, test } from '@playwright/test';

test('wide shell: header buttons, unnumbered ribbon, gated stages', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Load Data' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save Dataset' })).toBeVisible();
  // Save Figure lives in the top bar now; disabled until data is loaded.
  await expect(page.getByRole('button', { name: 'Save Figure' })).toBeDisabled();
  const ribbon = page.getByRole('navigation', { name: 'stages' });
  await expect(ribbon.getByRole('button', { name: 'Frequency' })).toBeEnabled();
  await expect(ribbon).not.toContainText(/[0-9]\./); // no numbering

  // Gated stages (Acquire/Setup/Fit) are NAVIGABLE — clickable, and show an
  // explanatory placeholder rather than a dead-disabled button.
  const acquire = ribbon.getByRole('button', { name: 'Acquire' });
  await expect(acquire).toBeEnabled();
  await acquire.click();
  await expect(page.getByText(/arrives in a future update/i)).toBeVisible();
});

test('narrow: rail with word-label ribbon and flyover tray', async ({ page }) => {
  await page.goto('/?narrow=1');
  await expect(page.getByRole('navigation', { name: 'stages' })).toContainText('Freq');
  await expect(page.getByTestId('narrow-rail')).toBeVisible();
  await expect(page.getByTestId('tray')).toBeHidden(); // flyover tray starts hidden
  await page.getByTestId('rail-more').click(); // ⋯ opens flyover
  await expect(page.getByTestId('tray')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('tray')).toBeHidden();
});

test('tray matrix ops (fixture-loaded set)', async ({ page }) => {
  await page.goto('/?fixture=1');
  const card0 = page.getByTestId('tray-card-0');
  await expect(card0).toBeVisible();                 // fixture loaded a set into the tray
  await card0.getByTestId('set-header').click();     // row cycle
  await page.getByTestId('chip-ch-1').click();       // column cycle
  await card0.getByTestId('set-header').dblclick();
  await page.keyboard.type('hammer'); await page.keyboard.press('Enter');
  await expect(card0).toContainText('hammer');
});
