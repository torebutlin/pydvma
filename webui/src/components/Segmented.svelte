<script lang="ts" generics="T">
  /**
   * Shared segmented single-choice control (round-4 controls redesign).
   *
   * ONE control language app-wide: a row of tight buttons where exactly one
   * is `.active`, replacing the ambiguous "toggle button that renames itself"
   * (a single button showing `dB`/`lin` gave no clue whether it displayed the
   * CURRENT state or the state it would SET — round-4 feedback item 7). Each
   * option is always visible, so the current selection and the alternatives
   * are both legible at a glance.
   *
   * Ported from the `.seg` / `.sbtn` styling in `dev/mockups/round2-bench.html`
   * and the pre-existing inline segmented toggles in `ZoomToolbar`, now shared
   * by the plot toolbar (lin|log, dB|lin) AND the Live viewer (dB|lin, log|lin
   * f, FFT|PSD, full|range) so the two behave identically (feedback item 2).
   *
   * Generic over the option value `T` (string, boolean, number…), compared by
   * `===`; `onchange` fires with the picked option's value. An optional leading
   * `label` renders a small mono tag (e.g. `x` / `y`) that reads as part of the
   * control. `testid` lands on the group; a per-option `testid` lands on its
   * button (so existing e2e hooks like `live-mode-psd` survive the refactor).
   */
  interface Option<V> {
    value: V;
    label: string;
    /** Native tooltip / hover title. */
    title?: string;
    /** Optional per-button data-testid (preserves existing e2e hooks). */
    testid?: string;
  }

  let {
    options,
    value,
    onchange,
    ariaLabel,
    label = '',
    testid = undefined,
  }: {
    options: Option<T>[];
    /** Currently selected value (compared to each option by `===`). */
    value: T;
    /** Fired with the chosen option's value. */
    onchange: (v: T) => void;
    /** Accessible group label (also used as the ARIA name). */
    ariaLabel: string;
    /** Optional leading mono tag rendered inside the group (e.g. `x`). */
    label?: string;
    /** Optional data-testid for the group container. */
    testid?: string;
  } = $props();
</script>

<span class="segmented" role="group" aria-label={ariaLabel} data-testid={testid}>
  {#if label}<span class="segmented-tag" aria-hidden="true">{label}</span>{/if}
  <span class="segmented-btns">
    {#each options as opt (String(opt.value))}
      <button
        type="button"
        class="segmented-btn"
        class:active={opt.value === value}
        aria-pressed={opt.value === value}
        title={opt.title}
        data-testid={opt.testid}
        onclick={() => onchange(opt.value)}
      >{opt.label}</button>
    {/each}
  </span>
</span>

<!-- Class names avoid the bare `.seg`/`button` used by the global
     `.card-controls .seg` rule so this component styles itself consistently
     whether mounted inside a card (Live viewer) or on the plot (ZoomToolbar). -->
<style>
  .segmented {
    display: inline-flex;
    align-items: center;
    gap: 5px;
  }
  .segmented-tag {
    color: var(--muted, #66708a);
    font: 600 11px var(--font-mono, ui-monospace, Menlo, monospace);
  }
  /* The buttons share a bordered pill so they read as ONE control. */
  .segmented-btns {
    display: inline-flex;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 7px;
    overflow: hidden;
    background: var(--control-bg);
  }
  .segmented-btn {
    border: none;
    border-right: 1px solid var(--border, #e3e6eb);
    background: var(--control-bg);
    height: 26px;
    min-width: 30px;
    padding: 0 10px;
    cursor: pointer;
    color: var(--muted, #66708a);
    font: 600 11.5px var(--font-body, system-ui, sans-serif);
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  .segmented-btn:last-child {
    border-right: none;
  }
  .segmented-btn:hover {
    background: var(--hover-bg);
    color: var(--text, #1b2437);
  }
  .segmented-btn.active {
    background: var(--accent-soft);
    color: var(--indigo, #4f46e5);
  }
</style>
