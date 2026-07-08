import { expect, test, type Page } from '@playwright/test';

/**
 * Dark theme + narrow-rail mini-monitor strip (round-5 items 11 + 14).
 *
 * The theme is stamped as `data-theme` on <html>; a Header sun/moon toggle
 * persists an explicit choice to localStorage (winning over the OS media
 * query). Exported figures are theme-independent (figure.ts keys off fixed
 * CHROME constants), so the serialised plot SVG must be byte-identical across
 * themes even though the ON-SCREEN plot recolours.
 */

/** Collect page console errors so a dark render that throws fails loudly. */
function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
  });
  page.on('pageerror', (e) => errors.push(String(e)));
  return errors;
}

const rootTheme = (page: Page) =>
  page.evaluate(() => document.documentElement.getAttribute('data-theme'));

const cssVar = (page: Page, name: string) =>
  page.evaluate(
    (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(),
    name,
  );

test('theme toggle flips the root token, renders a plot, and throws nothing', async ({ page }) => {
  const errors = trackConsoleErrors(page);
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('plot-line').first()).toBeVisible();

  // Default (Playwright Chromium reports light) → light.
  await expect.poll(() => rootTheme(page)).toBe('light');
  const lightSurface = await cssVar(page, '--surface');

  // Toggle → dark: the root token flips and the surface colour actually changes.
  await page.getByTestId('theme-toggle').click();
  await expect.poll(() => rootTheme(page)).toBe('dark');
  const darkSurface = await cssVar(page, '--surface');
  expect(darkSurface).not.toBe(lightSurface);

  // The plot still renders under dark (canvas/SVG did not blow up).
  await expect(page.getByTestId('plot-line').first()).toBeVisible();
  await expect(page.getByTestId('plot-svg')).toBeVisible();
  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([]);
});

test('the explicit choice persists across a reload (wins over the OS default)', async ({ page }) => {
  await page.goto('/?fixture=1');
  await page.getByTestId('theme-toggle').click(); // → dark
  await expect.poll(() => rootTheme(page)).toBe('dark');

  await page.reload();
  // The inline boot script re-stamps dark before first paint (persisted).
  await expect.poll(() => rootTheme(page)).toBe('dark');
  // The toggle now offers the light switch (sun glyph).
  await expect(page.getByTestId('theme-toggle')).toHaveAttribute('aria-pressed', 'true');
});

test('exported plot SVG is byte-identical across themes (export is theme-independent)', async ({
  page,
}) => {
  await page.goto('/?fixture=1');
  const svg = page.getByTestId('plot-svg');
  await expect(svg).toBeVisible();

  // Serialised source under light.
  const lightSvg = await svg.evaluate((el) => el.outerHTML);
  // The on-screen plot background follows the theme (computed CSS var).
  const lightBg = await svg
    .locator('.plot-bg')
    .evaluate((el) => getComputedStyle(el).fill);

  await page.getByTestId('theme-toggle').click();
  await expect.poll(() => rootTheme(page)).toBe('dark');

  const darkSvg = await svg.evaluate((el) => el.outerHTML);
  const darkBg = await svg
    .locator('.plot-bg')
    .evaluate((el) => getComputedStyle(el).fill);

  // Serialisation (inline CHROME hexes + data) is unchanged: exports match.
  expect(darkSvg).toBe(lightSvg);
  // …but the ON-SCREEN plot-bg actually recoloured for dark.
  expect(darkBg).not.toBe(lightBg);
  // The inline attribute the exporter reads stayed the fixed light hex.
  expect(lightSvg).toContain('fill="#ffffff"');
});

test('narrow rail shows the mini-monitor strip: idle dot, then live bars while streaming', async ({
  page,
}) => {
  await page.goto('/?narrow=1');
  const railMon = page.getByTestId('rail-mon');
  await expect(railMon).toBeVisible(); // strip docked at the rail foot
  // Idle: a tiny muted dot, no clip indicator.
  await expect(railMon.locator('.rail-mon-dot')).toBeVisible();
  await expect(railMon.getByTestId('clip-pill')).toBeHidden();

  // Clicking the strip opens the Live stage; its card can start the monitor.
  await railMon.click();
  await expect(page.getByTestId('live-scope')).toBeVisible();
  await page.getByRole('button', { name: 'Start Monitor' }).click();

  // Streaming: the strip now shows the live level bars + clip indicator.
  await expect(railMon.getByTestId('clip-pill')).toBeVisible();
  await expect(railMon.locator('.rail-mon-dot')).toBeHidden();
});
