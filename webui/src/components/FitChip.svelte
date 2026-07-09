<script lang="ts" module>
  // Round-8 feedback: the chip "gets a bit in the way sometimes". Drag
  // offset + collapsed state live at MODULE scope so they survive the
  // chip's re-mounts (stage switches, Nyquist/default layout swaps) —
  // the panel stays where Tore parked it for the whole session.
  const chipUi = $state({ dx: 0, dy: 0, collapsed: false });
</script>

<script lang="ts">
  /**
   * Floating modal-fit summary chip (design spec §3; mockup
   * dev/mockups/round2-bench.html `#fitChip`, lines 1602-1606). Overlays the
   * TF plot on the Fit stage, listing each fitted mode as
   * `fn = … Hz · ζ = … · Q = …`.
   *
   * Round-4 item 9: each mode row carries a **mute** toggle (keep the mode in
   * the model but drop it from the global reconstruction overlay) and a **×**
   * delete button (consistent with the app's × elsewhere), and an **Undo**
   * affordance appears after a destructive action. Delete / mute / undo route
   * through the STATELESS engine (`actions.calcFit`) + the modal store, which
   * owns the accumulated matrix and the one-level undo slot.
   *
   * Round 8: the chip is draggable (grab the header strip) and minimisable
   * (chevron, MiniMonitor idiom) so it can be parked out of the way of the
   * data. The drag is clamped to the plot area.
   */
  import { PHASE_DEV_WARN_DEG, type ModalStore } from '../lib/stores/modal';
  import type { Actions } from '../lib/analysis/actions';

  let { modal, actions }: { modal: ModalStore; actions: Actions } = $props();
  const modalState = $derived(modal);
  const busy = $derived(actions.busy);

  let chipEl = $state<HTMLDivElement | undefined>();
  let dragging = $state(false);
  let dragStart = { x: 0, y: 0, dx: 0, dy: 0 };

  /** The chip's CSS anchor — keep in lockstep with the .fit-chip rule. */
  const ANCHOR = { left: 64, bottom: 52 };

  /**
   * Clamp the drag offset so the chip stays inside the plot area (its
   * offsetParent). Uses offsetWidth/Height (transform-independent) and the
   * known CSS anchor, so it is exact mid-drag AND after a size change —
   * expanding a chip parked at an edge pulls it back into view instead of
   * clipping its buttons past the plot edge.
   */
  function clampToParent() {
    if (!chipEl) return;
    const parent = chipEl.offsetParent as HTMLElement | null;
    if (!parent) return;
    const pw = parent.clientWidth;
    const ph = parent.clientHeight;
    const cw = chipEl.offsetWidth;
    const ch = chipEl.offsetHeight;
    const minDx = -ANCHOR.left;
    const maxDx = Math.max(minDx, pw - ANCHOR.left - cw);
    const maxDy = ANCHOR.bottom;
    const minDy = Math.min(maxDy, -(ph - ANCHOR.bottom - ch));
    chipUi.dx = Math.min(Math.max(chipUi.dx, minDx), maxDx);
    chipUi.dy = Math.min(Math.max(chipUi.dy, minDy), maxDy);
  }

  // Re-clamp when the chip's size changes: collapse/expand, mode rows coming
  // and going, and on (re)mount (which also catches resizes while unmounted).
  $effect(() => {
    void chipUi.collapsed;
    void $modalState.modes.length;
    void $modalState.undo;
    clampToParent();
  });

  function onDragDown(e: PointerEvent) {
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragging = true;
    dragStart = { x: e.clientX, y: e.clientY, dx: chipUi.dx, dy: chipUi.dy };
  }
  function onDragMove(e: PointerEvent) {
    if (!dragging || !chipEl) return;
    chipUi.dx = dragStart.dx + (e.clientX - dragStart.x);
    chipUi.dy = dragStart.dy + (e.clientY - dragStart.y);
    clampToParent();
  }
  function onDragUp() {
    dragging = false;
  }
  function toggleCollapse() {
    chipUi.collapsed = !chipUi.collapsed;
  }

  /** Q to a compact string (∞ when ζ ≤ 0). */
  function fmtQ(q: number): string {
    if (!Number.isFinite(q)) return '∞';
    return q >= 100 ? q.toFixed(0) : q.toFixed(1);
  }

  /** The set the model targets ('all' as a defensive fallback). */
  const target = $derived($modalState.setId ?? 'all');

  function deleteOne(i: number) {
    actions.calcFit(target, null, $modalState.mt, 'delete_one', 1, i);
  }
  function toggleMute(i: number) {
    modal.toggleMute(i);
    // Recompute the global overlay from the filtered model (no new fit).
    actions.calcFit(target, null, $modalState.mt, 'recon');
  }
  function undo() {
    modal.undo();
  }
</script>

<div
  class="fit-chip mono"
  class:dragging
  role="status"
  aria-label="fitted modes"
  bind:this={chipEl}
  style="transform: translate({chipUi.dx}px, {chipUi.dy}px)"
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="chip-head"
    title="Drag to move · double-click to minimise"
    onpointerdown={onDragDown}
    onpointermove={onDragMove}
    onpointerup={onDragUp}
    onpointercancel={onDragUp}
    ondblclick={toggleCollapse}
  >
    <span class="grip" aria-hidden="true">⠿</span>
    <span class="chip-title">fit{$modalState.modes.length ? ` · ${$modalState.modes.length} mode${$modalState.modes.length === 1 ? '' : 's'}` : ''}</span>
    <button
      class="chip-min"
      onpointerdown={(e) => e.stopPropagation()}
      onclick={toggleCollapse}
      title={chipUi.collapsed ? 'Show the fit summary' : 'Minimise the fit summary'}
      aria-label={chipUi.collapsed ? 'expand fit summary' : 'minimise fit summary'}
    >{chipUi.collapsed ? '▸' : '▾'}</button>
  </div>
  {#if !chipUi.collapsed}
  {#if $modalState.modes.length}
    {#each $modalState.modes as m, i (i)}
      <div class="mode-row" class:muted={$modalState.muted[i]}>
        <span class="mode-txt">
          <b>mode {i + 1}</b>&nbsp;&nbsp;fn = {m.fn.toFixed(1)} Hz · ζ = {m.zn.toFixed(4)} · Q = {fmtQ(m.Q)}
          {#if m.phaseDevDeg > PHASE_DEV_WARN_DEG}
            <!-- JW-logger parity (round-7f): a significantly COMPLEX fitted
                 modal constant usually means the wrong TF type is selected. -->
            <span class="phase-warn" data-testid="mode-phase-warning"
              title="Fitted modal phase is {m.phaseDevDeg.toFixed(0)}° from real (0/180°) — check the TF type (Acceleration / Velocity / Displacement)">⚠</span>
          {/if}
        </span>
        <button
          class="mrow-btn"
          class:on={$modalState.muted[i]}
          disabled={$busy}
          onclick={() => toggleMute(i)}
          title={$modalState.muted[i] ? 'Unmute — include this mode in the reconstruction' : 'Mute — hide this mode from the reconstruction (kept in the model)'}
          aria-label={$modalState.muted[i] ? `unmute mode ${i + 1}` : `mute mode ${i + 1}`}
        >{$modalState.muted[i] ? '🔇' : '🔊'}</button>
        <button
          class="mrow-btn del"
          disabled={$busy}
          onclick={() => deleteOne(i)}
          title="Delete this mode"
          aria-label={`delete mode ${i + 1}`}
        >×</button>
      </div>
    {/each}
    {#if $modalState.undo}
      <div class="chip-foot">
        <button class="undo-btn" disabled={$busy} onclick={undo} title="Undo the last modal change">↶ Undo</button>
      </div>
    {/if}
  {:else}
    <div class="mode-row"><span class="mode-txt">No fit — choose Fit 1 / 2 / 3</span></div>
  {/if}
  {/if}
</div>

<style>
  .fit-chip {
    position: absolute;
    left: 64px;
    bottom: 52px;
    /* Above the legend (z 5): both are draggable, but the chip is the
       smaller one — kept on top it stays visible and grabbable wherever it
       is parked, instead of vanishing (ungrabbably) under the legend. */
    z-index: 6;
    background: var(--overlay-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 11px;
    font-size: 12px;
    line-height: 1.55;
    box-shadow: var(--shadow);
    /* Container ignores pointer events so it never steals plot gestures; the
       interactive buttons (and the drag header) opt back in individually. */
    pointer-events: none;
    max-width: 60%;
  }
  .fit-chip.dragging {
    opacity: 0.92;
  }
  .chip-head {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 5px;
    margin: -3px -6px 2px;
    padding: 1px 6px;
    cursor: grab;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
    color: var(--muted);
    font-size: 10px;
  }
  .fit-chip.dragging .chip-head {
    cursor: grabbing;
  }
  .grip {
    font-size: 9px;
    letter-spacing: 1px;
    opacity: 0.7;
  }
  .chip-title {
    flex: 1;
    white-space: nowrap;
  }
  .chip-min {
    border: none;
    background: none;
    padding: 0 2px;
    font-size: 10px;
    line-height: 1.2;
    cursor: pointer;
    color: var(--muted);
  }
  .chip-min:hover {
    color: var(--text, #222);
  }
  .mode-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .mode-row.muted .mode-txt {
    text-decoration: line-through;
    opacity: 0.55;
  }
  .mode-txt b {
    color: var(--indigo);
  }
  .phase-warn {
    pointer-events: auto; /* hoverable for the explanatory title */
    cursor: help;
    color: var(--danger, #dc2626);
  }
  .mrow-btn {
    pointer-events: auto;
    flex: 0 0 auto;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    border-radius: 5px;
    font-size: 11px;
    line-height: 1;
    padding: 2px 5px;
    cursor: pointer;
    color: var(--text, #222);
  }
  .mrow-btn:hover:not(:disabled) {
    background: var(--hover, #f0f0f4);
  }
  .mrow-btn.on {
    border-color: var(--indigo);
  }
  .mrow-btn.del {
    font-size: 14px;
    color: var(--muted);
  }
  .mrow-btn.del:hover:not(:disabled) {
    color: var(--pink);
    border-color: var(--pink);
  }
  .mrow-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .chip-foot {
    margin-top: 4px;
    display: flex;
    justify-content: flex-end;
  }
  .undo-btn {
    pointer-events: auto;
    border: 1px solid var(--border);
    background: var(--surface, #fff);
    border-radius: 5px;
    font-size: 11px;
    padding: 2px 8px;
    cursor: pointer;
    color: var(--indigo);
  }
  .undo-btn:hover:not(:disabled) {
    background: var(--hover, #f0f0f4);
  }
  .undo-btn:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
