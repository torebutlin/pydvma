import { expect, test, type Page } from '@playwright/test';

/**
 * Toast close buttons. NON-ENGINE: `?fixture=1` exposes `window.__toasts`,
 * so a spec can raise the same kinds of toast the app does without running
 * a fit. Lab feedback (2026-10): Refine's warning carried only Undo, so the
 * only way to accept the refined result was to leave the toast sitting there.
 */

type PushOpts = { level?: string; closable?: boolean; actions?: { label: string }[] };

/** Push a toast through the hook; each action records its label on `window.__ran`. */
async function push(page: Page, message: string, opts: PushOpts): Promise<void> {
  await page.evaluate(([m, o]) => {
    const w = window as unknown as {
      __toasts?: { push: (m: string, o: unknown) => number };
      __ran?: string[];
    };
    if (!w.__toasts) throw new Error('window.__toasts hook missing (need ?fixture=1)');
    w.__ran = [];
    const { actions, ...rest } = o as PushOpts;
    w.__toasts.push(m as string, {
      ...rest,
      actions: actions?.map((a) => ({ label: a.label, run: () => { w.__ran!.push(a.label); } })),
    });
  }, [message, opts] as const);
}

async function open(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect.poll(() => page.evaluate(() =>
    !!(window as unknown as { __toasts?: unknown }).__toasts)).toBe(true);
}

test('an Undo toast can be closed with ×, which keeps the result (runs no action)', async ({ page }) => {
  await open(page);
  const msg = 'Refine moved 1 mode(s) far from their fitted peaks';
  await push(page, msg, { level: 'info', actions: [{ label: 'Undo' }] });
  const toast = page.getByTestId('toast').filter({ hasText: msg });
  await expect(toast.getByRole('button', { name: 'Undo' })).toBeVisible();
  await toast.getByTestId('toast-close').click();
  await expect(toast).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __ran: string[] }).__ran)).toEqual([]);
});

test('an offer with its own Dismiss shows no extra ×', async ({ page }) => {
  await open(page);
  const msg = 'Restore last session?';
  await push(page, msg, { level: 'info', closable: false, actions: [{ label: 'Restore' }, { label: 'Dismiss' }] });
  const toast = page.getByTestId('toast').filter({ hasText: msg });
  await expect(toast.getByRole('button', { name: 'Restore' })).toBeVisible();
  await expect(toast.getByTestId('toast-close')).toHaveCount(0);
});
