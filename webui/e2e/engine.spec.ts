import { expect, test, type Page } from '@playwright/test';

/**
 * @engine — the real pyodide boot + compute round-trip (Task 11). SLOW: it
 * downloads/instantiates the vendored pyodide runtime, loads numpy/scipy, and
 * micropip-installs the pydvma + peakutils wheels in a web worker, then runs a
 * `calc_fft` end to end. Tagged `@engine` so it can be run/skipped in isolation
 * (`playwright test --grep @engine`).
 *
 * Booting to ready alone is NOT sufficient proof — the round-trip validates
 * glue.py, the complex-array marshalling, and the worker protocol together.
 */

/**
 * Boot the engine, wait for 'ready', drive the calc_fft self-test, and assert
 * the marshalled shape. Shared by both tests so the offline guard proves the
 * exact same end-to-end path, not just a boot.
 */
async function bootAndRoundTrip(page: Page): Promise<void> {
  await page.goto('/?engine=1');

  await expect(page.getByTestId('engine-status')).toHaveText('ready', {
    timeout: 200_000,
  });

  const result = await page.evaluate(() => (window as any).__engineSelfTest());

  // freq_axis must be non-empty.
  expect(result.freqAxisLen).toBeGreaterThan(0);
  // freq_data is complex128 -> marshalled with complex: true.
  expect(result.freqDataComplex).toBe(true);
  // Interleaved [re,im] flat length === 2 * Nf * Nc.
  expect(result.freqDataLen).toBe(2 * result.freqAxisLen * result.nChannels);
  // Declared shape is (Nf, Nc).
  expect(result.freqDataShape).toEqual([result.freqAxisLen, result.nChannels]);
}

test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('boots pyodide and round-trips calc_fft through the worker', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(e.message));

    await bootAndRoundTrip(page);

    expect(errors, `console/page errors: ${errors.join('\n')}`).toEqual([]);
  });

  // Regression guard for the offline install path. The pydvma wheel declares
  // `Requires-Dist: peakutils` (and matplotlib); the worker MUST install the
  // vendored wheels with deps=false so micropip never reaches out to PyPI for
  // them. Here we ABORT every pypi.org / files.pythonhosted.org request while
  // leaving the sanctioned pyodide CDN (cdn.jsdelivr.net, for the prebuilt
  // numpy/scipy/micropip wheels) reachable, then require a full boot +
  // round-trip. This FAILS on the old deps=true code (boot dies with
  // "Can't fetch metadata for 'peakutils'") and PASSES on the fix.
  test('boots and round-trips with PyPI blocked (offline install guard)', async ({ page }) => {
    const bootFailures: string[] = [];
    page.on('console', (m) => {
      const t = m.text();
      // Only care about engine boot failures / python tracebacks — browser
      // "net::ERR_FAILED" noise from the aborted PyPI requests is expected.
      if (m.type() === 'error' && (/\[engine\] boot failed/.test(t) || /Traceback|ModuleNotFoundError|ValueError/.test(t))) {
        bootFailures.push(t);
      }
    });

    let pypiHits = 0;
    await page.route(/https?:\/\/([^/]*\.)?(pypi\.org|pythonhosted\.org)\//, (route) => {
      pypiHits++;
      return route.abort();
    });

    await bootAndRoundTrip(page);

    // No boot failure surfaced, and (proving the fix) micropip never tried PyPI.
    expect(bootFailures, `engine boot errors: ${bootFailures.join('\n')}`).toEqual([]);
    expect(pypiHits, 'the worker must not fetch anything from PyPI').toBe(0);
  });
});
