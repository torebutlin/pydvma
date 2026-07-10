import { get } from 'svelte/store';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createToasts } from '../../src/lib/stores/toast';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test('info/success toasts auto-dismiss after the default 4 s', () => {
  const t = createToasts();
  t.push('saved', { level: 'success' });
  t.push('note', { level: 'info' });
  expect(get(t.toasts)).toHaveLength(2);
  vi.advanceTimersByTime(4100);
  expect(get(t.toasts)).toHaveLength(0);
});

test('ERROR toasts pin open until dismissed (round-10, JW: message vanished before he could copy it)', () => {
  const t = createToasts();
  const id = t.push('Load failed: KeyError npts', { level: 'error' });
  vi.advanceTimersByTime(60_000);
  expect(get(t.toasts)).toHaveLength(1);         // still there a minute later
  t.dismiss(id);                                  // the × button's path
  expect(get(t.toasts)).toHaveLength(0);
});

test('an explicit timeout still makes an error transient', () => {
  const t = createToasts();
  t.push('transient error', { level: 'error', timeout: 1000 });
  vi.advanceTimersByTime(1100);
  expect(get(t.toasts)).toHaveLength(0);
});

test('actionable toasts pin open and close after their action runs', () => {
  const t = createToasts();
  let ran = false;
  t.push('Restore last session?', { actions: [{ label: 'Restore', run: () => { ran = true; } }] });
  vi.advanceTimersByTime(60_000);
  const list = get(t.toasts);
  expect(list).toHaveLength(1);
  list[0].actions![0].run();
  expect(ran).toBe(true);
  expect(get(t.toasts)).toHaveLength(0);
});
