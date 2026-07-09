import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

/**
 * Task 13 (file I/O) e2e — the FALLBACK (download/upload) paths, which are
 * what Playwright's Chromium exercises because it does not expose
 * `showDirectoryPicker` without special flags. So `workdir` stays null and
 * every load/save goes through `fallbackDir()`: Load creates a hidden
 * `<input type=file>` (surfaced to Playwright as a filechooser), Save
 * triggers an `<a download>`.
 *
 * Covered here:
 *   - Load a checked-in .dvma via the fallback file input → tray populates.
 *   - Legacy .npy load (@engine, slow): the pickle → glue.legacy_to_dvma →
 *     readDvma → tray path, proving the bytes marshalling end to end.
 *   - Autosave → restore: load, wait for the debounced autosave, reload,
 *     and assert the "Restore last session?" toast repopulates the tray.
 *   - .mat import is wired in code but has no sample fixture → test.fixme.
 */

/** Absolute path to a checked-in fixture under webui/tests/fixtures. */
function fixture(name: string): string {
  return fileURLToPath(new URL(`../tests/fixtures/${name}`, import.meta.url));
}

/** Click Load Data and answer the fallback file chooser with `path`. */
async function loadViaFallback(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

test('load a .dvma via the fallback file input populates the tray', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('tray-card-0')).toBeHidden(); // nothing loaded yet
  await loadViaFallback(page, fixture('impulse.dvma'));
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
});

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('legacy .npy load → glue legacy_to_dvma → readDvma → tray', async ({ page }) => {
    await page.goto('/');
    await loadViaFallback(page, fixture('reference_dataset_v140.npy'));
    // First conversion boots pyodide + installs wheels — allow the full budget.
    // Proves the whole path: fallback input → sniff 'npy' → engine
    // legacy_to_dvma (bytes marshalling) → readDvma → loadDataset → tray.
    await expect(page.getByTestId('tray-card-0')).toBeVisible({ timeout: 200_000 });
  });
});

test('autosave persists and the restore banner repopulates on reload', async ({ page }) => {
  await page.goto('/');
  await loadViaFallback(page, fixture('impulse.dvma'));
  await expect(page.getByTestId('tray-card-0')).toBeVisible();

  // Wait for the debounced autosave (2 s) to land in IndexedDB, then confirm
  // the key is present so the reload deterministically finds a session. Read
  // the raw store (idb-keyval defaults: db 'keyval-store', store 'keyval') so
  // the check does not depend on importing the module in page context.
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            new Promise<number>((resolve) => {
              const open = indexedDB.open('keyval-store');
              open.onsuccess = () => {
                const db = open.result;
                if (!db.objectStoreNames.contains('keyval')) return resolve(0);
                const req = db.transaction('keyval').objectStore('keyval').get('pydvma:autosave');
                req.onsuccess = () => {
                  const v = req.result as Uint8Array | undefined;
                  resolve(v ? v.byteLength : 0);
                };
                req.onerror = () => resolve(0);
              };
              open.onerror = () => resolve(0);
            }),
        ),
      { timeout: 10_000 },
    )
    .toBeGreaterThan(0);

  // Reload: the boot-time restore reads the autosave and offers to restore.
  await page.reload();
  const toast = page.getByTestId('toast').filter({ hasText: 'Restore last session?' });
  await expect(toast).toBeVisible();
  await toast.getByRole('button', { name: 'Restore' }).click();
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
});

// .mat (JW-logger) import, end to end through the engine's mat_to_dvma
// (round-7e). The fixture is a synthetic JW TF file — one complex FRF column
// plus one COHERENCE column (real, in [0,1]), the layout of Jim Woodhouse's
// admittance measurements. The import must attach the coherence as the TF's
// coherence overlay, NOT as a second TF channel: imported as a channel it
// poisons modal fits (fn/zeta rail to the window edge — seen on real JW
// guitar files).
test('mat import (JW logger): one TF line, coherence as overlay not a channel', async ({ page }) => {
  await page.goto('/');
  await loadViaFallback(page, fixture('jw_tf_coh.mat'));
  // The conversion runs in the pyodide engine — allow its boot.
  await expect(page.getByTestId('tray-card-0')).toBeVisible({ timeout: 200_000 });

  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  // Exactly ONE legend row: the coherence column did not become a TF line.
  await expect(page.getByTestId('legend-entry')).toHaveCount(1);
  // The coherence DID arrive: the toolbar offers the coherence right-axis
  // control, which App gates on the model's y2 (coherence) axis existing.
  await page.getByTestId('zoom-toolbar').hover();
  await expect(page.getByTestId('coherence-control')).toBeVisible();
});
