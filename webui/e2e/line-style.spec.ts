import { expect, test, type Page } from '@playwright/test';

/**
 * A line's colour and thickness from the tray card's ⋯ pop-up (2026-11-27,
 * 4C6 lab: two lines from two sets came out the same colour). Non-@engine:
 * the checked-in 2-channel fixture (`?fixture=1`) draws its Time lines and
 * legend on load, no compute needed.
 *
 * Asserts: ⋯ opens a pop-up on the page (not inside the tray), a swatch and
 * "bold" restyle the line in the plot, the legend and the tray chip, the set's
 * lines stay shown, Reset brings back the automatic colour and normal width,
 * and Escape / a press outside close it.
 */

const BLUE = '#2563eb';     // LINE_PALETTE[0], the fixture's ch_0
const PINK = '#be185d';     // LINE_PALETTE[6]
const PINK_RGB = 'rgb(190, 24, 93)';

const card0 = (page: Page) => page.getByTestId('tray-card-0');
const firstLine = (page: Page) => page.getByTestId('plot-line').first();

test('⋯ picks a line\'s colour and weight; Reset puts it back', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(firstLine(page)).toHaveAttribute('stroke', BLUE);
  await expect(firstLine(page)).toHaveAttribute('stroke-width', '1.5');

  await card0(page).getByTestId('line-style-open').click();
  const pop = page.getByTestId('line-style-panel');
  await expect(pop).toBeVisible();
  // On the page itself, not inside the scrolling tray, so it is never clipped.
  expect(await pop.evaluate((el) => el.parentElement === document.body)).toBe(true);
  const box = (await pop.boundingBox())!;
  const vp = page.viewportSize()!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(vp.width);
  expect(box.y + box.height).toBeLessThanOrEqual(vp.height);

  await pop.getByTestId('line-swatch-0-6').click();
  await pop.getByTestId('line-weight-0-bold').click();

  await expect(firstLine(page)).toHaveAttribute('stroke', PINK);
  await expect(firstLine(page)).toHaveAttribute('stroke-width', '2.5');
  await expect(pop.getByTestId('line-swatch-0-6')).toHaveAttribute('aria-pressed', 'true');
  await expect(card0(page).getByTestId('ch-row-0').locator('.ch-chip'))
    .toHaveCSS('background-color', PINK_RGB);
  const legendRow = page.getByTestId('legend').getByTestId('legend-entry')
    .filter({ hasText: 'webui fixture · ch_0' });
  await expect(legendRow.locator('.swatch')).toHaveCSS('background-color', PINK_RGB);
  // The legend's key line is drawn bolder too (normal 3 px, bold 5 px).
  await expect(legendRow.locator('.swatch')).toHaveCSS('height', '5px');
  // Picking a style never hides or fades the line.
  await expect(card0(page).getByTestId('ch-row-0').locator('.state-badge')).toHaveText('on');
  await expect(pop).toBeVisible();

  await pop.getByTestId('line-style-reset').click();
  await expect(firstLine(page)).toHaveAttribute('stroke', BLUE);
  await expect(firstLine(page)).toHaveAttribute('stroke-width', '1.5');

  await page.keyboard.press('Escape');
  await expect(pop).toHaveCount(0);
});

test('a press outside the pop-up closes it; Done closes it too', async ({ page }) => {
  await page.goto('/?fixture=1');
  await expect(firstLine(page)).toBeVisible();
  const open = card0(page).getByTestId('line-style-open');

  await open.click();
  await expect(page.getByTestId('line-style-panel')).toBeVisible();
  await page.mouse.click(5, 5);
  await expect(page.getByTestId('line-style-panel')).toHaveCount(0);

  await open.click();
  await page.getByTestId('line-style-done').click();
  await expect(page.getByTestId('line-style-panel')).toHaveCount(0);

  // ⋯ again while open closes it rather than reopening.
  await open.click();
  await expect(page.getByTestId('line-style-panel')).toBeVisible();
  await open.click();
  await expect(page.getByTestId('line-style-panel')).toHaveCount(0);
});

test('the ⋯ stays where it is when the card is hovered', async ({ page }) => {
  // cal and × appear only on hover; a ⋯ placed before them jumped sideways as
  // the pointer arrived, and the click landed on the header (fading the set).
  await page.goto('/?fixture=1');
  await expect(firstLine(page)).toBeVisible();
  const open = card0(page).getByTestId('line-style-open');
  await page.mouse.move(5, 5);
  const before = (await open.boundingBox())!;
  await card0(page).getByTestId('set-header').hover({ position: { x: 30, y: 8 } });
  await expect(card0(page).locator('.xdel')).toBeVisible();
  const after = (await open.boundingBox())!;
  expect(Math.abs(after.x - before.x)).toBeLessThan(0.5);
});


test('in the narrow layout the pop-up opens over the tray drawer', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/?fixture=1');
  await page.getByTestId('rail-more').click();
  const tray = page.getByTestId('tray');
  await tray.getByTestId('line-style-open').click();
  const pop = page.getByTestId('line-style-panel');
  await expect(pop).toBeVisible();
  // Topmost where it sits: not hidden behind the drawer.
  const onTop = await pop.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return el.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
  });
  expect(onTop).toBe(true);
  const box = (await pop.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(375);
  await pop.getByTestId('line-swatch-1-2').click();
  await expect(tray.getByTestId('ch-row-1').locator('.ch-chip')).toHaveCSS('background-color', 'rgb(5, 150, 105)');
});
