<script lang="ts">
  /**
   * Floating plot-navigation toolbar (design spec §6). Visuals ported
   * from the `.zoom-bar` / `.zbtn` / `#axPop` styles in
   * `dev/mockups/round2-bench.html`. Positions itself top-right of its
   * nearest positioned ancestor — mount it inside the plot host next
   * to `PlotSurface`.
   *
   * Wiring contract (documented design choice): the toolbar takes the
   * WHOLE view-state store object rather than narrow callbacks — every
   * button maps 1:1 onto a store method (`back` / `forward` /
   * `setRange` / `autoFit` targets) and the manual-limits popover must
   * READ `current.range` for its two-way sync, so callbacks would just
   * re-implement the store surface. The store's identity must be
   * stable for the component's lifetime (it is created once at app
   * startup).
   *
   * `mode` (box-zoom vs pan) is deliberately toolbar-LOCAL UI state —
   * not serialised with the view state — exposed as a bindable prop so
   * the parent can feed it to `PlotSurface`. Default is box-zoom (the
   * labsheet teaches box-zoom first).
   *
   * Auto X sets the x-range to the full data extent (y untouched);
   * Auto Y sets the y-range to the extent of the lines CURRENTLY
   * visible in the plot model — off lines are excluded upstream by the
   * selection filter, which implements spec §6 "Auto Y fits selected
   * lines only". Both are single history entries. The parent passes
   * that extent via `dataExtent` (compute it from the model's lines
   * with `dataExtent()` from `lib/plot/build`).
   *
   * The `⋯` popover two-way syncs with the store: its min/max fields
   * re-seed whenever the view's range changes (falling back to the
   * data extent while an axis is auto-fit); edits reach the store only
   * via Apply (validated: numeric, max > min).
   */
  import type { ViewState } from '../lib/stores/viewstate';
  import { fmtTick } from '../lib/plot/scales';
  import { presetToXY, type LegendPreset } from '../lib/plot/legendPos';

  let {
    viewState,
    dataExtent,
    mode = $bindable('box'),
  }: {
    viewState: ViewState;
    /** X/Y extent of the lines currently visible in the plot model. */
    dataExtent: { x: [number, number]; y: [number, number] };
    /** Active drag tool; bind and pass through to PlotSurface. */
    mode?: 'box' | 'pan';
  } = $props();

  // Derived (not destructured) so the toolbar tracks a reassigned viewState prop.
  const current = $derived(viewState.current);
  const active = $derived(viewState.active);
  const uid = $props.id();

  let popOpen = $state(false);
  let xminS = $state(''), xmaxS = $state(''), yminS = $state(''), ymaxS = $state('');
  let limitsError = $state('');

  /** What the plot is actually showing: explicit range or auto-fit extent. */
  const shown = $derived({
    x: $current.range.x ?? dataExtent.x,
    y: $current.range.y ?? dataExtent.y,
  });

  // Store → fields sync: re-seed whenever the underlying range moves.
  // Typing only touches the field states, so it never re-triggers this.
  $effect(() => {
    xminS = fmtTick(shown.x[0], shown.x[1] - shown.x[0]);
    xmaxS = fmtTick(shown.x[1], shown.x[1] - shown.x[0]);
    yminS = fmtTick(shown.y[0], shown.y[1] - shown.y[0]);
    ymaxS = fmtTick(shown.y[1], shown.y[1] - shown.y[0]);
    limitsError = '';
  });

  function autoX() {
    viewState.setRange($active, { x: [dataExtent.x[0], dataExtent.x[1]], y: $current.range.y });
  }
  function autoY() {
    viewState.setRange($active, { x: $current.range.x, y: [dataExtent.y[0], dataExtent.y[1]] });
  }

  function applyLimits() {
    const x0 = parseFloat(xminS), x1 = parseFloat(xmaxS);
    const y0 = parseFloat(yminS), y1 = parseFloat(ymaxS);
    if (![x0, x1, y0, y1].every(Number.isFinite) || x1 <= x0 || y1 <= y0) {
      limitsError = 'Limits must be numeric with max > min.';
      return;
    }
    viewState.setRange($active, { x: [x0, x1], y: [y0, y1] });
    popOpen = false;
  }

  // ---- Legend controls (mirrors into the active view's legend slice) ----

  /** The active view's legend slice, read live for two-way sync. */
  const legend = $derived($current.legend);

  /** Preset buttons, labelled for the popover row. */
  const PRESETS: { id: LegendPreset; label: string }[] = [
    { id: 'ne', label: 'NE' }, { id: 'nw', label: 'NW' },
    { id: 'se', label: 'SE' }, { id: 'sw', label: 'SW' },
    { id: 'outside-right', label: 'Out ▸' },
  ];

  /** Show/hide the legend without disturbing its placement. */
  function setLegendVisible(visible: boolean) {
    viewState.setLegend($active, { ...legend, visible });
  }

  /** Snap the legend to a corner/edge preset (records the preset id). */
  function applyPreset(id: LegendPreset) {
    const { x, y } = presetToXY(id);
    viewState.setLegend($active, { ...legend, x, y, preset: id });
  }
</script>

<div class="zoom-bar" data-testid="zoom-toolbar" role="toolbar" aria-label="Plot navigation">
  <button class="zbtn" class:active={mode === 'box'} aria-pressed={mode === 'box'}
    title="Box zoom — drag a rectangle on the plot" onclick={() => (mode = 'box')}>◱</button>
  <button class="zbtn" class:active={mode === 'pan'} aria-pressed={mode === 'pan'}
    title="Pan — drag to move the axes" onclick={() => (mode = 'pan')}>✥</button>
  <button class="zbtn" title="Back (previous axis range)"
    onclick={() => viewState.back($active)}>‹</button>
  <button class="zbtn" title="Forward"
    onclick={() => viewState.forward($active)}>›</button>
  <button class="zbtn" title="Autoscale X" onclick={autoX}>Auto X</button>
  <button class="zbtn" title="Autoscale Y (fits selected lines only)" onclick={autoY}>Auto Y</button>
  <button class="zbtn" class:active={popOpen} aria-expanded={popOpen}
    title="Manual axis limits" onclick={() => (popOpen = !popOpen)}>⋯</button>
</div>

{#if popOpen}
  <div class="ax-pop" data-testid="axis-popover">
    <div class="row">
      <label for="{uid}-xmin">xmin</label><input id="{uid}-xmin" bind:value={xminS} />
      <label for="{uid}-xmax">xmax</label><input id="{uid}-xmax" bind:value={xmaxS} />
    </div>
    <div class="row">
      <label for="{uid}-ymin">ymin</label><input id="{uid}-ymin" bind:value={yminS} />
      <label for="{uid}-ymax">ymax</label><input id="{uid}-ymax" bind:value={ymaxS} />
    </div>
    {#if limitsError}<div class="err" role="alert">{limitsError}</div>{/if}
    <div class="row end">
      <button class="btn" onclick={() => (popOpen = false)}>Cancel</button>
      <button class="btn apply" onclick={applyLimits}>Apply</button>
    </div>

    <div class="sep"></div>
    <div class="row">
      <span class="grp">Legend</span>
      <label class="toggle">
        <input type="checkbox" checked={legend.visible}
          onchange={(e) => setLegendVisible(e.currentTarget.checked)} />
        <span>Show</span>
      </label>
    </div>
    <div class="row presets" data-testid="legend-presets">
      {#each PRESETS as p (p.id)}
        <button class="pbtn" class:active={legend.visible && legend.preset === p.id}
          title="Move legend: {p.label}" onclick={() => applyPreset(p.id)}>{p.label}</button>
      {/each}
    </div>
  </div>
{/if}

<style>
  .zoom-bar {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 6;
    display: flex;
    gap: 3px;
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 8px;
    padding: 3px;
    box-shadow: var(--shadow, 0 1px 3px rgba(16, 24, 40, 0.12));
  }
  .zbtn {
    border: 1px solid transparent;
    background: transparent;
    border-radius: 6px;
    min-width: 26px;
    height: 24px;
    padding: 0 6px;
    cursor: pointer;
    color: var(--muted, #66708a);
    font: 600 11.5px var(--font-body, system-ui, sans-serif);
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .zbtn:hover {
    background: #f2f4f8;
    color: var(--text, #1b2437);
  }
  .zbtn.active {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo, #4f46e5);
  }
  .ax-pop {
    position: absolute;
    top: 38px;
    right: 8px;
    z-index: 8;
    background: var(--surface, #ffffff);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: var(--radius, 10px);
    box-shadow: 0 8px 28px rgba(16, 24, 40, 0.16);
    padding: 11px 13px;
  }
  .ax-pop .row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 5px 0;
  }
  .ax-pop .row.end {
    justify-content: flex-end;
  }
  .ax-pop label {
    font: 11.5px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--muted, #66708a);
    width: 34px;
  }
  .ax-pop input {
    width: 84px;
    font-family: var(--font-mono, ui-monospace, Menlo, monospace);
    font-size: 12px;
  }
  .err {
    font-size: 11px;
    color: #b91c1c;
    margin: 4px 0;
    max-width: 250px;
  }
  .btn {
    border: 1px solid var(--border, #e3e6eb);
    background: #fff;
    border-radius: 6px;
    height: 24px;
    padding: 0 10px;
    font: 600 11.5px var(--font-body, system-ui, sans-serif);
    color: var(--text, #1b2437);
    cursor: pointer;
  }
  .btn:hover {
    background: #f2f4f8;
  }
  .btn.apply {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo, #4f46e5);
  }
  .sep {
    height: 1px;
    background: var(--border, #e3e6eb);
    margin: 9px 0 7px;
  }
  .grp {
    font: 600 11.5px var(--font-body, system-ui, sans-serif);
    color: var(--text, #1b2437);
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-left: auto;
    font: 11.5px var(--font-body, system-ui, sans-serif);
    color: var(--muted, #66708a);
    width: auto;
    cursor: pointer;
  }
  .presets {
    gap: 4px;
    flex-wrap: wrap;
  }
  .pbtn {
    border: 1px solid var(--border, #e3e6eb);
    background: #fff;
    border-radius: 6px;
    height: 24px;
    min-width: 34px;
    padding: 0 7px;
    font: 600 11px var(--font-body, system-ui, sans-serif);
    color: var(--text, #1b2437);
    cursor: pointer;
  }
  .pbtn:hover {
    background: #f2f4f8;
  }
  .pbtn.active {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo, #4f46e5);
  }
</style>
