<script lang="ts">
  /**
   * Narrow-mode data rail (design spec §5; visuals ported from
   * dev/mockups/round2-bench.html `#rail`). A ~72px vertical rail shown
   * only in narrow layout, tagged `data-testid="narrow-rail"`.
   *
   * It iterates `selection.setsView` (may be empty — a hint is shown
   * when there are no sets); clicking a set chip calls
   * `selection.cycleSet(setId)`. The `⋯` control
   * (`data-testid="rail-more"`) opens the full data tray as a flyover
   * drawer over a scrim; Escape (or a scrim click) closes it.
   *
   * The real Tray is Task 10 — the flyover here contains only a
   * placeholder region tagged `data-testid="tray"` for Task 10 to fill.
   * The flyover starts CLOSED, so that placeholder is hidden until the
   * user opens it.
   */
  import type { Selection } from '../lib/stores/selection';

  let { selection }: { selection: Selection } = $props();

  const setsView = $derived(selection.setsView);
  let open = $state(false);

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') open = false;
  }
</script>

<svelte:window on:keydown={onKeydown} />

<aside class="rail" data-testid="narrow-rail" aria-label="data rail">
  <div class="rail-sets">
    {#if $setsView.length === 0}
      <span class="rail-hint">No data</span>
    {:else}
      {#each $setsView as set (set.id)}
        <button
          class="rail-set"
          class:off={set.allOff}
          title={set.name}
          onclick={() => selection.cycleSet(set.id)}
        >
          <span class="rs-swatches">
            {#each set.colors as c}<i style="background:{c}"></i>{/each}
          </span>
          <span class="rs-idx">{set.index + 1}</span>
        </button>
      {/each}
    {/if}
  </div>
  <button
    class="rail-more"
    data-testid="rail-more"
    title="Open the full data tray"
    onclick={() => (open = true)}
  >⋯</button>
</aside>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={() => (open = false)}></div>
  <div class="flyover" role="dialog" aria-label="data tray">
    <!-- Task 10 fills this region with the real tray. -->
    <div class="tray-placeholder" data-testid="tray">
      <span class="ph-note">Data tray arrives in Task 10</span>
    </div>
  </div>
{/if}

<style>
  .rail {
    flex: 0 0 72px;
    width: 72px;
    display: flex;
    flex-direction: column;
    align-items: center;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 8px 4px 0;
    gap: 8px;
    min-height: 0;
  }
  .rail-sets {
    display: flex;
    flex-direction: column;
    gap: 7px;
    align-items: center;
    overflow-y: auto;
    flex: 0 1 auto;
    min-height: 0;
    width: 100%;
  }
  .rail-hint {
    font-size: 10.5px;
    color: var(--muted);
    text-align: center;
    padding: 6px 0;
  }
  .rail-set {
    width: 60px;
    border: 2px solid var(--border);
    border-radius: 10px;
    background: #fff;
    padding: 6px 4px 4px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    flex: 0 0 auto;
  }
  .rail-set.off {
    opacity: 0.72;
  }
  .rs-swatches {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    justify-content: center;
    max-width: 44px;
  }
  .rs-swatches i {
    width: 8px;
    height: 8px;
    border-radius: 2px;
  }
  .rs-idx {
    font: 600 10px var(--font-mono);
    color: var(--muted);
  }
  .rail-more {
    border: 1px dashed #c6cbd6;
    background: #fff;
    border-radius: 8px;
    width: 60px;
    height: 24px;
    cursor: pointer;
    color: var(--muted);
    font-size: 13px;
    flex: 0 0 auto;
  }
  .rail-more:hover {
    color: var(--text);
    border-color: #98a1b5;
  }

  .scrim {
    position: fixed;
    inset: 0;
    z-index: 60;
    background: rgba(23, 32, 58, 0.35);
  }
  .flyover {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 302px;
    z-index: 80;
    background: var(--surface);
    border-right: 1px solid var(--border);
    box-shadow: var(--shadow);
    display: flex;
    flex-direction: column;
  }
  .tray-placeholder {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .ph-note {
    font-size: 12px;
    color: var(--muted);
    font-style: italic;
  }
</style>
