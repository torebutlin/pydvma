/**
 * Tests for the stages store — verifies the stage list, capability
 * gates, and the Live tab's position in the ribbon.
 */
import { get } from 'svelte/store';
import { expect, test, beforeEach } from 'vitest';
import { STAGES, capabilities, enabledStages } from '../../src/lib/stores/stages';

beforeEach(() => {
  capabilities.set({ liveSource: false, fitEngine: false });
});

test('Live stage exists between Acquire and Time', () => {
  const ids = STAGES.map((s) => s.id);
  const acquireIdx = ids.indexOf('acquire');
  const liveIdx = ids.indexOf('live');
  const timeIdx = ids.indexOf('time');
  expect(liveIdx).toBeGreaterThan(acquireIdx);
  expect(liveIdx).toBeLessThan(timeIdx);
});

test('Live stage is gated on liveSource', () => {
  const liveDef = STAGES.find((s) => s.id === 'live');
  expect(liveDef).toBeDefined();
  expect(liveDef!.needs).toBe('liveSource');
});

test('Live is disabled when liveSource is false', () => {
  const stages = get(enabledStages);
  const live = stages.find((s) => s.id === 'live');
  expect(live).toBeDefined();
  expect(live!.enabled).toBe(false);
});

test('Live is enabled when liveSource flips true', () => {
  capabilities.set({ liveSource: true, fitEngine: false });
  const stages = get(enabledStages);
  const live = stages.find((s) => s.id === 'live');
  expect(live!.enabled).toBe(true);
});

test('all nine stages are present', () => {
  expect(STAGES).toHaveLength(9);
  const ids = STAGES.map((s) => s.id);
  expect(ids).toEqual([
    'setup', 'acquire', 'live', 'time', 'frequency', 'tf', 'sono', 'fit', 'export',
  ]);
});
