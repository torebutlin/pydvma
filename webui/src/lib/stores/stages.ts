// stores/stages.ts
import { derived, writable } from 'svelte/store';
import type { ViewId } from './viewstate';

/**
 * One workflow stage in the bench ribbon (design spec §2). Stages are
 * UNNUMBERED — there are deliberately no digit-key shortcuts, so typing
 * a digit never switches views. `view` is the plot view a stage
 * activates (or `null` for stages like Export that keep the current
 * view), and `needs` is the capability gate that decides whether the
 * stage is enabled.
 */
export interface StageDef {
  id: 'setup' | 'acquire' | 'time' | 'frequency' | 'tf' | 'sono' | 'fit' | 'export';
  label: string;
  view: ViewId | null;               // null = keeps current view (export)
  needs: 'none' | 'liveSource' | 'fitEngine';
}
export const STAGES: StageDef[] = [
  { id: 'setup', label: 'Setup', view: null, needs: 'liveSource' },
  { id: 'acquire', label: 'Acquire', view: 'time', needs: 'liveSource' },
  { id: 'time', label: 'Time', view: 'time', needs: 'none' },
  { id: 'frequency', label: 'Frequency', view: 'frequency', needs: 'none' },
  { id: 'tf', label: 'TF', view: 'tf', needs: 'none' },
  { id: 'sono', label: 'Sonogram', view: 'sono', needs: 'none' },
  { id: 'fit', label: 'Fit', view: 'tf', needs: 'fitEngine' },   // Plan 2
  { id: 'export', label: 'Export', view: null, needs: 'none' },
];

/**
 * Capability gates for the stage ribbon. In Plan 1 both are OFF: there
 * is no live data source (acquisition arrives in Plan 2) and no mode-
 * fitting engine, so Setup/Acquire (liveSource) and Fit (fitEngine)
 * render greyed and non-clickable.
 */
export const capabilities = writable({ liveSource: false, fitEngine: false }); // Plan 1: both off
export const activeStage = writable<StageDef['id']>('time');
/**
 * Stages annotated with their current `enabled` flag: `none`-gated
 * stages are always enabled; the rest follow their capability gate.
 */
export const enabledStages = derived(capabilities, $c =>
  STAGES.map(s => ({ ...s, enabled: s.needs === 'none'
    || (s.needs === 'liveSource' && $c.liveSource)
    || (s.needs === 'fitEngine' && $c.fitEngine) })));
