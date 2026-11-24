import { readFileSync, statSync } from 'node:fs';
import { inflateSync } from 'node:zlib';
import { expect, test, type Download, type Page, type TestInfo } from '@playwright/test';

/**
 * Task 14 (figure export) e2e — the FALLBACK download path (Playwright's
 * Chromium has no File System Access API, so `workdir` stays null and every
 * Save Figure goes through an `<a download>`, which Playwright surfaces as a
 * download event).
 *
 * `?fixture=1` loads the checked-in impulse.dvma and the Time view renders
 * immediately from it (no engine needed — this is NOT an @engine test), so
 * the plot's <svg> is ready to export. The card is reached from the Export
 * stage in the ribbon.
 *
 * These assert both the plumbing (a download of the right name fires per
 * checked format) AND what was written: Save Figure writes the PRINT layout
 * (`lib/export/printFigure.ts`) at the Export stage's printed width (160 mm
 * by default), so a PNG is 600 dpi — `round(160 / 25.4 × 600)` = 3780 px wide,
 * 16:9 tall, with a `pHYs` chunk saying so — and a PDF embeds the figure font.
 * A valid-named-but-BLANK export (exactly where a rendering regression lands)
 * still fails on the size floors rather than passing on the filename alone.
 */

/** Byte size of a completed download's saved file (fallback path). */
async function downloadSize(download: Download): Promise<number> {
  const path = await download.path();
  expect(path).toBeTruthy();
  return statSync(path!).size;
}

/** The bytes of a completed download's saved file (fallback path). */
async function downloadBytes(download: Download): Promise<Buffer> {
  const path = await download.path();
  expect(path).toBeTruthy();
  return readFileSync(path!);
}

/**
 * The BaseFont of every font a PDF page's text is set in: inflates each
 * FlateDecode stream, collects the resource names its `Tf` operators select,
 * and looks each up in the page's `/Font` resources. Enough for jsPDF's
 * one-page, uncompressed-dictionary output; not a general PDF reader.
 */
function pdfFontsUsed(pdf: Buffer): string[] {
  const text = pdf.toString('latin1');
  const resources = /\/Font <<([^>]*)>>/.exec(text)?.[1] ?? '';
  const objOf = new Map([...resources.matchAll(/\/(F\d+) (\d+) 0 R/g)].map((m) => [m[1], m[2]]));
  const baseFont = (obj: string): string | undefined => {
    const body = new RegExp(`(?:^|\\n)${obj} 0 obj([^]*?)endobj`).exec(text)?.[1] ?? '';
    return /\/BaseFont \/(\S+)/.exec(body)?.[1];
  };
  const names = new Set<string>();
  for (const m of text.matchAll(/\/FlateDecode\s*>>\s*stream\r?\n/g)) {
    // This stream's own /Length: the last one before its `stream` keyword.
    const len = Number([...text.slice(Math.max(0, m.index - 200), m.index).matchAll(/\/Length (\d+)/g)].at(-1)?.[1]);
    if (!(len > 0)) continue;
    const start = m.index + m[0].length;
    let content: string;
    try { content = inflateSync(pdf.subarray(start, start + len)).toString('latin1'); } catch { continue; }
    for (const t of content.matchAll(/\/(F\d+) [\d.]+ Tf/g)) names.add(t[1]);
  }
  return [...names].map((n) => baseFont(objOf.get(n) ?? '') ?? `?${n}`);
}

/** Click the Export stage card's Export button and wait for the one download. */
async function exportOne(page: Page): Promise<Download> {
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('region', { name: 'Export stage controls' }).getByRole('button', { name: 'Export', exact: true }).click();
  return downloadPromise;
}

/** Load the fixture and open the Export stage; returns once the plot is up. */
async function openExport(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  // The Time plot renders straight from the loaded fixture.
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Export' }).click();
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toBeVisible();
}

test('Export stage → PNG → Export downloads a .png', async ({ page }) => {
  await openExport(page);

  // PNG is the default-checked format; PDF is off. Export → one .png. The
  // card's execute button is "Export" (scoped to the card; the ribbon also
  // has an "Export" stage button).
  const download = await exportOne(page);
  expect(download.suggestedFilename()).toMatch(/\.png$/);
  const png = await downloadBytes(download);
  // 160 mm at 600 dpi, 16:9: 3780 × 2126 px (the height to ±2 px of rounding).
  expect(png.readUInt32BE(16)).toBe(3780);
  expect(Math.abs(png.readUInt32BE(20) - 2126)).toBeLessThanOrEqual(2);
  // The resolution is stamped: a pHYs chunk straight after IHDR (byte 33),
  // 23622 px/m (600 dpi) on both axes, unit 1 (metre).
  expect(png.subarray(37, 41).toString('latin1')).toBe('pHYs');
  expect(png.readUInt32BE(41)).toBe(23622);
  expect(png.readUInt32BE(45)).toBe(23622);
  expect(png[49]).toBe(1);
  // Non-empty, yet not a nuisance to attach or upload: under 1 MB.
  expect(png.length).toBeGreaterThan(1000);
  expect(png.length).toBeLessThan(1_000_000);
});

test('a 90 mm figure is 2126 px wide', async ({ page }) => {
  await openExport(page);
  await page.getByTestId('fig-width-90').click();
  const png = await downloadBytes(await exportOne(page));
  // round(90 / 25.4 × 600) = 2126.
  expect(png.readUInt32BE(16)).toBe(2126);
});

test('Export stage → PDF only → Export downloads a .pdf', async ({ page }) => {
  await openExport(page);

  // Uncheck PNG, check PDF → the single download is the .pdf.
  await page.getByRole('checkbox', { name: 'PNG' }).uncheck();
  await page.getByRole('checkbox', { name: 'PDF' }).check();

  const download = await exportOne(page);
  expect(download.suggestedFilename()).toMatch(/\.pdf$/);
  const pdf = await downloadBytes(download);
  // A 1 KB floor catches an empty/blank-page PDF while staying robust.
  expect(pdf.length).toBeGreaterThan(1000);
  // The figure font is embedded (a TrueType FontFile2 under its own name), so
  // the labels print in it wherever the PDF is opened. jsPDF writes the family
  // 'Pydvma Figure Serif' as a PDF name, each space escaped as #20.
  const text = pdf.toString('latin1');
  expect(text).toContain('/FontFile2');
  expect(text).toContain('/FontName /Pydvma#20Figure#20Serif');
  // And every text on the page is set in it: each `Tf` in the page's content
  // stream picks the font resource whose BaseFont is the figure font (the
  // standard 14 fonts jsPDF always lists stay unused).
  const used = pdfFontsUsed(pdf);
  expect(used.length).toBeGreaterThan(0);
  expect(new Set(used)).toEqual(new Set(['Pydvma#20Figure#20Serif']));
});

test('the top-bar Save Figure asks for a name and saves the current plot', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  // Save Figure lives in the top bar (works from every view). Like Save
  // Dataset it asks for a name first (the served app's Save dialog; a prompt
  // here), then saves with the Export stage's choices (PNG by default) —
  // without leaving the current view (2026-10-26: it used to only switch to
  // the Export stage, which read as "nothing happens").
  page.once('dialog', (d) => {
    expect(d.message()).toContain('Save figure');
    expect(d.defaultValue()).toMatch(/^pydvma_figure_.*\.png$/);
    void d.accept('topbar');
  });
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save Figure' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('topbar.png');
  expect(await downloadSize(download)).toBeGreaterThan(1000);
  await expect(page.getByRole('region', { name: 'Export stage controls' })).toHaveCount(0);
});

/**
 * Data export (lossless-export round, 2026-10-06): Export CSV and Export
 * Matlab write the very document Save writes, converted by the engine's
 * python writers (`dvma_to_csv` / `dvma_to_mat`), so each is ONE file holding
 * what the .dvma holds — and Load Data reads it back. Both boot the engine.
 * The card's buttons are scoped to the Export region so the ribbon's own
 * "Export" stage button never matches.
 */

/** Click Load Data and answer the fallback file chooser with `path`. */
async function loadViaFallback(page: Page, path: string): Promise<void> {
  const chooserPromise = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Load Data' }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles(path);
}

/** Export with `button`, then load the download back: the sets double. */
async function exportAndReload(
  page: Page, info: TestInfo, button: string, ext: string,
): Promise<string> {
  await openExport(page);
  const region = page.getByRole('region', { name: 'Export stage controls' });
  const btn = region.getByRole('button', { name: button });
  await expect(btn).toBeEnabled();
  const before = await page.getByTestId(/^tray-card-\d+$/).count();

  const downloads: Download[] = [];
  page.on('download', (d) => downloads.push(d));
  await btn.click();
  // The first export boots pyodide — allow the full boot.
  await expect.poll(() => downloads.length, { timeout: 200_000 }).toBe(1);
  await page.waitForTimeout(500);
  expect(downloads).toHaveLength(1);                     // ONE file, not one per kind
  expect(downloads[0].suggestedFilename()).toMatch(new RegExp(`\\.${ext}$`));
  // Keep the file's own name: a .mat is recognised by its extension.
  const path = info.outputPath(downloads[0].suggestedFilename());
  await downloads[0].saveAs(path);

  // Load Data APPENDS: the exported sets come back beside the originals.
  await loadViaFallback(page, path);
  await expect(page.getByTestId(/^tray-card-\d+$/)).toHaveCount(2 * before, { timeout: 200_000 });
  await expect(page.getByTestId('toast').filter({ hasText: /failed|could not/i })).toHaveCount(0);
  // impulse.dvma carries a TF, and it came back too.
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();
  return path;
}

test.describe('@engine', () => {
  test.setTimeout(400_000);

  test('Export CSV writes one pydvma CSV that Load Data reads back', async ({ page }, info) => {
    const path = await exportAndReload(page, info, 'Export CSV', 'csv');
    const lines = readFileSync(path, 'utf8').split('\n');
    expect(lines[0]).toBe('# pydvma dataset (pydvma-csv 1)');
    expect(lines.some((l) => l.startsWith('# manifest: {'))).toBe(true);
    // a readable table per item: heading, column names, rows
    const t = lines.findIndex((l) => l.startsWith('# table 0: item 0, TimeData'));
    expect(t).toBeGreaterThan(0);
    expect(lines[t + 1].startsWith('time_axis,time_data[0]')).toBe(true);
    expect(lines.some((l) => /^freq_axis,tf_data\[0\]\.re,tf_data\[0\]\.im/.test(l))).toBe(true);
  });

  test('Export Matlab writes one pydvma .mat that Load Data reads back', async ({ page }, info) => {
    const path = await exportAndReload(page, info, 'Export Matlab', 'mat');
    expect(statSync(path).size).toBeGreaterThan(100);
  });
});
