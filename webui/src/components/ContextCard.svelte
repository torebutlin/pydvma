<script lang="ts">
  /**
   * Fixed-height context-card frame (design spec §3; visuals ported
   * from dev/mockups/round2-bench.html `.ctx-zone`).
   *
   * In WIDE mode the zone is a fixed 118px tall so the frame never
   * jumps as stages switch. The four analysis stages (time / frequency
   * / tf / sono) render their real card here, wired to the shared
   * stores + analysis actions; stages without a Task-12 card (setup /
   * acquire / fit / export) fall back to a muted placeholder that holds
   * the same frame. In NARROW mode the height relaxes to a min-height
   * and the card body may scroll (`.ctx-body` overflow) if its controls
   * exceed the frame.
   */
  import { activeStage, STAGES } from '../lib/stores/stages';
  import type { ViewState } from '../lib/stores/viewstate';
  import type { Selection } from '../lib/stores/selection';
  import type { Actions } from '../lib/analysis/actions';
  import type { AnalysisSettings } from '../lib/stores/analysisSettings';
  import type { WorkDir } from '../lib/files/workdir';
  import type { Toasts } from '../lib/stores/toast';
  import TimeCard from './cards/TimeCard.svelte';
  import FrequencyCard from './cards/FrequencyCard.svelte';
  import TFCard from './cards/TFCard.svelte';
  import SonoCard from './cards/SonoCard.svelte';
  import ExportCard from './cards/ExportCard.svelte';

  let {
    narrow = false,
    viewState,
    selection,
    actions,
    analysisSettings,
    getSvg,
    workdir,
    onsave,
    toasts,
    hasData = false,
    autosaveEnabled = $bindable(true),
  }: {
    narrow?: boolean;
    viewState: ViewState;
    selection: Selection;
    actions: Actions;
    /** Per-set analysis settings + shared target (Task R1). */
    analysisSettings: AnalysisSettings;
    /** Active plot's <svg> accessor (Export card figure source). */
    getSvg: () => SVGSVGElement | undefined;
    /** Working directory for Save Figure / Save Dataset. */
    workdir: WorkDir | null;
    /** Header's Save Dataset handler (reused by the Export card). */
    onsave: () => void;
    /** Shared toast store. */
    toasts: Toasts;
    /** Whether any dataset is loaded (gates figure export). */
    hasData?: boolean;
    autosaveEnabled?: boolean;
  } = $props();

  const labelOf = (id: string): string => STAGES.find((s) => s.id === id)?.label ?? '';

  /** Why a not-yet-built stage is empty — shown in its placeholder card. */
  const noteFor = (id: string): string =>
    id === 'setup' || id === 'acquire'
      ? 'Recording from a live input arrives in a future update. For now, Load Data to analyse an existing .dvma recording.'
      : id === 'fit'
        ? 'Modal curve-fitting arrives in a future update.'
        : 'Controls arrive in a later plan.';
</script>

<div class="ctx-zone" class:narrow>
  {#if $activeStage === 'time'}
    <TimeCard {viewState} {selection} {actions} />
  {:else if $activeStage === 'frequency'}
    <FrequencyCard {actions} {selection} {analysisSettings} />
  {:else if $activeStage === 'tf'}
    <TFCard {viewState} {selection} {actions} {analysisSettings} />
  {:else if $activeStage === 'sono'}
    <SonoCard {actions} {selection} {analysisSettings} />
  {:else if $activeStage === 'export'}
    <ExportCard {getSvg} {workdir} {onsave} {toasts} {hasData} bind:autosaveEnabled />
  {:else}
    <section class="ctx-card card-controls" aria-label="stage controls">
      <div class="ctx-name">
        <span class="cn-t">{labelOf($activeStage)}</span>
        <span class="cn-s">stage</span>
      </div>
      <div class="ctx-body">
        <span class="ctx-note">{noteFor($activeStage)}</span>
      </div>
    </section>
  {/if}
</div>

<style>
  .ctx-zone {
    flex: 0 0 auto;
    /* Grows to fit the tallest card (e.g. PSD's resolution row) rather than
       clipping/scrolling — 118px is the floor, not a fixed ceiling. */
    min-height: 118px;
    padding: 9px 16px;
    background: var(--bg);
  }
  .ctx-note {
    font-size: 12px;
    color: var(--muted);
    font-style: italic;
  }
</style>
