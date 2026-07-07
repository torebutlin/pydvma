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

  // Setup/Acquire/Live are now real stages (the acquisition first-cut flips
  // the liveSource capability on `acquire.init()`), so they render real cards.
  // Fit is a real stage too (Wave A1) but gated until a TF is computed
  // (`fitEngine` flips on the first TF): still NAVIGABLE — clicking it shows
  // the Fit card with its fit buttons disabled and a what-to-do note.
  const acquire = ribbon.getByRole('button', { name: 'Acquire' });
  await expect(acquire).toBeEnabled();
  const fit = ribbon.getByRole('button', { name: 'Fit' });
  await expect(fit).toBeEnabled();          // gated but clickable
  await fit.click();
  await expect(page.getByText(/needs a computed transfer function/i)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Fit 1' })).toBeDisabled();
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
