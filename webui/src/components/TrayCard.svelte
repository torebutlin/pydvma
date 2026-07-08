<script lang="ts">
  /**
   * One set card in the data tray (design spec §5; visuals ported from
   * the `.set-card` block of dev/mockups/round2-bench.html). Renders a
   * single `SetView` and drives the selection store's per-set and
   * per-line operations.
   *
   * Header: a colour-dot stack (one dot per channel, coloured by
   * `selection.lineColor`), the set name, a duration badge, a collapse
   * chevron and a delete `×`.
   *
   * The set name is the whole-set tri-state control (round-3 item 3): a
   * SINGLE click cycles the entire set (`cycleSet`: on → fade → off, a
   * mixed set snapping to 'on' first), a DOUBLE click opens the inline
   * rename (committed on Enter/blur, cancelled on Esc). The two are
   * disambiguated with a deferred-click timer (`onTitleClick` schedules
   * the cycle; `onTitleDblClick` cancels it and renames) so a rename never
   * also cycles. The title is a `role="button"` (Enter/Space cycle, F2
   * renames) so the action is keyboard-reachable. Clicking the header
   * anywhere ELSE (away from the title and the buttons/input) also cycles
   * the set, instantly; `onHeaderClick` guards controls and mid-rename
   * clicks. A set uniformly 'off' is struck-through + card-dimmed
   * (`set.allOff`); uniformly 'fade' dims just the title (`set.allFade`).
   *
   * When expanded, one row per channel: a colour chip (click →
   * `cycleLine`, dimmed to 40% when faded), a channel label (custom via
   * `selection.channelLabel`, default `ch_{c}`; double-click → inline
   * rename committed on Enter/blur, cancelled on Esc — mirrors the
   * set-name rename), a sparkline and a state badge. The row is a
   * `<button>` that cycles the tri-state on click; `onChRowClick` guards
   * that cycle so it never fires while the rename input is open or when
   * the click lands on the input itself (a single click still cycles; a
   * double-click on the label edits). Sparklines draw REAL data only —
   * when
   * `channelData(c)` returns a series it is min-max-decimated to ~60
   * columns; otherwise a flat muted placeholder line is shown (never
   * fabricated samples). A set whose lines are all off (`set.allOff`) is
   * struck through and the whole card dimmed ("out of stock").
   */
  import type { Selection, SetView } from '../lib/stores/selection';
  import { minMaxDecimate } from '../lib/plot/decimate';
  import { sigFigs } from '../lib/format';

  let {
    selection,
    set,
    onDeleteSet,
    onCalibrate,
    channelData,
    fit,
  }: {
    selection: Selection;
    set: SetView;
    onDeleteSet: (id: number) => void;
    /** Open the per-set calibration dialog (Task A2). Absent → no cal button. */
    onCalibrate?: (id: number) => void;
    channelData?: (ch: number) => Float64Array | undefined;
    /**
     * Modal-fit pseudo-set descriptor (round-5 item 13). When present the card
     * is the "Modal fit" card: a mode-count badge replaces the duration badge
     * and the × (via `onDeleteSet`) clears the modal model rather than removing
     * a data set. Its per-line controls are otherwise identical to a data set,
     * so the recon lines get normal tri-state / rename / legend behaviour.
     */
    fit?: { modeCount: number };
  } = $props();

  const stateStore = $derived(selection.state);
  const labelStore = $derived(selection.channelLabel);

  // Inline set-name-rename state.
  let editing = $state(false);
  let draft = $state('');

  function startRename() {
    draft = set.name;
    editing = true;
  }
  function commitRename() {
    if (!editing) return;
    editing = false;
    const name = draft.trim();
    if (name && name !== set.name) selection.rename(set.id, name);
  }
  function cancelRename() {
    editing = false;
  }
  function onNameKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') commitRename();
    else if (e.key === 'Escape') cancelRename();
  }

  // Inline channel-label-rename state (Task R5) — MIRRORS the set-name
  // rename: double-click the `.ch-lab` → text input, committed on
  // Enter/blur, cancelled on Esc. Only one channel edits at a time.
  let editingCh = $state<number | null>(null);
  let chDraft = $state('');

  function startChRename(ch: number) {
    chDraft = $labelStore(set.id, ch);
    editingCh = ch;
  }
  function commitChRename() {
    if (editingCh === null) return;
    const ch = editingCh;
    editingCh = null;
    // renameChannel trims and treats blank as "reset to default", so we
    // can hand it the raw draft — including an emptied field (reset).
    selection.renameChannel(set.id, ch, chDraft);
  }
  function cancelChRename() {
    editingCh = null;
  }
  function onChKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') commitChRename();
    else if (e.key === 'Escape') cancelChRename();
  }

  // ── Whole-set tri-state via the card title (round-3 item 3) ──────────
  // Clicking the title cycles the WHOLE set (`cycleSet`: on → fade → off,
  // mixed → on first); double-clicking the title still opens the inline
  // rename. Because a double-click also delivers two `click` events, a
  // naked single-click handler would cycle (twice) on the way to renaming.
  // We disambiguate with the standard deferred-click timer: a click on the
  // title schedules the cycle after a short window, and a following
  // dblclick cancels it and renames instead. (Spatial separation — used by
  // the channel rows, where the rename-able `.ch-lab` is simply excluded
  // from the row's cycle target — is not an option here because item 3
  // asks the title ITSELF to be the cycle target.)
  const DBLCLICK_MS = 220;
  let titleClickTimer: ReturnType<typeof setTimeout> | null = null;
  function clearTitleTimer() {
    if (titleClickTimer !== null) {
      clearTimeout(titleClickTimer);
      titleClickTimer = null;
    }
  }
  function onTitleClick() {
    if (editing) return;                 // a click while editing must not cycle
    clearTitleTimer();                   // collapse the 2nd click of a dblclick
    titleClickTimer = setTimeout(() => {
      titleClickTimer = null;
      selection.cycleSet(set.id);
    }, DBLCLICK_MS);
  }
  function onTitleDblClick() {
    clearTitleTimer();                   // cancel the pending single-click cycle
    if (editing) return;
    startRename();
  }
  // Keyboard: the title is a role=button, so Enter/Space cycle (no
  // dblclick race, so cycle immediately) and F2 renames (the OS-standard
  // rename key) — keeps the whole-set action reachable without a mouse.
  function onTitleKeydown(e: KeyboardEvent) {
    if (editing) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      clearTitleTimer();
      selection.cycleSet(set.id);
    } else if (e.key === 'F2') {
      e.preventDefault();
      clearTitleTimer();
      startRename();
    }
  }

  // Clicking the header AWAY from the title + controls also cycles the set
  // (a bigger mouse target), instantly — no dblclick action lives there, so
  // no deferral is needed. Guarded against controls (name/input, buttons,
  // chevron, ×) and against firing mid-rename. Clears any pending title
  // cycle so a title-click-then-header-click can't double-fire.
  function onHeaderClick(e: MouseEvent) {
    if (editing) return;
    const t = e.target as HTMLElement;
    if (t.closest('button, input, .set-name')) return;
    clearTitleTimer();
    selection.cycleSet(set.id);
  }

  // The channel row is a <button> that cycles the tri-state on click.
  // Guard the cycle so it does NOT fire while a rename input is open, when
  // the click lands on the rename input, OR when it lands on the `.ch-lab`
  // itself — the label is the rename affordance (double-click → edit), so
  // like the set-name span it must be excluded from the toggle target, or
  // a double-click's two `click` events would cycle the line twice on the
  // way to opening the editor. A click anywhere ELSE on the row (chip,
  // sparkline, badge) still cycles. Mirrors `onHeaderClick`'s guard list.
  function onChRowClick(ch: number, e: MouseEvent) {
    const t = e.target as HTMLElement;
    if (editingCh === ch || t.closest('input, .ch-lab')) return;
    selection.cycleLine(set.id, ch);
  }

  const SPARK_W = 46;
  const SPARK_H = 14;
  const SPARK_COLS = 60;

  /**
   * Build an SVG polyline `points` string for one channel's sparkline
   * from real data, or `undefined` when no data is available (caller
   * renders a flat placeholder instead — no fabricated samples).
   */
  function sparkPoints(ch: number): string | undefined {
    const data = channelData?.(ch);
    if (!data || data.length === 0) return undefined;
    const pts = minMaxDecimate(data, 0, data.length - 1, SPARK_COLS);
    if (pts.length === 0) return undefined;
    let lo = Infinity;
    let hi = -Infinity;
    for (const [, v] of pts) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    const span = hi - lo || 1;
    const n = pts.length;
    return pts
      .map(([, v], i) => {
        const x = n === 1 ? 0 : (i / (n - 1)) * SPARK_W;
        const y = SPARK_H - ((v - lo) / span) * SPARK_H;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(' ');
  }
</script>

<div
  class="set-card"
  class:dim={set.allOff}
  data-testid={`tray-card-${set.index}`}
>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="set-head"
    class:struck={set.allOff}
    class:faded={set.allFade}
    data-testid="set-header"
    onclick={onHeaderClick}
  >
    <button
      class="caret"
      title={set.collapsed ? 'Expand' : 'Collapse'}
      aria-label={set.collapsed ? 'Expand set' : 'Collapse set'}
      onclick={() => selection.toggleCollapse(set.id)}
    >{set.collapsed ? '▸' : '▾'}</button>

    <span class="dotstack">
      {#each set.colors as c, ch (ch)}
        <i style="background:{selection.lineColor(set.id, ch) ?? c}"></i>
      {/each}
      <em>{set.nChannels}</em>
    </span>

    {#if editing}
      <span class="set-name">
        <!-- svelte-ignore a11y_autofocus -->
        <input
          type="text"
          data-testid="set-name-input"
          bind:value={draft}
          onkeydown={onNameKeydown}
          onblur={commitRename}
          autofocus
        />
      </span>
    {:else}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <span
        class="set-name"
        role="button"
        tabindex="0"
        data-testid="set-name"
        title={`${set.name} — click to cycle the whole set on/fade/off; double-click (or F2) to rename`}
        aria-label={`${set.name}: set ${set.allOff ? 'hidden' : set.allFade ? 'faded' : 'shown'} — press Enter to cycle visibility, F2 to rename`}
        onclick={onTitleClick}
        ondblclick={onTitleDblClick}
        onkeydown={onTitleKeydown}
      >{set.name}</span>
    {/if}

    {#if fit}
      <span class="dur-badge fit-badge" title="Fitted modes in this modal model"
        >{fit.modeCount} mode{fit.modeCount === 1 ? '' : 's'}</span>
    {:else}
      <span class="dur-badge">{sigFigs(set.durationS)} s</span>
    {/if}
    {#if onCalibrate}
      <button
        class="cal-btn"
        data-testid="cal-open"
        title="Calibrate channels…"
        aria-label={`Calibrate ${set.name}`}
        onclick={() => onCalibrate?.(set.id)}
      >cal</button>
    {/if}
    <button
      class="xdel"
      title={fit ? 'Clear modal fit' : 'Delete set'}
      aria-label={fit ? 'Clear modal fit' : 'Delete set'}
      onclick={() => onDeleteSet(set.id)}
    >×</button>
  </div>

  {#if !set.collapsed}
    <div class="ch-list">
      {#each set.colors as c, ch (ch)}
        {@const st = $stateStore(set.id, ch)}
        {@const pts = sparkPoints(ch)}
        <!-- The WHOLE row cycles the line (chip + label + sparkline + badge),
             not just the colour chip — matches the mockup's click target. -->
        {@const chLab = $labelStore(set.id, ch)}
        <button
          type="button"
          class="ch-row"
          class:st-fade={st === 'fade'}
          class:st-off={st === 'off'}
          class:editing={editingCh === ch}
          data-testid={`ch-row-${ch}`}
          title={`${chLab}: ${st} — click to cycle on → fade → off`}
          aria-label={`Toggle channel ${ch} (currently ${st})`}
          onclick={(e) => onChRowClick(ch, e)}
        >
          <span
            class="ch-chip"
            style="background:{selection.lineColor(set.id, ch) ?? c}"
          ></span>
          {#if editingCh === ch}
            <!-- svelte-ignore a11y_autofocus -->
            <input
              class="ch-lab-input"
              type="text"
              data-testid={`ch-lab-input-${ch}`}
              bind:value={chDraft}
              onkeydown={onChKeydown}
              onblur={commitChRename}
              onclick={(e) => e.stopPropagation()}
              onmousedown={(e) => e.stopPropagation()}
              ondblclick={(e) => e.stopPropagation()}
              autofocus
            />
          {:else}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <span
              class="ch-lab"
              data-testid={`ch-lab-${ch}`}
              title="Double-click to rename"
              ondblclick={(e) => { e.stopPropagation(); startChRename(ch); }}
            >{chLab}</span>
          {/if}
          <svg class="spark" viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} preserveAspectRatio="none" aria-hidden="true">
            {#if pts}
              <polyline points={pts} fill="none" stroke={selection.lineColor(set.id, ch) ?? c} stroke-width="1" />
            {:else}
              <line x1="0" y1={SPARK_H / 2} x2={SPARK_W} y2={SPARK_H / 2} stroke="var(--border)" stroke-width="1" />
            {/if}
          </svg>
          <span class="state-badge state-{st}">{st}</span>
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .set-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 8px 10px 6px;
    margin-bottom: 10px;
  }
  .set-card.dim {
    opacity: 0.5;
  }
  .set-head {
    display: flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    border-radius: 6px;
    padding: 1px 2px;
  }
  .set-head:hover {
    background: var(--hover-bg);
  }
  .set-head.struck .set-name {
    text-decoration: line-through;
  }
  /* Whole set uniformly faded → dim the title, mirroring how a faded ROW
     reads (rows use opacity ~0.55). Struck (all-off) still wins visually
     via the whole-card .dim + line-through above. */
  .set-head.faded .set-name {
    opacity: 0.55;
  }
  /* Keyboard focus ring for the now-focusable title (role=button). */
  .set-name:focus-visible {
    outline: 2px solid var(--accent-soft-border);
    outline-offset: 1px;
  }
  .caret {
    border: none;
    background: none;
    color: var(--muted-2);
    cursor: pointer;
    font-size: 10px;
    width: 16px;
    padding: 0;
    flex: 0 0 auto;
  }
  .caret:hover {
    color: var(--text);
  }
  .dotstack {
    display: inline-flex;
    align-items: center;
    flex: 0 0 auto;
  }
  .dotstack i {
    width: 9px;
    height: 9px;
    border-radius: 3px;
    margin-left: -2px;
    outline: 1.5px solid var(--surface);
  }
  .dotstack i:first-child {
    margin-left: 0;
  }
  .dotstack em {
    font: 600 9px var(--font-mono);
    font-style: normal;
    color: var(--muted-2);
    margin-left: 2px;
  }
  .set-name {
    font-weight: 650;
    font-size: 13px;
    border-radius: 4px;
    padding: 0 2px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .set-name input {
    font: 650 13px var(--font-body);
    width: 110px;
    height: 22px;
    border: 1px solid var(--accent-soft-border);
    border-radius: 5px;
    padding: 0 4px;
    background: var(--control-bg);
    color: var(--text);
  }
  .dur-badge {
    margin-left: auto;
    font: 600 10.5px var(--font-mono);
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 1px 5px;
    background: var(--surface-2);
    flex: 0 0 auto;
  }
  /* Modal-fit card: the mode-count badge reads as an indigo accent (matching
     the Fit stage / chip) so the fit card is distinguishable at a glance. */
  .fit-badge {
    color: var(--indigo, #4f46e5);
    border-color: color-mix(in srgb, var(--indigo, #4f46e5) 35%, var(--border));
    background: color-mix(in srgb, var(--indigo, #4f46e5) 8%, var(--surface));
  }
  .cal-btn {
    border: 1px solid var(--border);
    color: var(--muted);
    background: var(--control-bg);
    border-radius: 5px;
    height: 18px;
    padding: 0 6px;
    font: 600 9.5px var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1;
    cursor: pointer;
    flex: 0 0 auto;
    display: none;
    align-items: center;
    justify-content: center;
  }
  .set-card:hover .cal-btn {
    display: inline-flex;
  }
  .cal-btn:hover {
    border-color: var(--indigo);
    color: var(--indigo);
    background: var(--accent-soft);
  }
  .xdel {
    border: 1px solid var(--danger-border);
    color: var(--danger);
    background: var(--control-bg);
    border-radius: 5px;
    width: 18px;
    height: 18px;
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    flex: 0 0 auto;
    display: none;
    align-items: center;
    justify-content: center;
    padding: 0;
  }
  .set-card:hover .xdel {
    display: inline-flex;
  }
  .xdel:hover {
    background: var(--danger-soft);
  }
  .ch-list {
    margin-top: 3px;
  }
  .ch-row {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 3px 2px;
    border-radius: 6px;
    /* Reset <button> defaults so the row reads as a plain interactive strip. */
    width: 100%;
    box-sizing: border-box;
    border: none;
    background: transparent;
    text-align: left;
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  .ch-row:hover {
    background: var(--hover-bg);
  }
  .ch-row.st-fade {
    opacity: 0.55;
  }
  .ch-row.st-fade .ch-chip {
    opacity: 0.4;
  }
  .ch-row.st-off {
    opacity: 0.5;
  }
  .ch-row.st-off .ch-chip {
    opacity: 0.15;
  }
  .ch-row.st-off .ch-lab {
    text-decoration: line-through;
    color: var(--muted);
  }
  .ch-chip {
    width: 14px;
    height: 14px;
    border-radius: 4px;
    flex: 0 0 auto;
    outline: 1px solid var(--border);
    outline-offset: 1px;
  }
  .ch-lab {
    font: 12px var(--font-mono);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ch-lab-input {
    font: 12px var(--font-mono);
    width: 96px;
    height: 20px;
    border: 1px solid var(--accent-soft-border);
    border-radius: 5px;
    padding: 0 4px;
    box-sizing: border-box;
    background: var(--control-bg);
    color: var(--text);
  }
  /* Keep the row from tinting/underlining the label while editing. */
  .ch-row.editing {
    cursor: default;
  }
  .ch-row.editing.st-off .ch-lab-input {
    text-decoration: none;
  }
  .spark {
    width: 46px;
    height: 14px;
    margin-left: auto;
    flex: 0 0 auto;
    opacity: 0.85;
  }
  .state-badge {
    font: 600 9px var(--font-mono);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: 4px;
    padding: 1px 4px;
    flex: 0 0 auto;
  }
  .state-on {
    color: var(--green);
    background: var(--success-soft);
  }
  .state-fade {
    color: var(--amber);
    background: var(--amber-soft);
  }
  .state-off {
    color: var(--muted);
    background: var(--surface-2);
  }
</style>
