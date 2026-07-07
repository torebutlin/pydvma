<script lang="ts">
  /**
   * Stage ribbon (design spec §2; visuals ported from
   * dev/mockups/round2-bench.html `.ribbon`). Wrapped in
   * `<nav aria-label="stages">`.
   *
   * Quiet, UNNUMBERED stage buttons driven by the `enabledStages`
   * derived store — there are no numbers and no digit-key shortcuts, so
   * typing a digit never switches views. The active stage gets a filled
   * pill; the row horizontally scrolls when it overflows.
   *
   * Clicking an ENABLED stage sets `activeStage` and, when the stage
   * declares a `view`, calls `viewState.activate(view)`. DISABLED stages
   * (their capability gate is off in Plan 1) are greyed, carry an
   * explanatory `title`, and are not clickable.
   *
   * The `narrow` prop (not viewport media queries) drives the compact
   * layout, so `?narrow=1` forces it deterministically for tests. In
   * narrow mode the labels stay as WORDS (never icon-only); only
   * "Frequency" abbreviates to "Freq".
   */
  import type { ViewState } from '../lib/stores/viewstate';
  import { activeStage, enabledStages, type StageDef } from '../lib/stores/stages';

  let { viewState, narrow = false }: { viewState: ViewState; narrow?: boolean } = $props();

  /** Label to show, abbreviating only Frequency -> Freq in narrow mode. */
  const labelFor = (s: StageDef): string =>
    narrow && s.id === 'frequency' ? 'Freq' : s.label;

  /** Explain why a gated stage has no controls yet (design spec §2 tooltips). */
  const disabledTitle = (s: StageDef): string =>
    s.needs === 'liveSource'
      ? 'Recording from a live input arrives in a future update'
      : 'Fit needs a computed transfer function — run Calc TF first';

  // Gated stages (Setup/Acquire/Fit in Plan 1) are still NAVIGABLE: clicking
  // one selects it and shows an explanatory placeholder card, rather than a
  // dead-grey no-op. Activating its view (when it has one) is harmless.
  function select(s: StageDef & { enabled: boolean }) {
    activeStage.set(s.id);
    if (s.view !== null) viewState.activate(s.view);
  }
</script>

<nav class="ribbon" class:narrow aria-label="stages">
  {#each $enabledStages as s, i (s.id)}
    {#if i > 0}<span class="sep" aria-hidden="true">·</span>{/if}
    <button
      class="stage"
      class:active={$activeStage === s.id}
      class:gated={!s.enabled}
      title={s.enabled ? s.label : disabledTitle(s)}
      onclick={() => select(s)}
    >{labelFor(s)}</button>
  {/each}
</nav>

<style>
  .ribbon {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    gap: 1px;
    padding: 6px 16px 5px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  .ribbon.narrow {
    overflow-x: auto;
  }
  .stage {
    border: 1px solid transparent;
    background: transparent;
    border-radius: 8px;
    height: 29px;
    padding: 0 12px;
    font: 500 12.5px inherit;
    font-family: inherit;
    color: var(--muted);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
  }
  .stage:hover:not(:disabled) {
    color: var(--text);
    background: #f6f7fa;
  }
  .stage.active {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo);
    font-weight: 600;
  }
  /* Gated stages read as "available to visit, not yet built" — dimmed but
     still clickable (they show an explanatory placeholder), not dead-grey. */
  .stage.gated:not(.active) {
    color: #b0b6c4;
  }
  .stage.gated:not(.active):hover {
    color: var(--text);
    background: #f6f7fa;
  }
  .sep {
    color: #d3d8e2;
    font-size: 12px;
    padding: 0 3px;
    user-select: none;
  }
</style>
