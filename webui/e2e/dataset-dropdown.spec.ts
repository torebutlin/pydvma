import { expect, test } from '@playwright/test';

/**
 * Task R1 — the per-set "Dataset ▾" dropdown on the analysis cards.
 * Non-@engine: exercises the store/card wiring only (no pyodide
 * compute). The checked-in fixture has ONE set, so this asserts the
 * Frequency / TF dropdowns render (All sets + the set entry), default to
 * "All sets", and are the FIRST control; the SONOGRAM dropdown (round-6
 * item 3) instead has NO "All sets" option — it is a single-set view, so it
 * defaults to the one time-bearing set. It also checks that switching a
 * target then editing a control persists that edit back through the shared
 * per-set settings store.
 */

const stage = (name: string) => `nav[aria-label="stages"] button:has-text("${name}")`;

test('Dataset dropdown renders on Frequency/TF/Sonogram, defaults to All sets, first control', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();   // fixture loaded a set

  // Frequency / TF: an aggregate 'All sets' plus the single set, defaulting to
  // 'all'.
  for (const [nav, card] of [
    ['Freq', 'Frequency stage controls'],
    ['TF', 'TF stage controls'],
  ] as const) {
    await page.locator(stage(nav)).click();
    const region = page.getByRole('region', { name: card });
    const ds = region.getByLabel('dataset', { exact: true });
    await expect(ds).toBeVisible();
    await expect(ds).toHaveValue('all');
    await expect(ds.locator('option')).toHaveText(['All sets', 'webui fixture']);
    await expect(region.locator('.grp-lab').first()).toHaveText('dataset');
  }

  // Sonogram (round-6 item 3): single-set only — NO 'All sets' option; the one
  // time-bearing set is selected by default, and it is still the first control.
  await page.locator(stage('Sonogram')).click();
  const sonoRegion = page.getByRole('region', { name: 'Sonogram stage controls' });
  const sonoDs = sonoRegion.getByLabel('dataset', { exact: true });
  await expect(sonoDs).toBeVisible();
  await expect(sonoDs.locator('option')).toHaveText(['webui fixture']);
  await expect(sonoDs).toHaveValue('0');
  await expect(sonoRegion.locator('.grp-lab').first()).toHaveText('dataset');
});

test('switching the Dataset dropdown to a set drives the tray solo and edits persist', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();

  await page.locator(stage('Freq')).click();
  const region = page.getByRole('region', { name: 'Frequency stage controls' });
  const ds = region.getByLabel('dataset', { exact: true });

  // Switch the target to the named set, then change the window.
  await ds.selectOption('0');
  await expect(ds).toHaveValue('0');
  const window = region.getByLabel('window', { exact: true });
  await expect(window).toHaveValue('hann');       // default
  await window.selectOption('flattop');
  await expect(window).toHaveValue('flattop');

  // Back to "All sets": with a single set, the representative shows the
  // same value — the edit persisted through the shared per-set store.
  await ds.selectOption('all');
  await expect(ds).toHaveValue('all');
  await expect(window).toHaveValue('flattop');
});
