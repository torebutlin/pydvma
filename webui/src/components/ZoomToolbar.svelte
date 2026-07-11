<script lang="ts">
  /**
   * Plot-navigation toolbar (design spec §6; round-4 redesign). Visuals
   * descend from the `.zoom-bar` / `.zbtn` / `#axPop` styles in
   * `dev/mockups/round2-bench.html`. Docked in the plot host's `.plot-nav`
   * header strip ABOVE the plot area (round-7 item 1 — it used to float over
   * the top-right of the data area, permanently covering it); only the
   * expander popover still drops over the plot corner, transiently.
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
   * ── round-5 special TF contexts (items 4-6) ──
   * Three optional modes adapt the toolbar for the TF plot family without
   * changing its round-4 shape:
   * - `nyquist`: the x/y limit groups + Auto buttons mean REAL/IMAG and drive
   *   `nyquistRange`; a third bordered `freq` group binds the committed
   *   frequency window (`range.x`) that the brush/Calc/Fit share.
   * - `phaseControl` (Bode): a `phase y` segmented control (±180° | auto) in the
   *   expanded panel drives the phase pane's own `phaseRange`.
   * - `coherenceControl`: a `coherence` segmented control (0–1 | auto) drives the
   *   overlay's right axis via `coherenceAuto`.
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
    nyquist = false,
    phaseControl = false,
    coherenceControl = false,
    sono = false,
    freqExtent = undefined,
    navControl = false,
    navOpen = false,
    onnavtoggle = undefined,
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
    /**
     * Nyquist mode (round-5 item 4): the x/y controls mean REAL/IMAG and act on
     * the tf view's `nyquistRange` (NOT `range`, whose `.x` stays the frequency
     * window). The x/y limit groups relabel real/imag, Auto X/Y auto-fit those
     * axes, and a third bordered `freq` group appears bound to the committed
     * frequency range. App passes this only for the tf Nyquist plotType.
     */
    nyquist?: boolean;
    /**
     * Bode mode (round-5 item 5): show a compact `phase y` control (auto | ±180°
     * lock) in the expanded panel that drives the phase pane's own y-axis
     * (`phaseRange`). The toolbar itself lives in the magnitude pane, so its
     * x/y controls stay the shared frequency + magnitude y.
     */
    phaseControl?: boolean;
    /**
     * Coherence overlay present (round-5 item 6): show a minimal `coherence`
     * control (auto | 0–1) in the expanded panel that drives the right axis via
     * `coherenceAuto`. App passes `!!model.y2Range`.
     */
    coherenceControl?: boolean;
    /**
     * Sonogram view: surface TWO segmented controls in the toolbar bar — a
     * frequency y-axis `lin | log` (drives `sonoFreqScale`) and a heat colour
     * `dB | lin` (drives `sonoColour`). App passes this only on the sono view.
     * There is deliberately NO x-scale control on sono: x is TIME, and a log
     * time axis is nonsensical (mirrors why `showXScale` excludes time/sono).
     * The colour control is tagged `colour` — NOT `y` — because on sono the
     * dB-ness is the heat COLOUR, not the frequency y-axis, so it must never be
     * confused with the `y` lin|log axis control beside it.
     */
    sono?: boolean;
    /**
     * Full frequency extent `[fmin, fmax]` — the fallback shown in the Nyquist
     * `freq` group when the committed frequency window is auto (null). Ignored
     * outside Nyquist mode.
     */
    freqExtent?: [number, number];
    /**
     * Show the frequency-navigator toggle (freq-navigator design 2026-07-11).
     * App passes true on the frequency/tf views; the button reports state via
     * `navOpen` and flips it through `onnavtoggle` (the state itself lives in
     * the view slice's `navigator` override — resolved in App).
     */
    navControl?: boolean;
    /** Current navigator visibility (drives aria-pressed / the active style). */
    navOpen?: boolean;
    /** Toggle callback — App writes `viewState.setNavigator(view, !navOpen)`. */
    onnavtoggle?: () => void;
  } = $props();

  // Derived (not destructured) so the toolbar tracks a reassigned viewState prop.
  const current = $derived(viewState.current);
  const active = $derived(viewState.active);
  const uid = $props.id();

  // Live axis-scale state for the segmented controls (R3).
  const xScale = $derived($current.xScale);
  const yScale = $derived($current.yScale);
  // Sono-only display scales: frequency y-axis lin↔log, heat colour dB↔lin.
  const sonoFreqScale = $derived($current.sonoFreqScale);
  const sonoColour = $derived($current.sonoColour);

  // On Nyquist the primary axes are the Real/Imag `nyquistRange`; everywhere
  // else the toolbar's x/y drive the primary `range`. `targetRange` is the one
  // the limit fields + Auto buttons read/write.
  const targetRange = $derived(nyquist ? $current.nyquistRange : $current.range);

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

  // ---- Nyquist frequency-window group (live, debounced; nyquist only) ----
  let fminS = $state(''), fmaxS = $state('');
  let freqError = $state('');
  let freqDirty = $state(false);
  let freqTimer: ReturnType<typeof setTimeout> | undefined;

  /**
   * What the primary (x/y) fields show: the explicit target range (Real/Imag on
   * Nyquist, else the primary range) or the auto-fit data extent per axis.
   */
  const shown = $derived({
    x: targetRange.x ?? dataExtent.x,
    y: targetRange.y ?? dataExtent.y,
  });

  /** The committed frequency window shown in the Nyquist `freq` group. */
  const freqShown = $derived<[number, number]>($current.range.x ?? freqExtent ?? [0, 0]);

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

  // Store → freq fields sync (Nyquist), gated by its own dirty flag.
  $effect(() => {
    if (!nyquist || freqDirty) return;
    const [lo, hi] = freqShown;
    fminS = fmtTick(lo, hi - lo);
    fmaxS = fmtTick(hi, hi - lo);
    freqError = '';
  });

  // Closing the panel abandons any half-typed / pending edit so the next open
  // re-seeds cleanly from the store.
  $effect(() => {
    if (!open) {
      if (commitTimer) { clearTimeout(commitTimer); commitTimer = undefined; }
      if (freqTimer) { clearTimeout(freqTimer); freqTimer = undefined; }
      dirty = false; freqDirty = false;
      limitsError = ''; freqError = '';
    }
  });

  /**
   * Validate the four x/y fields and commit ONE range change; invalid → show
   * error, no write. On Nyquist the write targets `nyquistRange` (Real/Imag);
   * elsewhere the primary `range`.
   */
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
    if (nyquist) viewState.setNyquistRange({ x: [x0, x1], y: [y0, y1] });
    else viewState.setRange($active, { x: [x0, x1], y: [y0, y1] });
  }

  /** A field changed: mark dirty and debounce a live commit (~300 ms). */
  function onLimitInput() {
    dirty = true;
    limitsError = '';
    if (commitTimer) clearTimeout(commitTimer);
    commitTimer = setTimeout(commitLimits, 300);
  }

  /** Commit the Nyquist frequency window (`range.x`), keeping the magnitude y. */
  function commitFreq() {
    freqTimer = undefined;
    const lo = parseFloat(fminS), hi = parseFloat(fmaxS);
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) {
      freqError = 'Frequency limits must be numeric with max > min.';
      return;
    }
    freqError = '';
    freqDirty = false;
    viewState.setRange('tf', { x: [lo, hi], y: $current.range.y });
  }

  function onFreqInput() {
    freqDirty = true;
    freqError = '';
    if (freqTimer) clearTimeout(freqTimer);
    freqTimer = setTimeout(commitFreq, 300);
  }

  // Auto X / Auto Y. On Nyquist these auto-fit the Real/Imag axes by resetting
  // the corresponding `nyquistRange` axis to null (the model then fits the
  // windowed locus, padded); elsewhere they set the explicit data extent.
  function autoX() {
    if (nyquist) viewState.setNyquistRange({ x: null, y: $current.nyquistRange.y });
    else viewState.setRange($active, { x: [dataExtent.x[0], dataExtent.x[1]], y: $current.range.y });
  }
  function autoY() {
    if (nyquist) viewState.setNyquistRange({ x: $current.nyquistRange.x, y: null });
    else viewState.setRange($active, { x: $current.range.x, y: [dataExtent.y[0], dataExtent.y[1]] });
  }

  // ---- Bode phase-pane y control + coherence right-axis control ----
  const phaseMode = $derived<'auto' | 'lock'>($current.phaseRange.y === null ? 'auto' : 'lock');
  function setPhaseMode(m: 'auto' | 'lock') {
    viewState.setPhaseRange(m === 'auto' ? { x: null, y: null } : { x: null, y: [-180, 180] });
  }
  const cohMode = $derived<'fixed' | 'auto'>($current.coherenceAuto ? 'auto' : 'fixed');

  $effect(() => () => {
    if (leaveTimer) clearTimeout(leaveTimer);
    if (commitTimer) clearTimeout(commitTimer);
    if (freqTimer) clearTimeout(freqTimer);
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
    {#if navControl}
      <button
        class="zbtn"
        class:active={navOpen}
        type="button"
        data-testid="freq-nav-toggle"
        title={navOpen ? 'Hide frequency navigator' : 'Show frequency navigator'}
        aria-label={navOpen ? 'Hide frequency navigator' : 'Show frequency navigator'}
        aria-pressed={navOpen}
        onclick={() => onnavtoggle?.()}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <rect x="1.5" y="5" width="13" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.4" />
          <rect x="6" y="5" width="4" height="6" fill="currentColor" opacity="0.6" />
        </svg>
      </button>
    {/if}
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

    <button class="zbtn" title={nyquist ? 'Auto-fit the Real axis to the windowed locus' : 'Autoscale X to the full data extent'}
      onclick={autoX}>{nyquist ? 'Auto Re' : 'Auto X'}</button>
    <button class="zbtn" title={nyquist ? 'Auto-fit the Imag axis to the windowed locus' : 'Autoscale Y (fits selected lines only)'}
      onclick={autoY}>{nyquist ? 'Auto Im' : 'Auto Y'}</button>

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
            { value: 'lin' as const, label: 'lin', title: 'Linear frequency axis' },
            { value: 'log' as const, label: 'log', title: 'Log10 frequency axis (decades)' },
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
            { value: 'log' as const, label: 'dB', title: 'Magnitude in dB (log)' },
            { value: 'lin' as const, label: 'lin', title: 'Linear magnitude' },
          ]}
        />
      {/if}
    {/if}

    {#if sono}
      <!-- Sono: frequency y-axis lin|log + heat colour dB|lin. x stays TIME
           (no x control — log time is nonsensical). The colour tag reads
           `colour` so it is never mistaken for the `y` frequency-axis control. -->
      <span class="zdiv" aria-hidden="true"></span>
      <Segmented
        testid="sono-yscale-toggle"
        ariaLabel="Frequency axis scale"
        label="y"
        value={sonoFreqScale}
        onchange={(s) => viewState.setSonoFreqScale(s)}
        options={[
          { value: 'lin' as const, label: 'lin', title: 'Linear frequency axis' },
          { value: 'log' as const, label: 'log', title: 'Log10 frequency axis (decades)' },
        ]}
      />
      <Segmented
        testid="sono-colour-toggle"
        ariaLabel="Heat colour mapping"
        label="colour"
        value={sonoColour}
        onchange={(c) => viewState.setSonoColour(c)}
        options={[
          { value: 'db' as const, label: 'dB', title: 'Colour by magnitude in dB (over the dynamic-range span)' },
          { value: 'lin' as const, label: 'lin', title: 'Colour by linear magnitude (0 → peak)' },
        ]}
      />
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
          <span class="axgrp-lab">{nyquist ? 'real' : 'x'}</span>
          <div class="axfield">
            <label for="{uid}-xmin">min</label>
            <input id="{uid}-xmin" bind:value={xminS} oninput={onLimitInput} inputmode="decimal"
              aria-label={nyquist ? 'Real min' : 'x min'} />
          </div>
          <div class="axfield">
            <label for="{uid}-xmax">max</label>
            <input id="{uid}-xmax" bind:value={xmaxS} oninput={onLimitInput} inputmode="decimal"
              aria-label={nyquist ? 'Real max' : 'x max'} />
          </div>
        </div>
        <div class="axgrp">
          <span class="axgrp-lab">{nyquist ? 'imag' : 'y'}</span>
          <div class="axfield">
            <label for="{uid}-ymin">min</label>
            <input id="{uid}-ymin" bind:value={yminS} oninput={onLimitInput} inputmode="decimal"
              aria-label={nyquist ? 'Imag min' : 'y min'} />
          </div>
          <div class="axfield">
            <label for="{uid}-ymax">max</label>
            <input id="{uid}-ymax" bind:value={ymaxS} oninput={onLimitInput} inputmode="decimal"
              aria-label={nyquist ? 'Imag max' : 'y max'} />
          </div>
        </div>
        {#if nyquist}
          <!-- The frequency window (round-5 item 4): the SAME committed range
               the brush, Calc and Fit read. Bound to `range.x`, kept apart
               from the Real/Imag axes above. -->
          <div class="axgrp freq" data-testid="nyquist-freq-group">
            <span class="axgrp-lab">freq</span>
            <div class="axfield">
              <label for="{uid}-fmin">min</label>
              <input id="{uid}-fmin" bind:value={fminS} oninput={onFreqInput} inputmode="decimal" aria-label="Frequency min" />
            </div>
            <div class="axfield">
              <label for="{uid}-fmax">max</label>
              <input id="{uid}-fmax" bind:value={fmaxS} oninput={onFreqInput} inputmode="decimal" aria-label="Frequency max" />
            </div>
          </div>
        {/if}
      </div>
      {#if limitsError}<div class="err" role="alert">{limitsError}</div>{/if}
      {#if nyquist && freqError}<div class="err" role="alert">{freqError}</div>{/if}

      {#if phaseControl || coherenceControl}
        <div class="sep"></div>
        <div class="pane-ctls">
          {#if phaseControl}
            <div class="pane-grp" data-testid="phase-y-control">
              <span class="grp">phase y</span>
              <Segmented
                testid="phase-y-toggle"
                ariaLabel="Phase pane y-axis"
                value={phaseMode}
                onchange={(m) => setPhaseMode(m)}
                options={[
                  { value: 'lock' as const, label: '±180°', title: 'Lock the phase axis to ±180°' },
                  { value: 'auto' as const, label: 'auto', title: 'Auto-fit the phase axis to the data' },
                ]}
              />
            </div>
          {/if}
          {#if coherenceControl}
            <div class="pane-grp" data-testid="coherence-control">
              <span class="grp">coherence</span>
              <Segmented
                testid="coherence-toggle"
                ariaLabel="Coherence right axis"
                value={cohMode}
                onchange={(m) => viewState.setCoherenceAuto(m === 'auto')}
                options={[
                  { value: 'fixed' as const, label: '0–1', title: 'Fixed coherence axis 0 to 1' },
                  { value: 'auto' as const, label: 'auto', title: 'Auto-fit the coherence axis to the data' },
                ]}
              />
            </div>
          {/if}
        </div>
      {/if}

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
    /* Docked in the parent's `.plot-nav` strip (round-7 item 1) — no longer
       absolutely positioned over the data area. Stays `relative` as the
       anchor for the `.ax-pop` popover, which still drops over the plot's
       top-right corner while open. */
    position: relative;
  }
  .zoom-bar {
    display: flex;
    align-items: center;
    gap: 3px;
    background: var(--overlay-bg);
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
    background: var(--hover-bg);
    color: var(--text, #1b2437);
  }
  .zbtn.active {
    background: var(--accent-soft);
    border-color: var(--accent-soft-border);
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
    box-shadow: var(--shadow-lg, 0 8px 28px rgba(16, 24, 40, 0.16));
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
  /* The Nyquist frequency group reads as the "shared window", tinted apart
     from the Real/Imag axis groups it sits beside. */
  .axgrp.freq {
    background: var(--surface-2);
  }
  .axgrp.freq .axgrp-lab {
    color: var(--muted, #66708a);
  }
  .pane-ctls {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .pane-grp {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
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
    background: var(--control-bg);
    color: var(--text);
  }
  .err {
    font-size: 11px;
    color: var(--danger);
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
    background: var(--control-bg);
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
    background: var(--hover-bg);
  }
  .pbtn.active {
    background: var(--accent-soft);
    border-color: var(--accent-soft-border);
    color: var(--indigo, #4f46e5);
  }
  .pbtn.outside {
    white-space: nowrap;
  }
</style>
