<script lang="ts">
  /**
   * Floating plot-navigation toolbar (design spec §6; round-4 redesign).
   * Visuals descend from the `.zoom-bar` / `.zbtn` / `#axPop` styles in
   * `dev/mockups/round2-bench.html`. Positions itself top-right of its
   * nearest positioned ancestor — mount it inside the plot host next to
   * `PlotSurface`.
   *
   * Wiring contract (documented design choice): the toolbar takes the WHOLE
   * view-state store object rather than narrow callbacks — every button maps
   * 1:1 onto a store method (`back` / `forward` / `setRange` / `autoFit`
   * targets) and the manual-limits panel must READ `current.range` for its
   * two-way sync, so callbacks would just re-implement the store surface.
   * The store's identity must be stable for the component's lifetime (it is
   * created once at app startup).
   *
   * `mode` (box-zoom vs pan) is deliberately toolbar-LOCAL UI state — not
   * serialised with the view state — exposed as a bindable prop so the parent
   * can feed it to `PlotSurface`. Default is box-zoom (the labsheet teaches
   * box-zoom first).
   *
   * ── round-4 controls redesign (feedback item 7) ──
   * - The `‹ ›` nav arrows were view-HISTORY back/forward: every committed
   *   box-zoom / pan / auto-fit pushes a history entry (see viewstate.ts), so
   *   these are genuinely UNDO / REDO of view-range changes — now drawn as the
   *   standard curl arrows `↶ ↷` with explicit "Undo/Redo view change" titles.
   * - Bigger, clearer box-zoom + pan glyphs (crisp inline SVG, not tiny text).
   * - The `⋯` popover is replaced by an expander chevron; HOVERING the toolbar
   *   auto-opens the panel (pointerenter) and leaving collapses it after a
   *   short delay (pointerleave). A click PINS / unpins it open for touch,
   *   where there is no hover.
   * - Manual axis limits apply LIVE (debounced ~300 ms; no Apply button) and
   *   are laid out transposed: xmin/xmax stacked in a bordered `x` group on the
   *   left, ymin/ymax stacked in a `y` group on the right.
   * - Legend placement is a 2×2 corner grid (matching the plot corners) plus an
   *   "outside" option and a show toggle.
   *
   * Auto X sets the x-range to the full data extent (y untouched); Auto Y sets
   * the y-range to the extent of the lines CURRENTLY visible in the plot model
   * — off lines are excluded upstream by the selection filter (spec §6 "Auto Y
   * fits selected lines only"). Both are single history entries. The parent
   * passes that extent via `dataExtent` (compute it with `dataExtent()` from
   * `lib/plot/build`).
   *
   * The manual-limits panel two-way syncs with the store: its min/max fields
   * re-seed whenever the view's range changes (falling back to the data extent
   * while an axis is auto-fit), EXCEPT while the user is mid-edit (`dirty`), so
   * a live-committed edit never clobbers what is still being typed.
   */
  import type { ViewState } from '../lib/stores/viewstate';
  import { fmtTick } from '../lib/plot/scales';
  import { presetToXY, type LegendPreset } from '../lib/plot/legendPos';
  import Segmented from './Segmented.svelte';

  let {
    viewState,
    dataExtent,
    mode = $bindable('box'),
    showXScale = false,
    showYScale = false,
  }: {
    viewState: ViewState;
    /** X/Y extent of the lines currently visible in the plot model. */
    dataExtent: { x: [number, number]; y: [number, number] };
    /** Active drag tool; bind and pass through to PlotSurface. */
    mode?: 'box' | 'pan';
    /**
     * Show the frequency x-axis lin↔log segmented control (R3). App passes
     * `true` only on frequency/tf views (where x is frequency); the time/sono
     * views leave it off — log time is nonsensical.
     */
    showXScale?: boolean;
    /**
     * Show the magnitude dB↔linear segmented control (R3). App passes `true`
     * only on magnitude-capable views/sub-modes (FFT mag / PSD / TF mag /
     * Bode-mag); it stays off on phase/real/imag/Nyquist so the label never
     * misrepresents a non-magnitude pane.
     */
    showYScale?: boolean;
  } = $props();

  // Derived (not destructured) so the toolbar tracks a reassigned viewState prop.
  const current = $derived(viewState.current);
  const active = $derived(viewState.active);
  const uid = $props.id();

  // Live axis-scale state for the segmented controls (R3).
  const xScale = $derived($current.xScale);
  const yScale = $derived($current.yScale);

  // ---- expander: hover auto-opens, click pins (touch) ----
  let pinned = $state(false);
  let hovered = $state(false);
  const open = $derived(pinned || hovered);
  let leaveTimer: ReturnType<typeof setTimeout> | undefined;

  function onEnter() {
    if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = undefined; }
    hovered = true;
  }
  function onLeave() {
    // Small delay so crossing the gap between the bar and the panel (or a
    // brief exit) doesn't flicker it shut mid-reach.
    if (leaveTimer) clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => { hovered = false; leaveTimer = undefined; }, 160);
  }

  // ---- manual axis limits (live, debounced) ----
  let xminS = $state(''), xmaxS = $state(''), yminS = $state(''), ymaxS = $state('');
  let limitsError = $state('');
  // True from the first keystroke until a debounced commit lands (or the panel
  // closes). Gates the store→fields re-seed so a live commit can't overwrite a
  // half-typed value.
  let dirty = $state(false);
  let commitTimer: ReturnType<typeof setTimeout> | undefined;

  /** What the plot is actually showing: explicit range or auto-fit extent. */
  const shown = $derived({
    x: $current.range.x ?? dataExtent.x,
    y: $current.range.y ?? dataExtent.y,
  });

  // Store → fields sync: re-seed whenever the underlying range moves, unless
  // the user is mid-edit. Typing sets `dirty`, so this never fights the caret.
  $effect(() => {
    const s = shown;
    if (dirty) return;
    xminS = fmtTick(s.x[0], s.x[1] - s.x[0]);
    xmaxS = fmtTick(s.x[1], s.x[1] - s.x[0]);
    yminS = fmtTick(s.y[0], s.y[1] - s.y[0]);
    ymaxS = fmtTick(s.y[1], s.y[1] - s.y[0]);
    limitsError = '';
  });

  // Closing the panel abandons any half-typed / pending edit so the next open
  // re-seeds cleanly from the store.
  $effect(() => {
    if (!open) {
      if (commitTimer) { clearTimeout(commitTimer); commitTimer = undefined; }
      dirty = false;
      limitsError = '';
    }
  });

  /** Validate the four fields and commit ONE setRange; invalid → show error, no write. */
  function commitLimits() {
    commitTimer = undefined;
    const x0 = parseFloat(xminS), x1 = parseFloat(xmaxS);
    const y0 = parseFloat(yminS), y1 = parseFloat(ymaxS);
    if (![x0, x1, y0, y1].every(Number.isFinite) || x1 <= x0 || y1 <= y0) {
      limitsError = 'Limits must be numeric with max > min.';
      return;   // keep `dirty` so a valid range change can't clobber the edit
    }
    limitsError = '';
    dirty = false;
    viewState.setRange($active, { x: [x0, x1], y: [y0, y1] });
  }

  /** A field changed: mark dirty and debounce a live commit (~300 ms). */
  function onLimitInput() {
    dirty = true;
    limitsError = '';
    if (commitTimer) clearTimeout(commitTimer);
    commitTimer = setTimeout(commitLimits, 300);
  }

  function autoX() {
    viewState.setRange($active, { x: [dataExtent.x[0], dataExtent.x[1]], y: $current.range.y });
  }
  function autoY() {
    viewState.setRange($active, { x: $current.range.x, y: [dataExtent.y[0], dataExtent.y[1]] });
  }

  $effect(() => () => {
    if (leaveTimer) clearTimeout(leaveTimer);
    if (commitTimer) clearTimeout(commitTimer);
  });

  // ---- Legend controls (mirrors into the active view's legend slice) ----

  /** The active view's legend slice, read live for two-way sync. */
  const legend = $derived($current.legend);

  /** Corner presets laid out to MATCH their plot corners (2×2 grid). */
  const CORNERS: { id: LegendPreset; label: string }[] = [
    { id: 'nw', label: 'NW' }, { id: 'ne', label: 'NE' },
    { id: 'sw', label: 'SW' }, { id: 'se', label: 'SE' },
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

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="zoom-wrap" onpointerenter={onEnter} onpointerleave={onLeave}>
  <div class="zoom-bar" data-testid="zoom-toolbar" role="toolbar" aria-label="Plot navigation">
    <button class="zbtn glyph" class:active={mode === 'box'} aria-pressed={mode === 'box'}
      aria-label="Box zoom" title="Box zoom — drag a rectangle on the plot" onclick={() => (mode = 'box')}>
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor"
        stroke-width="1.4" aria-hidden="true">
        <rect x="2.3" y="2.3" width="11.4" height="11.4" rx="1.4" stroke-dasharray="2.6 1.7" />
        <rect x="5.4" y="5.4" width="5.2" height="5.2" rx="0.8" fill="currentColor"
          fill-opacity="0.16" stroke="none" />
      </svg>
    </button>
    <button class="zbtn glyph" class:active={mode === 'pan'} aria-pressed={mode === 'pan'}
      aria-label="Pan" title="Pan — drag to move the axes" onclick={() => (mode = 'pan')}>
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor"
        stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M8 1.6v12.8M1.6 8h12.8" />
        <path d="M8 1.6 6.3 3.5M8 1.6l1.7 1.9M8 14.4l-1.7-1.9M8 14.4l1.7-1.9
                 M1.6 8l1.9-1.7M1.6 8l1.9 1.7M14.4 8l-1.9-1.7M14.4 8l-1.9 1.7" />
      </svg>
    </button>

    <span class="zdiv" aria-hidden="true"></span>

    <button class="zbtn undo" title="Undo view change (previous axis range)"
      aria-label="Undo view change" onclick={() => viewState.back($active)}>↶</button>
    <button class="zbtn undo" title="Redo view change (next axis range)"
      aria-label="Redo view change" onclick={() => viewState.forward($active)}>↷</button>

    <span class="zdiv" aria-hidden="true"></span>

    <button class="zbtn" title="Autoscale X to the full data extent" onclick={autoX}>Auto X</button>
    <button class="zbtn" title="Autoscale Y (fits selected lines only)" onclick={autoY}>Auto Y</button>

    {#if showXScale || showYScale}
      <span class="zdiv" aria-hidden="true"></span>
      {#if showXScale}
        <Segmented
          testid="xscale-toggle"
          ariaLabel="Frequency axis scale"
          label="x"
          value={xScale}
          onchange={(s) => viewState.setXScale(s)}
          options={[
            { value: 'lin', label: 'lin', title: 'Linear frequency axis' },
            { value: 'log', label: 'log', title: 'Log10 frequency axis (decades)' },
          ]}
        />
      {/if}
      {#if showYScale}
        <Segmented
          testid="yscale-toggle"
          ariaLabel="Magnitude scale"
          label="y"
          value={yScale}
          onchange={(s) => viewState.setYScale(s)}
          options={[
            { value: 'log', label: 'dB', title: 'Magnitude in dB (log)' },
            { value: 'lin', label: 'lin', title: 'Linear magnitude' },
          ]}
        />
      {/if}
    {/if}

    <span class="zdiv" aria-hidden="true"></span>

    <button class="zbtn chevron" class:active={open} class:pinned aria-expanded={open}
      aria-label="More plot controls" title="Axis limits & legend — hover to open, click to pin"
      data-testid="zoom-expand" onclick={() => (pinned = !pinned)}>
      <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor"
        stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
        class="chev-icon" class:up={open}>
        <path d="M4 6l4 4 4-4" />
      </svg>
    </button>
  </div>

  {#if open}
    <div class="ax-pop" data-testid="axis-popover">
      <div class="limits" role="group" aria-label="Manual axis limits">
        <div class="axgrp">
          <span class="axgrp-lab">x</span>
          <div class="axfield">
            <label for="{uid}-xmin">min</label>
            <input id="{uid}-xmin" bind:value={xminS} oninput={onLimitInput} inputmode="decimal" />
          </div>
          <div class="axfield">
            <label for="{uid}-xmax">max</label>
            <input id="{uid}-xmax" bind:value={xmaxS} oninput={onLimitInput} inputmode="decimal" />
          </div>
        </div>
        <div class="axgrp">
          <span class="axgrp-lab">y</span>
          <div class="axfield">
            <label for="{uid}-ymin">min</label>
            <input id="{uid}-ymin" bind:value={yminS} oninput={onLimitInput} inputmode="decimal" />
          </div>
          <div class="axfield">
            <label for="{uid}-ymax">max</label>
            <input id="{uid}-ymax" bind:value={ymaxS} oninput={onLimitInput} inputmode="decimal" />
          </div>
        </div>
      </div>
      {#if limitsError}<div class="err" role="alert">{limitsError}</div>{/if}

      <div class="sep"></div>

      <div class="legrow">
        <span class="grp">Legend</span>
        <label class="toggle">
          <input type="checkbox" checked={legend.visible}
            onchange={(e) => setLegendVisible(e.currentTarget.checked)} />
          <span>Show</span>
        </label>
      </div>
      <div class="legend-place" data-testid="legend-presets">
        <div class="corner-grid">
          {#each CORNERS as p (p.id)}
            <button class="pbtn" class:active={legend.visible && legend.preset === p.id}
              title="Move legend: {p.label}" onclick={() => applyPreset(p.id)}>{p.label}</button>
          {/each}
        </div>
        <button class="pbtn outside" class:active={legend.visible && legend.preset === 'outside-right'}
          title="Move legend: outside (right of the plot)"
          onclick={() => applyPreset('outside-right')}>Outside ▸</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .zoom-wrap {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 6;
  }
  .zoom-bar {
    display: flex;
    align-items: center;
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
    min-width: 28px;
    height: 28px;
    padding: 0 7px;
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
  /* Icon buttons: give the glyph room so it reads clearly (feedback: too tiny). */
  .zbtn.glyph {
    min-width: 30px;
    padding: 0 6px;
  }
  .zbtn.glyph svg {
    display: block;
  }
  /* Curl undo/redo arrows, sized up so they're unmistakable. */
  .zbtn.undo {
    font-size: 16px;
    line-height: 1;
    padding-bottom: 2px;
  }
  .chev-icon {
    transition: transform 0.15s ease;
  }
  .chev-icon.up {
    transform: rotate(180deg);
  }
  /* Thin separators between logical button groups. */
  .zdiv {
    width: 1px;
    align-self: stretch;
    margin: 3px 1px;
    background: var(--border, #e3e6eb);
  }

  .ax-pop {
    position: absolute;
    top: calc(100% + 5px);
    right: 0;
    z-index: 8;
    background: var(--surface, #ffffff);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: var(--radius, 10px);
    box-shadow: 0 8px 28px rgba(16, 24, 40, 0.16);
    padding: 11px 12px;
  }

  /* Transposed limits: x group (min/max stacked) left, y group right. */
  .limits {
    display: flex;
    gap: 10px;
  }
  .axgrp {
    display: flex;
    flex-direction: column;
    gap: 5px;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 8px;
    padding: 7px 8px 8px;
  }
  .axgrp-lab {
    font: 700 11px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--indigo, #4f46e5);
    letter-spacing: 0.04em;
    margin-bottom: 1px;
  }
  .axfield {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .axfield label {
    font: 11px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--muted, #66708a);
    width: 26px;
  }
  .axfield input {
    width: 82px;
    font-family: var(--font-mono, ui-monospace, Menlo, monospace);
    font-size: 12px;
    padding: 3px 5px;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 5px;
  }
  .err {
    font-size: 11px;
    color: #b91c1c;
    margin: 6px 0 0;
    max-width: 210px;
  }
  .sep {
    height: 1px;
    background: var(--border, #e3e6eb);
    margin: 10px 0 8px;
  }
  .legrow {
    display: flex;
    align-items: center;
    margin-bottom: 7px;
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
    cursor: pointer;
  }
  .legend-place {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  /* 2×2 grid of corner buttons, positioned to mirror the plot corners. */
  .corner-grid {
    display: grid;
    grid-template-columns: 40px 40px;
    grid-template-rows: 26px 26px;
    gap: 4px;
  }
  .pbtn {
    border: 1px solid var(--border, #e3e6eb);
    background: #fff;
    border-radius: 6px;
    height: 26px;
    padding: 0 8px;
    font: 600 11px var(--font-body, system-ui, sans-serif);
    color: var(--text, #1b2437);
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .pbtn:hover {
    background: #f2f4f8;
  }
  .pbtn.active {
    background: #eef0ff;
    border-color: #c7d2fe;
    color: var(--indigo, #4f46e5);
  }
  .pbtn.outside {
    white-space: nowrap;
  }
</style>
