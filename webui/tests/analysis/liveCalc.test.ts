import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createLiveCalc } from '../../src/lib/analysis/liveCalc';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test('does not fire until the debounce elapses', () => {
  let n = 0;
  const { schedule } = createLiveCalc(() => true, () => { n += 1; }, 150);
  schedule();
  vi.advanceTimersByTime(149);
  expect(n).toBe(0);
  vi.advanceTimersByTime(1);
  expect(n).toBe(1);
});

test('rapid schedules coalesce to a single trailing recompute', () => {
  let n = 0;
  const { schedule } = createLiveCalc(() => true, () => { n += 1; }, 150);
  schedule(); schedule(); schedule();          // e.g. dragging a slider
  vi.advanceTimersByTime(200);
  expect(n).toBe(1);                           // one recompute, not three
});

test('stays button-gated: never fires while hasResult() is false', () => {
  let has = false;
  let n = 0;
  const { schedule } = createLiveCalc(() => has, () => { n += 1; }, 150);
  schedule();
  vi.advanceTimersByTime(300);
  expect(n, 'no result yet → a tweak must not recompute (no engine boot)').toBe(0);
  // Once a first result exists (Calc pressed), live recompute kicks in.
  has = true;
  schedule();
  vi.advanceTimersByTime(200);
  expect(n).toBe(1);
});

test('cancel drops a pending recompute', () => {
  let n = 0;
  const { schedule, cancel } = createLiveCalc(() => true, () => { n += 1; }, 150);
  schedule();
  cancel();
  vi.advanceTimersByTime(300);
  expect(n).toBe(0);
});
