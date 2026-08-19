<script lang="ts">
  /**
   * "Choose sets…" — the subset picker for Save Dataset / Export Matlab /
   * Export CSV (derived-data round, Task 5). A checkbox list of the current
   * MEASUREMENTS, each row showing the set's display name and small badges
   * for what it carries (time · fft · tf · fit), with OK / Cancel.
   *
   * SELECTION STATE IS LOCAL TO ONE INVOCATION: every row starts TICKED on
   * every open, the pick is deliberately not persisted between opens, and it
   * is never read from — nor does it write to — the view / solo / fade state.
   * What is on screen and what a save contains are separate questions by
   * design; the primary buttons beside this one still mean "everything".
   *
   * That guarantee rests on being MOUNTED FRESH per open, which the card
   * arranges with `{#key pick}` — hopping straight from one split control's
   * picker to another leaves the surrounding `{#if}` truthy throughout, so
   * without the key this instance would be reused and carry its ticks over.
   *
   * Positioned absolutely inside a `position: relative` anchor, following
   * ZoomToolbar's `.ax-pop` precedent (which is where the surface styling
   * comes from). Dismissal follows CalibrateDialog: Escape cancels, and a
   * pointer press outside the anchor cancels — the anchor, not this element,
   * so pressing the ▾ button that opened it closes rather than reopens.
   *
   * DUMB component: it receives the rows, edits a local tick list, and hands
   * the chosen `setId`s back on confirm. It knows nothing about saving.
   */
  import type { ChoosableSet } from '../lib/export/data';

  let {
    sets,
    title,
    confirmLabel = 'Save',
    anchor = null,
    onconfirm,
    oncancel,
  }: {
    /** One row per measurement, in load order (`actions.choosableSets()`). */
    sets: ChoosableSet[];
    /** What the pick is for, e.g. "Save Dataset" — the popover's heading. */
    title: string;
    /** Verb on the confirm button ("Save" / "Export"). */
    confirmLabel?: string;
    /** Element a pointer press must fall OUTSIDE of to dismiss. */
    anchor?: HTMLElement | null;
    onconfirm: (setIds: number[]) => void;
    oncancel: () => void;
  } = $props();

  // All ticked, seeded ONCE per mount — the component is mounted fresh on
  // every open (an `{#if}` in the card), which is exactly what makes
  // "all ticked initially, every time" true without any reset logic.
  // svelte-ignore state_referenced_locally
  let picked = $state<boolean[]>(sets.map(() => true));

  let rootEl = $state<HTMLDivElement>();

  const anyPicked = $derived(picked.some(Boolean));

  function confirm(): void {
    onconfirm(sets.filter((_, i) => picked[i]).map((s) => s.setId));
  }

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') oncancel();
  }

  /** Dismiss on a press outside the anchor (which contains this popover). */
  function onPointerDown(e: PointerEvent): void {
    const t = e.target as Node | null;
    if (!t) return;
    if (anchor?.contains(t) || rootEl?.contains(t)) return;
    oncancel();
  }
</script>

<svelte:window on:keydown={onKeydown} on:pointerdown={onPointerDown} />

<div
  class="ax-pop cs-pop"
  bind:this={rootEl}
  data-testid="choose-sets-popover"
  role="dialog"
  aria-label={`${title} — choose sets`}
>
  <div class="cs-title">{title} — choose sets</div>

  {#if sets.length === 0}
    <div class="cs-empty">No measurements loaded.</div>
  {:else}
    <div class="cs-list">
      {#each sets as s, i (s.setId)}
        <label class="cs-row" data-testid={`choose-set-${s.setId}`}>
          <input type="checkbox" bind:checked={picked[i]} aria-label={s.name} />
          <span class="cs-name">{s.name}</span>
          <span class="cs-kinds">
            {#each s.kinds as k (k)}<span class="cs-badge">{k}</span>{/each}
          </span>
        </label>
      {/each}
    </div>
  {/if}

  <div class="cs-actions">
    <button class="btn" data-testid="choose-sets-cancel" onclick={oncancel}>Cancel</button>
    <button
      class="btn indigo"
      data-testid="choose-sets-ok"
      disabled={!anyPicked}
      title={anyPicked ? undefined : 'Tick at least one set'}
      onclick={confirm}>{confirmLabel}</button>
  </div>
</div>

<style>
  /* Surface + placement ported from ZoomToolbar's `.ax-pop` (the house
     popover), dropped BELOW-LEFT of the split buttons that open it. */
  .ax-pop {
    position: absolute;
    top: calc(100% + 5px);
    left: 0;
    z-index: 8;
    background: var(--surface, #ffffff);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: var(--radius, 10px);
    box-shadow: var(--shadow-lg, 0 8px 28px rgba(16, 24, 40, 0.16));
    padding: 11px 12px;
  }
  .cs-pop {
    min-width: 240px;
    max-width: 340px;
  }
  .cs-title {
    font: 700 11px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--indigo, #4f46e5);
    letter-spacing: 0.04em;
    margin-bottom: 7px;
  }
  .cs-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
    max-height: 240px;
    overflow-y: auto;
  }
  .cs-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    color: var(--text);
  }
  .cs-row:hover {
    background: var(--hover-bg);
  }
  .cs-row input {
    margin: 0;
    accent-color: var(--indigo);
    cursor: pointer;
  }
  .cs-name {
    flex: 1 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cs-kinds {
    display: inline-flex;
    gap: 3px;
    flex: 0 0 auto;
  }
  /* Same visual weight as the tray's `.dur-badge` / `.fit-badge` chips. */
  .cs-badge {
    font: 600 9.5px var(--font-mono, ui-monospace, Menlo, monospace);
    color: var(--muted, #66708a);
    background: var(--surface-2);
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 5px;
    padding: 0 4px;
    line-height: 15px;
  }
  .cs-empty {
    font-size: 12px;
    color: var(--muted, #66708a);
    padding: 4px 2px;
  }
  .cs-actions {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
    margin-top: 9px;
  }
</style>
