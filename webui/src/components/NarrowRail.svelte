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
   * The flyover drawer is the codebase's first modal dialog and sets the
   * a11y precedent: on open, focus moves into the drawer (which is
   * `tabindex=-1`); Tab / Shift+Tab are trapped so focus cycles within
   * the drawer; `aria-modal="true"` marks it; the Escape handler is
   * scoped to `open`; and on close, focus is restored to the trigger.
   * It hosts the real `Tray` (Task 10) and starts CLOSED, so the tray
   * region (`data-testid="tray"`) is hidden until opened.
   */
  import type { Selection } from '../lib/stores/selection';
  import Tray from './Tray.svelte';

  let {
    selection,
    /** Forwarded to the hosted Tray so narrow-mode sparklines draw real data. */
    channelSeries,
    /** Forwarded to the hosted Tray for the modal-fit card (round-5 item 13). */
    modal,
    onDeleteFit,
  }: {
    selection: Selection;
    channelSeries?: (setId: number, ch: number) => Float64Array | undefined;
    modal?: import('../lib/stores/modal').ModalStore;
    onDeleteFit?: () => void;
  } = $props();

  const setsView = $derived(selection.setsView);
  let open = $state(false);

  // References for focus management: the drawer to focus on open, and the
  // trigger to restore focus to on close.
  let drawerEl: HTMLDivElement | undefined = $state();
  let moreBtn: HTMLButtonElement | undefined = $state();

  // Move focus into the drawer when it opens; restore it to the trigger
  // only on a genuine open->close transition. The initial mount runs with
  // `open === false`, so restoring on every falsey pass would steal focus
  // to the ⋯ button on page load — hence the `prevOpen` guard.
  let prevOpen = false;
  $effect(() => {
    if (open) drawerEl?.focus();
    else if (prevOpen) moreBtn?.focus();
    prevOpen = open;
  });

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && open) open = false;
  }

  /**
   * Focus trap: keep Tab / Shift+Tab cycling within the drawer while it
   * is open. Wraps from the last focusable element back to the first
   * (and vice versa).
   */
  function onDrawerKeydown(e: KeyboardEvent) {
    if (e.key !== 'Tab' || !drawerEl) return;
    const focusable = drawerEl.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length === 0) {
      e.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && (active === first || active === drawerEl)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
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
    bind:this={moreBtn}
    class="rail-more"
    data-testid="rail-more"
    title="Open the full data tray"
    aria-haspopup="dialog"
    aria-expanded={open}
    onclick={() => (open = true)}
  >⋯</button>
</aside>

{#if open}
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="scrim" onclick={() => (open = false)}></div>
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div
    bind:this={drawerEl}
    class="flyover"
    role="dialog"
    aria-modal="true"
    aria-label="data tray"
    tabindex="-1"
    data-testid="tray"
    onkeydown={onDrawerKeydown}
  >
    <Tray {selection} {modal} channelData={channelSeries} {onDeleteFit} />
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
  .flyover:focus {
    outline: none;
  }
</style>
