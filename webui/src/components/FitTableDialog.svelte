<script lang="ts">
  /**
   * The modal fit in full: every mode's fn / ζ / Q, and its modal constant
   * An and phase φn on every fitted line (4C6 lab, 2026-11). The fit chip
   * over the plot stays compact once a model spans many lines (a beam tested
   * at 20+ points lists 20+ constants per mode); this is where they are read,
   * one column pair per mode, one row per line, so a mode shape reads down
   * a column. **Copy** puts the same grid on the clipboard as tab-separated
   * text, at full precision, for a spreadsheet (`fitTableTsv`).
   *
   * DUMB component: it renders what it is given and reports a close. Mounted
   * by FitChip, which moves it to `document.body` (the chip is transformed by
   * its drag offset, and a transformed ancestor would trap a fixed overlay).
   */
  import { fitTableTsv, type ModalMode } from '../lib/stores/modal';

  let {
    modes,
    muted,
    labels,
    onclose,
  }: {
    modes: ModalMode[];
    muted: boolean[];
    /** The legend label of each fitted line, in column order. */
    labels: string[];
    onclose: () => void;
  } = $props();

  const nLines = $derived(modes.reduce((n, m) => Math.max(n, m.an.length), 0));
  const lineIdx = $derived(Array.from({ length: nLines }, (_, k) => k));

  /** Four significant figures, true minus sign, exponent when far from 1. */
  function fmt(v: number): string {
    if (!Number.isFinite(v)) return '—';
    const m = Math.abs(v);
    const txt = m !== 0 && (m >= 1e5 || m < 1e-3)
      ? v.toExponential(3).replace('e+', 'e')
      : String(Number(v.toPrecision(4)));
    return txt.replace('-', '−');
  }
  const fmtDeg = (d: number): string =>
    (Number.isFinite(d) ? `${d.toFixed(1).replace('-', '−')}°` : '—');
  const fmtQ = (q: number): string =>
    (!Number.isFinite(q) ? '∞' : q >= 100 ? q.toFixed(0) : q.toFixed(1));

  let tableEl = $state<HTMLTableElement>();
  const copyKey = /Mac|iPhone|iPad/.test(navigator.userAgent) ? '⌘C' : 'Ctrl+C';
  let copied = $state<'idle' | 'ok' | 'selected'>('idle');
  /**
   * Copy the grid as tab-separated text. A browser may refuse the clipboard
   * (a locked-down lab PC, an embedded view): then the older copy command is
   * tried, and failing that the table is SELECTED, so Ctrl+C (⌘C) copies it (a
   * selected table pastes into a spreadsheet as a grid too).
   */
  async function copy(): Promise<void> {
    const text = fitTableTsv(modes, muted, labels);
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const t = document.createElement('textarea');
      t.value = text;
      t.style.position = 'fixed';
      t.style.opacity = '0';
      document.body.appendChild(t);
      t.select();
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      t.remove();
    }
    if (!ok && tableEl) {
      const sel = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(tableEl);
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
    copied = ok ? 'ok' : 'selected';
    setTimeout(() => { copied = 'idle'; }, ok ? 1800 : 4000);
  }

  let closeBtn = $state<HTMLButtonElement>();
  $effect(() => { closeBtn?.focus(); });

  /** Escape closes — on the window, as the other dialogs do (focus may sit
   *  outside the overlay). */
  function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') onclose();
  }
</script>

<svelte:window on:keydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div
  class="overlay"
  data-testid="fit-table-overlay"
  role="dialog"
  aria-modal="true"
  aria-label="Modal fit table"
  tabindex="-1"
  onclick={(e) => { if (e.target === e.currentTarget) onclose(); }}
>
  <div class="modal">
    <div class="head">
      <div class="modal-title">
        Modal fit · {modes.length} mode{modes.length === 1 ? '' : 's'} on {nLines} line{nLines === 1 ? '' : 's'}
      </div>
      <button class="btn" data-testid="fit-table-copy" onclick={copy}
        title="Copy the table as tab-separated text, at full precision, for a spreadsheet"
      >{copied === 'ok' ? 'Copied' : copied === 'selected' ? `Selected: press ${copyKey}` : 'Copy'}</button>
      <button class="btn" bind:this={closeBtn} onclick={onclose} aria-label="close fit table">Close</button>
    </div>
    <div class="table-host">
      <table class="fit-table mono" data-testid="fit-table" bind:this={tableEl}>
        <thead>
          <tr>
            <th class="lab"></th>
            {#each modes as _, i (i)}
              <th colspan="2" class="mode-h" class:muted={muted[i]}>mode {i + 1}{muted[i] ? ' (muted)' : ''}</th>
            {/each}
          </tr>
          <tr class="pole">
            <th class="lab">fn (Hz)</th>
            {#each modes as m, i (i)}<td colspan="2" class:muted={muted[i]}>{m.fn.toFixed(2)}</td>{/each}
          </tr>
          <tr class="pole">
            <th class="lab">ζ</th>
            {#each modes as m, i (i)}<td colspan="2" class:muted={muted[i]}>{m.zn.toFixed(5)}</td>{/each}
          </tr>
          <tr class="pole last">
            <th class="lab">Q</th>
            {#each modes as m, i (i)}<td colspan="2" class:muted={muted[i]}>{fmtQ(m.Q)}</td>{/each}
          </tr>
          <tr class="sub">
            <th class="lab">line</th>
            {#each modes as _, i (i)}<th class="sub-h">An</th><th class="sub-h">φn</th>{/each}
          </tr>
        </thead>
        <tbody>
          {#each lineIdx as k (k)}
            <tr>
              <th class="lab">{labels[k] ?? `line ${k + 1}`}</th>
              {#each modes as m, i (i)}
                <td class:muted={muted[i]}>{fmt(m.an[k])}</td>
                <td class="deg" class:muted={muted[i]}>{fmtDeg(m.pnDeg[k])}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="note">
      An and φn are the modal constant of each line: the mode adds
      An·e<sup>iφn</sup> / (ωn² − ω² + 2i·ζn·ωn·ω) to H/(iω)<sup>p</sup>, with
      p = 2, 1, 0 for acceleration, velocity, displacement.
    </p>
  </div>
</div>

<style>
  /* The house modal surface (CalibrateDialog / SonoIncludeDialog). */
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 330;
    background: var(--scrim);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
  }
  .modal {
    max-width: min(96vw, 1200px);
    max-height: 90vh;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-radius: 12px;
    padding: 14px 16px 12px;
    box-shadow: 0 24px 70px rgba(16, 24, 40, 0.35);
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .modal-title {
    flex: 1;
    font-weight: 700;
    font-size: 14px;
  }
  .btn {
    border: 1px solid var(--border);
    background: var(--surface);
    border-radius: 6px;
    font-size: 12px;
    padding: 4px 10px;
    cursor: pointer;
    color: var(--text);
  }
  .btn:hover { background: var(--hover, #f0f0f4); }
  .table-host {
    overflow: auto;
    min-height: 0;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  .fit-table {
    border-collapse: separate;
    border-spacing: 0;
    font-size: 11.5px;
    color: var(--text);
  }
  .fit-table th, .fit-table td {
    padding: 3px 9px;
    text-align: right;
    white-space: nowrap;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
  }
  /* The line labels stay put while the modes scroll sideways, and the
     mode headings while the lines scroll down. */
  .fit-table .lab {
    position: sticky;
    left: 0;
    z-index: 1;
    text-align: left;
    font-weight: 600;
    color: var(--text);
  }
  .fit-table thead tr:first-child th {
    position: sticky;
    top: 0;
    z-index: 2;
  }
  .fit-table thead tr:first-child th.lab { z-index: 3; }
  .mode-h {
    text-align: center !important;
    color: var(--indigo);
    font-weight: 700;
  }
  .pole td { text-align: center; color: var(--text); }
  .pole.last td, .pole.last th { border-bottom-color: var(--text); }
  .sub-h {
    color: var(--muted);
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .deg { color: var(--muted); }
  .muted { opacity: 0.5; }
  .note {
    font-size: 11px;
    line-height: 1.4;
    color: var(--muted);
    margin: 8px 2px 0;
  }
</style>
