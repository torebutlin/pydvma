import { expect, test } from '@playwright/test';

test('wide shell: header buttons, unnumbered ribbon, gated stages', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Load Data' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save Dataset' })).toBeVisible();
  const ribbon = page.getByRole('navigation', { name: 'stages' });
  await expect(ribbon.getByRole('button', { name: 'Frequency' })).toBeEnabled();
  await expect(ribbon.getByRole('button', { name: 'Acquire' })).toBeDisabled();
  await expect(ribbon).not.toContainText(/[0-9]\./); // no numbering
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
