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
   */
  import type { ModalStore } from '../lib/stores/modal';
  import type { Actions } from '../lib/analysis/actions';

  let { modal, actions }: { modal: ModalStore; actions: Actions } = $props();
  const modalState = $derived(modal);
  const busy = $derived(actions.busy);

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

<div class="fit-chip mono" role="status" aria-label="fitted modes">
  {#if $modalState.modes.length}
    {#each $modalState.modes as m, i (i)}
      <div class="mode-row" class:muted={$modalState.muted[i]}>
        <span class="mode-txt">
          <b>mode {i + 1}</b>&nbsp;&nbsp;fn = {m.fn.toFixed(1)} Hz · ζ = {m.zn.toFixed(4)} · Q = {fmtQ(m.Q)}
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
</div>

<style>
  .fit-chip {
    position: absolute;
    left: 64px;
    bottom: 52px;
    z-index: 4;
    background: rgba(255, 255, 255, 0.92);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 7px 11px;
    font-size: 12px;
    line-height: 1.55;
    box-shadow: var(--shadow);
    /* Container ignores pointer events so it never steals plot gestures; the
       interactive buttons opt back in individually. */
    pointer-events: none;
    max-width: 60%;
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
    color: #be185d;
    border-color: #be185d;
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
