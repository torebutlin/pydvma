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

// The .mat (JW-logger) import path is wired in glue.py (mat_to_dvma) + the
// load pipeline, but there is no real JW-logger .mat fixture checked in to
// prove it end to end. Defer the e2e until a sample is available.
test.fixme('mat import — needs a sample .mat fixture', () => {});
