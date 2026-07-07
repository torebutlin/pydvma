<script lang="ts">
  /**
   * Floating modal-fit summary chip (design spec §3; mockup
   * dev/mockups/round2-bench.html `#fitChip`, lines 1602-1606). Overlays the
   * TF plot on the Fit stage, listing each fitted mode as
   * `fn = … Hz · ζ = … · Q = …`. Purely presentational — reads the modal
   * store; positioned bottom-left over the plot like the mockup.
   */
  import type { ModalStore } from '../lib/stores/modal';

  let { modal }: { modal: ModalStore } = $props();
  const modalState = $derived(modal);

  /** Q to a compact string (∞ when ζ ≤ 0). */
  function fmtQ(q: number): string {
    if (!Number.isFinite(q)) return '∞';
    return q >= 100 ? q.toFixed(0) : q.toFixed(1);
  }
</script>

<div class="fit-chip mono" role="status" aria-label="fitted modes">
  {#if $modalState.modes.length}
    {#each $modalState.modes as m, i (i)}
      <div>
        <b>mode {i + 1}</b>&nbsp;&nbsp;fn = {m.fn.toFixed(1)} Hz · ζ = {m.zn.toFixed(4)} · Q = {fmtQ(m.Q)}
      </div>
    {/each}
  {:else}
    <div>No fit — choose Fit 1 / 2 / 3</div>
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
    pointer-events: none;
    max-width: 60%;
  }
  .fit-chip b {
    color: var(--indigo);
  }
</style>
