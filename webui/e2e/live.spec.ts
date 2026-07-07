import { expect, test } from '@playwright/test';

/**
 * Live acquisition e2e (round-2 redesign): the persistent bottom-left
 * mini-oscilloscope, its start/stop + cross-stage persistence, the
 * expand→Live navigation, Setup's full toggle, and the Acquire summary.
 *
 * The monitor's getUserMedia resolves against Chromium's fake media
 * device (enabled in playwright.config.ts), so Start reaches "streaming"
 * headlessly.
 */

test('mini monitor is docked with a discoverable Start, and persists across stages once streaming', async ({ page }) => {
  await page.goto('/');

  const mini = page.getByTestId('mini-monitor');
  await expect(mini).toBeVisible();                    // docked in the tray foot on every stage
  await expect(page.getByTestId('mini-start')).toBeVisible(); // idle Start affordance is discoverable

  // Start the monitor from the mini itself.
  await page.getByTestId('mini-start').click();
  await expect(page.getByTestId('mini-stop')).toBeVisible();  // reached streaming (Stop now shown)

  // Switching stages does NOT stop it — the round-2 persistence contract
  // that replaced the old auto-stop-on-leaving-Live behaviour.
  const ribbon = page.getByRole('navigation', { name: 'stages' });
  await ribbon.getByRole('button', { name: 'Frequency' }).click();
  await expect(mini).toBeVisible();
  await expect(page.getByTestId('mini-stop')).toBeVisible();  // still streaming after the stage change

  // User stop idles it back to the discoverable Start.
  await page.getByTestId('mini-stop').click();
  await expect(page.getByTestId('mini-start')).toBeVisible();
});

test('mini ⤢ expand navigates to the Live stage scope', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('mini-start').click();
  await expect(page.getByTestId('mini-stop')).toBeVisible();

  await page.getByRole('button', { name: 'Expand oscilloscope' }).click();
  // The Live figure area is the expanded three-pane scope.
  await expect(page.getByTestId('live-scope')).toBeVisible();
  await expect(page.getByTestId('fft-canvas')).toBeVisible();
});

test('Setup full toggle grows the settings area with the raw-measurement constraints', async ({ page }) => {
  await page.goto('/');
  const ribbon = page.getByRole('navigation', { name: 'stages' });
  await ribbon.getByRole('button', { name: 'Setup' }).click();

  await expect(page.getByTestId('setup-full')).toBeHidden(); // basic view by default
  await page.getByRole('button', { name: /Full/ }).click();
  await expect(page.getByTestId('setup-full')).toBeVisible(); // second row of real settings appears
  await expect(page.getByTestId('setup-full')).toContainText(/echo/i);
});

test('Acquire summary shows device and an honest pretrigger state', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Acquire' }).click();

  const summary = page.getByTestId('acquire-summary');
  await expect(summary).toBeVisible();
  await expect(summary).toContainText('44.1 kHz');
  await expect(summary).toContainText('Default input');
  await expect(summary).toContainText('no pretrig');
});
