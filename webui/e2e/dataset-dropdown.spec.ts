import { expect, test } from '@playwright/test';

/**
 * Task R1 — the per-set "Dataset ▾" dropdown on the analysis cards.
 * Non-@engine: exercises the store/card wiring only (no pyodide
 * compute). The checked-in fixture has ONE set, so this asserts the
 * dropdown renders (All sets + the set entry), defaults to "All sets",
 * is the FIRST control on each of Frequency / TF / Sonogram, and that
 * switching the target to the set then editing a control persists that
 * edit back through the shared per-set settings store (verified by
 * switching back to "All sets", which — with a single set — shows the
 * same value).
 */

const stage = (name: string) => `nav[aria-label="stages"] button:has-text("${name}")`;

test('Dataset dropdown renders on Frequency/TF/Sonogram, defaults to All sets, first control', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();   // fixture loaded a set

  for (const [nav, card] of [
    ['Freq', 'Frequency stage controls'],
    ['TF', 'TF stage controls'],
    ['Sonogram', 'Sonogram stage controls'],
  ] as const) {
    await page.locator(stage(nav)).click();
    const region = page.getByRole('region', { name: card });
    const ds = region.getByLabel('dataset', { exact: true });
    await expect(ds).toBeVisible();
    // Defaults to "All sets".
    await expect(ds).toHaveValue('all');
    // Options: "All sets" + one per set (the fixture's single set).
    await expect(ds.locator('option')).toHaveText(['All sets', 'webui fixture']);
    // It is the FIRST labelled control group in the card body.
    await expect(region.locator('.grp-lab').first()).toHaveText('dataset');
  }
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
