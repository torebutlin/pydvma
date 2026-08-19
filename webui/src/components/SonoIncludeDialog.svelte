<script lang="ts">
  /**
   * "Include sonogram data?" — the save-time prompt (derived-data round,
   * Task 5b; Tore's design).
   *
   * Save materialises the computed FFT and TF silently, because the app
   * already holds exactly what the file wants. A sonogram is different: the
   * view is ONE channel's magnitude image while pydvma's `SonoData` stores the
   * whole complex cube, so including it means running the transform again —
   * seconds on a long record under the browser engine, and a noticeably bigger
   * file. That is a decision, so it is asked rather than assumed, and only
   * when there is actually a sonogram to store (a session that never opened
   * the Sono card never sees this dialog, and autosave never raises it).
   *
   * Three answers, matching `SonoSaveChoice`:
   *   - **This channel** (the default): store the channel the sono view is
   *     showing — the one the user has been looking at;
   *   - **All channels**: store every channel of each listed measurement;
   *   - **Don't include**: save without it.
   *
   * DISMISSAL IS "DON'T INCLUDE", NOT "CANCEL". Escape and a backdrop click
   * both resolve to `'none'`, so the save the user already committed to (they
   * have named the file by this point) always completes. Nothing here can
   * abandon a save silently.
   *
   * DUMB component: it renders the names it is given and reports the choice.
   * The recompute, the item building and any failure toast belong to the
   * caller (`actions.includeSonograms` / App's save handler).
   */
  import type { SonoSaveChoice } from '../lib/analysis/actions';

  let {
    setNames,
    onchoose,
  }: {
    /** Display names of the measurements a sonogram would be stored for. */
    setNames: string[];
    /** The user's answer; dismissal reports `'none'`. */
    onchoose: (choice: SonoSaveChoice) => void;
  } = $props();

  const many = $derived(setNames.length > 1);

  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') onchoose('none');
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="overlay"
  data-testid="sono-include-overlay"
  role="dialog"
  aria-modal="true"
  aria-label="Include sonogram data?"
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) onchoose('none'); }}
  onkeydown={onKeydown}
>
  <div class="modal">
    <div class="modal-title">Include sonogram data?</div>

    <p class="body">
      {many ? 'These measurements have' : 'This measurement has'} a sonogram:
      <span class="names">{setNames.join(', ')}</span>.
      Saving {many ? 'them' : 'it'} recomputes the full complex sonogram so the
      file holds real data, not just the picture.
    </p>
    <p class="note">
      Including sonograms can make saving slower and files larger.
    </p>

    <div class="mrow end">
      <button class="btn" data-testid="sono-include-none" onclick={() => onchoose('none')}>
        Don't include
      </button>
      <button class="btn" data-testid="sono-include-all" onclick={() => onchoose('all')}>
        All channels
      </button>
      <!-- svelte-ignore a11y_autofocus -->
      <button
        class="btn indigo"
        data-testid="sono-include-channel"
        autofocus
        onclick={() => onchoose('channel')}
      >This channel</button>
    </div>
  </div>
</div>

<style>
  /* Same overlay/modal surface as CalibrateDialog (the house modal). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .modal {
    width: 400px;
    background: var(--surface);
    border-radius: 12px;
    padding: 16px 18px 14px;
    box-shadow: 0 24px 70px rgba(16, 24, 40, 0.35);
  }
  .modal-title {
    font-weight: 700;
    font-size: 14px;
    margin-bottom: 10px;
  }
  .body {
    font-size: 12.5px;
    line-height: 1.45;
    color: var(--text);
    margin: 0 0 8px;
  }
  .names {
    font-family: var(--font-mono);
    font-size: 11.5px;
  }
  .note {
    font-size: 11.5px;
    line-height: 1.4;
    color: var(--muted);
    margin: 0;
  }
  .mrow {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mrow.end {
    justify-content: flex-end;
    margin-top: 16px;
  }
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 28px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--control-bg);
    color: var(--text);
    font-family: inherit;
    font-size: 12.5px;
    font-weight: 500;
    cursor: pointer;
    white-space: nowrap;
  }
  .btn:hover {
    border-color: var(--border-strong);
    background: var(--hover-bg);
  }
  .btn.indigo {
    background: var(--indigo, #4f46e5);
    border-color: var(--indigo, #4f46e5);
    color: #fff;
    font-weight: 600;
  }
  .btn.indigo:hover {
    background: var(--indigo-hover);
  }
</style>
