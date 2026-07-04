<script lang="ts">
  /**
   * Draggable plot legend (design spec §6). An absolutely-positioned
   * card floating over the plot, mounted inside the plot host next to
   * `PlotSurface` / `ZoomToolbar`.
   *
   * Wiring contract (documented design choice): like `ZoomToolbar`,
   * this takes the WHOLE `selection` and `viewState` store objects
   * rather than narrow callbacks. It reads `selection.legendEntries`
   * (a derived store that already omits off lines and fully-off sets),
   * mirrors the data-tray's tri-state by calling `selection.cycleLine`,
   * and persists placement via `viewState.setLegend(active, …)` while
   * reading the current legend slice from `viewState.current`.
   * Callbacks would just re-implement this surface, and the stores'
   * identities are stable for the component's lifetime (created once
   * at app startup).
   *
   * Placement is FRACTIONAL (`legend.x` / `legend.y` in `[0, 1]`, spec
   * convention, see `lib/plot/legendPos`). The card anchors to the
   * right edge when `x > 0.5` and to the bottom when `y > 0.5` so a
   * corner preset pins the nearest corner of the card to that corner
   * of the plot (matplotlib feel). The whole card is hidden when
   * `legend.visible === false`.
   *
   * Rows mirror the tray: a colour swatch + label per entry; a `fade`
   * entry renders the whole row at 40% opacity. Clicking a row cycles
   * that line (on → fade → off → on); the store update flows back
   * through `legendEntries` and re-renders (off lines then drop out).
   *
   * Free drag: pointer-drag the card → `clampLegend(newFractionalPos)`
   * → `setLegend(active, { …legend, x, y, preset: null })`. Dragging
   * ALWAYS clears the preset and NEVER snaps (spec §6). Moves update
   * live (legend position is not history-tracked) but are rAF-coalesced
   * for smoothness; the final position also commits on pointerup.
   */
  import type { Selection } from '../lib/stores/selection';
  import type { ViewState } from '../lib/stores/viewstate';
  import { clampLegend } from '../lib/plot/legendPos';
  import { get } from 'svelte/store';

  let {
    selection,
    viewState,
  }: {
    selection: Selection;
    viewState: ViewState;
  } = $props();

  // Derived (not destructured) so the component tracks reassigned props.
  const entries = $derived(selection.legendEntries);
  const current = $derived(viewState.current);

  const legend = $derived($current.legend);

  // The card's own measured box, so anchoring pins the correct edge.
  let card: HTMLDivElement | undefined = $state();

  /**
   * CSS placement for the card. Fractional x/y position the anchor
   * point inside the host; when x>0.5 we anchor the card's RIGHT edge
   * (so it grows leftward and its right corner tracks the point), and
   * when y>0.5 we anchor its BOTTOM edge. This keeps corner presets
   * flush to the matching plot corner rather than overflowing it.
   */
  const placement = $derived.by(() => {
    const anchorRight = legend.x > 0.5;
    const anchorBottom = legend.y > 0.5;
    const xPct = `${legend.x * 100}%`;
    const yPct = `${legend.y * 100}%`;
    return {
      left: anchorRight ? 'auto' : xPct,
      right: anchorRight ? `${(1 - legend.x) * 100}%` : 'auto',
      top: anchorBottom ? 'auto' : yPct,
      bottom: anchorBottom ? `${(1 - legend.y) * 100}%` : 'auto',
    };
  });

  // ---- Free drag (pointer capture + rAF coalescing) ----
  //
  // A pointerdown only ARMS a potential drag; we defer pointer capture
  // (and the `dragging` state) until the pointer actually moves past a
  // few pixels. That keeps a plain tap/click on a row from being
  // captured by the card — capture would retarget the pointer sequence
  // and swallow the button's native `click`, breaking the tri-state
  // cycle. So: small movement = click the row; real movement = drag.

  /** Pixels of pointer travel before an armed press becomes a drag. */
  const DRAG_THRESHOLD_PX = 3;

  let armed = false;                 // pointerdown seen, not yet a drag
  let dragging = $state(false);      // a real drag is in progress
  let activePointer = 0;
  let downClientX = 0, downClientY = 0;  // pointerdown origin (client px)
  // Pointer→fraction needs the host rect; capture it at pointerdown.
  let hostRect: DOMRect | null = null;
  // Offset from the pointer to the card's top-left, in host fractions,
  // so the card doesn't jump under the cursor when the drag begins.
  let grabFx = 0, grabFy = 0;
  let rafId = 0;
  let pendingPos: { x: number; y: number } | null = null;

  /** Host element = the card's positioned ancestor (the plot host). */
  function hostOf(): HTMLElement | null {
    return card?.offsetParent as HTMLElement | null;
  }

  /** Commit a fractional position, clamped, clearing any preset. */
  function commit(pos: { x: number; y: number }) {
    const c = clampLegend(pos);
    viewState.setLegend(get(viewState.active), { ...legend, x: c.x, y: c.y, preset: null });
  }

  function onPointerDown(e: PointerEvent) {
    if (e.button !== 0 || !card) return;
    const host = hostOf();
    if (!host) return;
    hostRect = host.getBoundingClientRect();
    if (hostRect.width === 0 || hostRect.height === 0) return;
    // ARM only — no capture yet, so a plain click still reaches the row.
    armed = true;
    activePointer = e.pointerId;
    downClientX = e.clientX; downClientY = e.clientY;
    // Fraction of the pointer within the host, and the card's current
    // top-left as a fraction, so we can keep the grab offset constant.
    const cardRect = card.getBoundingClientRect();
    const px = (e.clientX - hostRect.left) / hostRect.width;
    const py = (e.clientY - hostRect.top) / hostRect.height;
    grabFx = px - (cardRect.left - hostRect.left) / hostRect.width;
    grabFy = py - (cardRect.top - hostRect.top) / hostRect.height;
  }

  function onPointerMove(e: PointerEvent) {
    if ((!armed && !dragging) || e.pointerId !== activePointer || !hostRect) return;
    // Promote an armed press to a drag once it travels past the threshold.
    if (!dragging) {
      const moved = Math.hypot(e.clientX - downClientX, e.clientY - downClientY);
      if (moved < DRAG_THRESHOLD_PX) return;
      dragging = true;
      card?.setPointerCapture(e.pointerId);
    }
    const px = (e.clientX - hostRect.left) / hostRect.width;
    const py = (e.clientY - hostRect.top) / hostRect.height;
    // Position is the card's top-left; subtract the grab offset.
    pendingPos = { x: px - grabFx, y: py - grabFy };
    if (!rafId) {
      rafId = requestAnimationFrame(() => {
        rafId = 0;
        if (pendingPos) commit(pendingPos);
      });
    }
  }

  function onPointerUp(e: PointerEvent) {
    if (e.pointerId !== activePointer) return;
    // A press that never crossed the threshold was a click: let the
    // row button's own onclick fire; we do nothing but disarm.
    if (dragging) {
      try { card?.releasePointerCapture(e.pointerId); } catch { /* already released */ }
      if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
      if (pendingPos) commit(pendingPos);
    }
    armed = false;
    dragging = false;
    pendingPos = null;
    hostRect = null;
  }

  // Cancel any pending rAF if the component unmounts mid-drag.
  $effect(() => () => { if (rafId) cancelAnimationFrame(rafId); });
</script>

{#if legend.visible}
  <div
    bind:this={card}
    class="legend"
    class:dragging
    data-testid="legend"
    style:left={placement.left}
    style:right={placement.right}
    style:top={placement.top}
    style:bottom={placement.bottom}
    role="group"
    aria-label="Plot legend — drag to reposition"
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
  >
    {#each $entries as e (`${e.setId}:${e.ch}`)}
      <button
        type="button"
        class="row"
        class:fade={e.state === 'fade'}
        data-testid="legend-entry"
        title="Click to cycle: on → fade → off"
        onclick={() => selection.cycleLine(e.setId, e.ch)}
      >
        <span class="swatch" style:background={e.color}></span>
        <span class="label">{e.label}</span>
      </button>
    {/each}
  </div>
{/if}

<style>
  .legend {
    position: absolute;
    z-index: 5;
    max-width: 46%;
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 6px 8px;
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 8px;
    box-shadow: var(--shadow, 0 1px 3px rgba(16, 24, 40, 0.12));
    cursor: grab;
    touch-action: none;
    user-select: none;
  }
  .legend.dragging {
    cursor: grabbing;
    box-shadow: 0 6px 20px rgba(16, 24, 40, 0.22);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 7px;
    border: none;
    background: transparent;
    border-radius: 4px;
    padding: 2px 4px;
    cursor: pointer;
    text-align: left;
    color: var(--text, #1b2437);
    font: 500 11.5px var(--font-body, system-ui, sans-serif);
  }
  .row:hover {
    background: #f2f4f8;
  }
  .row.fade {
    opacity: 0.4;
  }
  .swatch {
    flex: 0 0 auto;
    width: 14px;
    height: 3px;
    border-radius: 2px;
  }
  .label {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
