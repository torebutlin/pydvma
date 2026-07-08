import { expect, test } from '@playwright/test';

/**
 * @engine — the analysis golden path (Task 12). Loads the checked-in
 * impulse.dvma via `?fixture=1`, switches to the TF stage, runs Calc TF
 * end to end through the real pyodide worker, and asserts a plot line
 * renders. Then switches to the Nyquist plot type and asserts the plot
 * SVG's drawing box is ~square (the aspect-locked Nyquist view).
 *
 * SLOW: the first Calc TF pays the full pyodide boot (numpy/scipy +
 * pydvma wheel install) because the app boots the engine lazily on
 * first compute. Tagged `@engine` so it runs/skips with the other
 * engine tests.
 */
test.describe('@engine', () => {
  test.setTimeout(240_000);

  test('fixture → TF → Calc TF renders a line; Nyquist is square', async ({ page }) => {
    await page.goto('/?fixture=1');

    // The fixture set lands in the tray.
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    // Switch to the TF stage and run the transfer-function estimate.
    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
    await page.getByRole('button', { name: 'Calc TF' }).click();

    // First compute boots the engine — allow the full boot budget.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });

    // Nyquist: pick the plot type and assert a ~square drawing box.
    await page.getByLabel('plot type').selectOption('nyquist');
    // Give the aspect-locked model a beat to re-render.
    await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 20_000 });

    const svg = page.getByTestId('plot-svg');
    const box = await svg.boundingBox();
    expect(box).not.toBeNull();
    // The SVG element fills the host; the SQUARE is the inner drawing
    // area. Assert the frame rect (data-role="axis" .frame) is square.
    const frame = await page.evaluate(() => {
      const f = document.querySelector('[data-testid="plot-svg"] rect.frame') as SVGGraphicsElement | null;
      if (!f) return null;
      const b = f.getBoundingClientRect();
      return { w: b.width, h: b.height };
    });
    expect(frame).not.toBeNull();
    expect(Math.abs(frame!.w - frame!.h)).toBeLessThan(0.2 * frame!.w);
  });

  test('fixture → Sonogram → Calc renders a filled, painted heat canvas', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();
    await page.getByRole('button', { name: 'Calc Sonogram' }).click();

    const canvas = page.getByTestId('sono-canvas');
    await expect(canvas).toBeVisible({ timeout: 200_000 });

    // The canvas element mounts immediately in the sono view; wait until the
    // worker result has actually PAINTED it (non-trivial alpha coverage)
    // before measuring — otherwise we read the empty default buffer.
    await expect.poll(async () => page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let painted = 0;
      for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
      return painted / (c.width * c.height);
    }), { timeout: 200_000 }).toBeGreaterThan(0.9);

    // The two shipped bugs: (1) the canvas rendered at its intrinsic buffer
    // size (a ~38px sliver) instead of filling the data rect; (2) the axis
    // SVG's opaque plot-bg hid the heat. Assert the canvas fills most of the
    // host, the overlay plot-bg is transparent, and the buffer has real
    // viridis structure (>1 distinct colour, spanning floor→peak).
    const info = await page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const host = c.closest('.plot-host') as HTMLElement;
      const r = c.getBoundingClientRect(), hr = host.getBoundingClientRect();
      const ctx = c.getContext('2d')!;
      const img = ctx.getImageData(0, 0, c.width, c.height).data;
      const colours = new Set<string>();
      let painted = 0;
      for (let i = 0; i < img.length; i += 4) {
        if (img[i + 3]) painted++;
        colours.add(`${img[i]},${img[i + 1]},${img[i + 2]}`);
      }
      const bg = document.querySelector('[data-role="plot-bg"]')?.getAttribute('fill');
      return {
        fillsHost: r.width > hr.width * 0.7 && r.height > hr.height * 0.6,
        paintedFrac: painted / (c.width * c.height),
        distinctColours: colours.size,
        plotBg: bg,
      };
    });
    expect(info.fillsHost).toBe(true);
    expect(info.plotBg).toBe('transparent');
    expect(info.paintedFrac).toBeGreaterThan(0.9);
    expect(info.distinctColours).toBeGreaterThan(3);
  });

  test('fixture → Sonogram → CWT method → Calc renders a painted heat canvas (round-5 item 12)', async ({ page }) => {
    await page.goto('/?fixture=1');
    await expect(page.getByTestId('tray-card-0')).toBeVisible();

    await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Sonogram' }).click();

    // Switch the transform to the complex Morlet CWT (constant-Q) via the
    // shared STFT | CWT segmented control, then compute through the real
    // engine (needs the rebuilt wheel that ships analysis.calculate_cwt).
    await page.getByTestId('sono-method').getByRole('button', { name: 'CWT' }).click();
    // The CWT-only controls appear; the STFT nFFT box is hidden.
    await expect(page.getByLabel('voices per octave')).toBeVisible();
    await expect(page.getByLabel('nFFT')).toHaveCount(0);

    await page.getByRole('button', { name: 'Calc Sonogram' }).click();

    const canvas = page.getByTestId('sono-canvas');
    await expect(canvas).toBeVisible({ timeout: 200_000 });
    await expect.poll(async () => page.evaluate(() => {
      const c = document.querySelector('[data-testid="sono-canvas"]') as HTMLCanvasElement;
      const img = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let painted = 0;
      for (let i = 3; i < img.length; i += 4) if (img[i]) painted++;
      return painted / (c.width * c.height);
    }), { timeout: 200_000 }).toBeGreaterThan(0.9);
  });
});
