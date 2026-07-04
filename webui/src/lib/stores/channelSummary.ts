/**
 * Column-summary helper for the data tray's channel-chip row.
 *
 * Each channel chip carries a mini tri-state dot that summarises one
 * channel index across every set that has it. This pure function folds
 * that column of per-set tri-states into a single indicator state.
 *
 * Pure — no DOM, no Svelte. Unit-tested in
 * `tests/stores/channelSummary.test.ts`.
 */

import type { TriState } from './selection';

/**
 * Summary state shown on a channel chip's dot: the three plain
 * tri-states plus `'mixed'` for a column whose sets disagree.
 */
export type ColumnState = TriState | 'mixed';

/**
 * Summarise one channel column (its tri-state across all sets that
 * expose that channel) into a single `ColumnState`:
 *
 * - empty column (no set has the channel) -> `'off'`;
 * - every set agreeing -> that shared state (`'on'`/`'fade'`/`'off'`);
 * - any disagreement -> `'mixed'`.
 */
export function summariseColumn(states: TriState[]): ColumnState {
  if (states.length === 0) return 'off';
  const first = states[0];
  return states.every(s => s === first) ? first : 'mixed';
}
