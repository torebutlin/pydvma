import { expect, test } from '@playwright/test';

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
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('boots pyodide and round-trips calc_fft through the worker', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto('/?engine=1');

    // Wait for the engine to boot to 'ready' (the slow part).
    await expect(page.getByTestId('engine-status')).toHaveText('ready', {
      timeout: 200_000,
    });

    // Round-trip: 2-channel sine -> calc_fft -> shape metadata.
    const result = await page.evaluate(() => (window as any).__engineSelfTest());

    // freq_axis must be non-empty.
    expect(result.freqAxisLen).toBeGreaterThan(0);
    // freq_data is complex128 -> marshalled with complex: true.
    expect(result.freqDataComplex).toBe(true);
    // Interleaved [re,im] flat length === 2 * Nf * Nc.
    expect(result.freqDataLen).toBe(2 * result.freqAxisLen * result.nChannels);
    // Declared shape is (Nf, Nc).
    expect(result.freqDataShape).toEqual([result.freqAxisLen, result.nChannels]);

    expect(errors, `console/page errors: ${errors.join('\n')}`).toEqual([]);
  });
});
