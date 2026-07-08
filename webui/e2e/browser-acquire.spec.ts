import { expect, test } from '@playwright/test';

/**
 * Browser (Web Audio) output-stimulus + pretrigger e2e — round-5 item 10.
 *
 * On the plain Web Audio path (no `pydvma serve` bridge) the Acquire card's
 * output-stimulus group and pretrigger arm now render, and an armed or
 * output-driven capture lands a set via Chromium's fake media device
 * (`--use-fake-device-for-media-stream`, enabled in playwright.config.ts).
 *
 * A real acoustic loop-back — the played stimulus reaching the mic and crossing
 * the pretrigger threshold — is NOT feasible headless (no speakers→mic path),
 * so the trigger-on-real-signal path is covered by the pretrig/source unit
 * tests.  Here we assert the UI un-gates and every capture path completes and
 * lands a set without an uncaught error (the armed path falls back to an
 * ordinary capture on timeout).
 */

async function gotoAcquire(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('navigation', { name: 'stages' })
    .getByRole('button', { name: 'Acquire' }).click();
}

test('the output group and pretrigger arm render on the Web Audio path (un-gated)', async ({ page }) => {
  await gotoAcquire(page);

  // Both groups render on the plain Web Audio path (previously bridge-only).
  await expect(page.getByTestId('acquire-output')).toBeVisible();
  await expect(page.getByTestId('acquire-pretrigger')).toBeVisible();

  // Toggling output on adds the OUT badge and the summary's output clause.
  await page.getByTestId('output-on').check();
  await expect(page.getByTestId('out-badge')).toBeVisible();
  await expect(page.getByTestId('acquire-summary')).toContainText('out:');

  // Arming shows the editable sample count (bare-arm default 100) + summary.
  await page.getByTestId('pretrig-arm').check();
  const samples = page.getByTestId('pretrig-samples-arm');
  await expect(samples).toBeVisible();
  await expect(samples).toHaveValue('100');
  await expect(page.getByTestId('acquire-summary')).toContainText('armed 100');
});

test('an armed capture lands a set via the fake mic (timeout fallback headless)', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await gotoAcquire(page);

  await page.getByTestId('pretrig-arm').check();
  // Short timeout: with no acoustic loop-back the fake tone may never cross, so
  // fall back to an ordinary capture quickly.
  await page.getByTestId('pretrig-timeout').fill('0.3');

  await page.getByTestId('log-btn').click();
  // The buffered / triggered capture lands as a set either way.
  await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 25000 });
  expect(errors, `uncaught errors:\n${errors.join('\n')}`).toHaveLength(0);
});

test('an output-driven capture lands a set with no uncaught error', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await gotoAcquire(page);

  await page.getByTestId('output-on').check();
  await expect(page.getByTestId('out-badge')).toBeVisible();

  await page.getByTestId('log-btn').click();
  await expect(page.locator('[data-testid^="tray-card-"]')).toHaveCount(1, { timeout: 25000 });
  expect(errors, `uncaught errors:\n${errors.join('\n')}`).toHaveLength(0);
});
