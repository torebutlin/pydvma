import { expect, test, type Page, type Locator } from '@playwright/test';

/**
 * Task R2 — the coupled ΔF resolution control (slider + text boxes) on
 * the Frequency card. Non-@engine: exercises the pure UI coupling over
 * `resolution.ts` (no pyodide compute). Drives PSD (FFT has no averaging,
 * so no resolution control), then:
 *   - asserts the four coupled boxes (N / frame-s / nFFT / Δf) + slider
 *     render, with a data-derived slider range (NOT the old fixed 1..30);
 *   - dragging the slider couples all four boxes;
 *   - typing an OUT-OF-RANGE N pins the slider to its end-stop while the
 *     typed value HOLDS (the number box is the source of truth);
 *   - typing a Δf inverts to a frame length (Δf = 1/frameLength).
 */

const stage = (name: string) => `nav[aria-label="stages"] button:has-text("${name}")`;

/** Navigate to Freq → PSD so the averaged resolution control is shown. */
async function openFreqPsd(page: Page): Promise<Locator> {
  await page.goto('/?fixture=1');
  await page.locator(stage('Freq')).click();
  const region = page.getByRole('region', { name: 'Frequency stage controls' });
  await region.getByRole('button', { name: 'PSD', exact: true }).click();
  return region;
}

test('resolution control renders four coupled boxes + a data-derived slider range', async ({ page }) => {
  const region = await openFreqPsd(page);
  const slider = region.getByLabel('resolution frames', { exact: true });
  await expect(slider).toBeVisible();
  // Range derives from the set (fs, duration), NOT the old hard-coded 1..30.
  await expect(slider).toHaveAttribute('min', '1');
  const max = await slider.getAttribute('max');
  expect(Number(max)).toBeGreaterThan(1);
  expect(max).not.toBe('30');

  // All four coupled quantities are present and typeable.
  await expect(region.getByLabel('N frames', { exact: true })).toBeVisible();
  await expect(region.getByLabel('frame length seconds', { exact: true })).toBeVisible();
  await expect(region.getByLabel('nFFT', { exact: true })).toBeVisible();
  await expect(region.getByLabel('delta f Hz', { exact: true })).toBeVisible();

  // Default N=10 for the fixture; Δf tracks the inverse of the frame
  // length (each box is independently rounded to 2 dp, so compare within
  // that display tolerance rather than exact reciprocals).
  await expect(region.getByLabel('N frames', { exact: true })).toHaveValue('10');
  const frameLen = Number(await region.getByLabel('frame length seconds', { exact: true }).inputValue());
  const dF = Number(await region.getByLabel('delta f Hz', { exact: true }).inputValue());
  expect(Math.abs(dF - 1 / frameLen)).toBeLessThan(0.2);
});

test('dragging the slider couples N / frame-s / nFFT / Δf', async ({ page }) => {
  const region = await openFreqPsd(page);
  const slider = region.getByLabel('resolution frames', { exact: true });
  const nBox = region.getByLabel('N frames', { exact: true });

  await expect(nBox).toHaveValue('10');
  const before = Number(await region.getByLabel('frame length seconds', { exact: true }).inputValue());

  // Move the slider up a few steps with the keyboard (fires input/change).
  await slider.focus();
  for (let i = 0; i < 5; i++) await slider.press('ArrowRight');

  // N followed the slider up, and the frame length shrank (more frames =
  // shorter frames) — the whole family recomputed together.
  await expect(nBox).not.toHaveValue('10');
  const after = Number(await region.getByLabel('frame length seconds', { exact: true }).inputValue());
  expect(after).toBeLessThan(before);
});

test('typing an out-of-range N pins the slider to its end-stop; the value holds', async ({ page }) => {
  const region = await openFreqPsd(page);
  const slider = region.getByLabel('resolution frames', { exact: true });
  const nBox = region.getByLabel('N frames', { exact: true });
  const sliderMax = Number(await slider.getAttribute('max'));

  // Type an N well above the slider's max end-stop.
  const bigN = sliderMax + 400;
  await nBox.fill(String(bigN));
  await nBox.blur();

  // The number box (source of truth) HOLDS the typed value...
  await expect(nBox).toHaveValue(String(bigN));
  // ...while the slider PINS to its max end-stop (never fights the value).
  await expect(slider).toHaveValue(String(sliderMax));
});

test('typing Δf inverts to a frame length (Δf = 1 / frameLength)', async ({ page }) => {
  const region = await openFreqPsd(page);
  const dFBox = region.getByLabel('delta f Hz', { exact: true });
  const frameLenBox = region.getByLabel('frame length seconds', { exact: true });

  await dFBox.fill('2');
  await dFBox.blur();

  // Δf = 2 Hz ⇒ ~0.5 s frame (the coupling honours 1/Δf).
  const frameLen = Number(await frameLenBox.inputValue());
  expect(frameLen).toBeCloseTo(0.5, 1);
});
