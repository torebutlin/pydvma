<script lang="ts">
  /**
   * The draggable free-decay START-TIME line on the sonogram (round-7 item
   * 3): a vertical marker over the heat map at the damping fit's start
   * time. Dragging it live-updates the damping store's `startTime` and
   * commits a refit on release — "the line for choosing where (in time) to
   * find those peaks".
   *
   * Mounted inside the sono `.plot-area`; the wrapper pins itself to the
   * SAME inner data rect as `.sono-heat` (margins L58/T16/R18/B42 — the
   * PlotSurface constants), so a time value maps to a plain fraction of the
   * wrapper's width. The wrapper is pointer-transparent; only the line's
   * fat hit strip takes events, so plot gestures (box-zoom/pan) under it
   * keep working.
   */
  let {
    window: win,
    value,
    busy = false,
    onlive,
    oncommit,
  }: {
    /** The displayed sono window (App's `sonoWindow`) — the x mapping. */
    window: { x: [number, number] };
    /** Current start time (s). */
    value: number;
    busy?: boolean;
    /** Live drag updates (store only — no fit). */
    onlive: (t: number) => void;
    /** Pointer released: run the fit at the final position. */
    oncommit: () => void;
  } = $props();

  let wrap = $state<HTMLDivElement | undefined>();
  let dragging = $state(false);

  const frac = $derived(
    Math.min(1, Math.max(0, (value - win.x[0]) / (win.x[1] - win.x[0] || 1))),
  );

  function timeFromEvent(e: PointerEvent): number {
    const r = wrap!.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / (r.width || 1)));
    return win.x[0] + f * (win.x[1] - win.x[0]);
  }
  function onDown(e: PointerEvent) {
    if (busy) return;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragging = true;
    onlive(timeFromEvent(e));
  }
  function onMove(e: PointerEvent) {
    if (!dragging) return;
    onlive(timeFromEvent(e));
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    oncommit();
  }
</script>

<div class="stl-wrap" bind:this={wrap} aria-hidden="false">
  <div class="stl-line" class:dragging data-testid="damping-start-line" style="left: {frac * 100}%">
    <span class="stl-tag">start</span>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="stl-hit" style="cursor: ew-resize"
      onpointerdown={onDown} onpointermove={onMove}
      onpointerup={onUp} onpointercancel={() => (dragging = false)}></div>
  </div>
</div>

<style>
  .stl-wrap {
    position: absolute;
    /* the PlotSurface inner data rect — keep in lockstep with .sono-heat */
    left: 58px;
    top: 16px;
    right: 18px;
    bottom: 42px;
    pointer-events: none;
    z-index: 5;
  }
  .stl-line {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 0;
    border-left: 2px dashed var(--danger, #dc2626);
    opacity: 0.9;
  }
  .stl-line.dragging {
    border-left-style: solid;
  }
  .stl-tag {
    position: absolute;
    top: 2px;
    left: 4px;
    font: 600 9.5px var(--font-mono, ui-monospace, monospace);
    color: var(--danger, #dc2626);
    background: var(--overlay-bg);
    border-radius: 3px;
    padding: 0 3px;
    white-space: nowrap;
  }
  .stl-hit {
    position: absolute;
    top: 0;
    bottom: 0;
    left: -7px;
    width: 14px;
    pointer-events: auto;
  }
</style>
