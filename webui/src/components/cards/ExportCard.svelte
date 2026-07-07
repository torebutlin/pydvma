<script lang="ts">
  /**
   * Export-stage context card (design spec §3; Task 14). Two save flows
   * plus the app-wide autosave toggle folded in (plan amendment A10):
   *
   *   - Save Dataset — delegates to the header's dataset-save handler
   *     (`onsave`), so there is one code path for writing the .dvma.
   *   - Save Figure — export the CURRENT plot's SVG as PNG and/or PDF,
   *     with a white / transparent / dark background, to the working dir
   *     (or a browser download in fallback mode). PNG and PDF are
   *     independent checkboxes: tick both and BOTH files are written (no
   *     silent two-for-one). The figure SVG comes from the active
   *     PlotSurface via the `getSvg` accessor; the restyle + rasterise /
   *     vectorise lives in src/lib/export/figure.ts.
   *   - Autosave — a toggle bound to the app's `autosaveEnabled` $state
   *     (threaded down as a bindable prop). This is where Task 13a's
   *     autosave switch finally gets a UI.
   *
   * Matlab / CSV data export are enabled when an `exporter` accessor is wired
   * (the analysis `actions`): Matlab downloads engine-built `.mat` bytes
   * (`scipy.io.savemat`), CSV serialises the raw arrays in pure TS
   * (src/lib/export/data.ts). When no exporter is provided they fall back to
   * DISABLED with an honest tooltip.
   */
  import { exportPdf, exportPng, type BackgroundMode } from '../../lib/export/figure';
  import { buildCsvFiles, type Exporter } from '../../lib/export/data';
  import { cancelAutosave } from '../../lib/files/autosave';
  import type { WorkDir } from '../../lib/files/workdir';
  import type { Toasts } from '../../lib/stores/toast';

  let {
    getSvg,
    workdir,
    onsave,
    toasts,
    hasData = false,
    exporter = undefined,
    datasetName = undefined,
    autosaveEnabled = $bindable(true),
  }: {
    /** Accessor for the active plot's root <svg> (null when no plot mounted). */
    getSvg: () => SVGSVGElement | undefined;
    /** Working directory to write into (null → browser download fallback). */
    workdir: WorkDir | null;
    /** The header's Save Dataset handler (single .dvma write path). */
    onsave: () => void;
    /** Shared toast store for success/error feedback. */
    toasts: Toasts;
    /** Whether any dataset is loaded (gates Save Figure + data export). */
    hasData?: boolean;
    /**
     * Data-export accessor (the analysis `actions`, which satisfies this
     * minimal surface). Absent → Matlab/CSV stay disabled with a tooltip.
     */
    exporter?: Exporter;
    /** Dataset name for the exported `.mat` / `.csv` base (else 'logged_data'). */
    datasetName?: string;
    /** App-wide autosave flag (bindable — this card owns its UI). */
    autosaveEnabled?: boolean;
  } = $props();

  // Save Figure dialog state.
  let png = $state(true);
  let pdf = $state(false);
  let bg = $state<BackgroundMode>('white');
  let filename = $state(defaultFigureName(new Date()));
  let busy = $state(false);

  /**
   * Autosave toggle change: when it goes OFF, cancel any pending debounced
   * write so a save scheduled by a mutation just before the toggle doesn't
   * still fire 2 s later. (The bound `autosaveEnabled` already gates future
   * schedules; this handles the in-flight one.)
   */
  function onAutosaveToggle(): void {
    if (!autosaveEnabled) cancelAutosave();
  }

  /** Default figure name: pydvma_figure_YYYY-MM-DD_HHMM (no extension). */
  function defaultFigureName(now: Date): string {
    const p = (n: number) => String(n).padStart(2, '0');
    const stamp = `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}_${p(now.getHours())}${p(now.getMinutes())}`;
    return `pydvma_figure_${stamp}`;
  }

  /** Strip any user-typed extension so we control .png/.pdf ourselves. */
  function baseName(): string {
    const n = filename.trim() || defaultFigureName(new Date());
    return n.replace(/\.(png|pdf)$/i, '');
  }

  /**
   * Write `bytes` as `name` via the working dir, or fall back to a browser
   * download when no folder is set. Mirrors App.svelte's save path so a
   * figure lands in the same place as a dataset.
   */
  async function write(name: string, bytes: Uint8Array): Promise<void> {
    if (workdir) {
      await workdir.save(name, bytes);
    } else {
      // Fallback download (no working folder / no File System Access API).
      const blob = new Blob([bytes.slice()], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  }

  /** Save Figure: serialise the active plot and write each ticked format. */
  async function saveFigure(): Promise<void> {
    const el = getSvg();
    if (!el) {
      toasts.push('No plot to export yet — load data and pick a view first.', { level: 'info' });
      return;
    }
    if (!png && !pdf) {
      toasts.push('Pick at least one format (PNG or PDF).', { level: 'info' });
      return;
    }
    const svgText = el.outerHTML;
    const base = baseName();
    busy = true;
    try {
      if (png) {
        const blob = await exportPng(svgText, bg);
        await write(`${base}.png`, new Uint8Array(await blob.arrayBuffer()));
      }
      if (pdf) {
        const blob = await exportPdf(svgText, bg);
        await write(`${base}.pdf`, new Uint8Array(await blob.arrayBuffer()));
      }
      const what = [png && 'PNG', pdf && 'PDF'].filter(Boolean).join(' + ');
      toasts.push(`Saved figure (${what})`, { level: 'success' });
    } catch (e) {
      toasts.push(`Figure export failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
    } finally {
      busy = false;
    }
  }

  /** Data-export filename base: the dataset name, else pydvma's logger default. */
  function dataBaseName(): string {
    return (datasetName?.trim() || 'logged_data').replace(/\.(mat|csv)$/i, '');
  }

  /**
   * Export Matlab: the engine builds the `.mat` (scipy.io.savemat, schema
   * matching pydvma export_to_matlab); this only downloads the bytes.
   */
  async function exportMatlab(): Promise<void> {
    if (!exporter) return;
    busy = true;
    try {
      const bytes = await exporter.exportMat();
      await write(`${dataBaseName()}.mat`, bytes);
      toasts.push('Exported Matlab (.mat)', { level: 'success' });
    } catch (e) {
      toasts.push(`Matlab export failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
    } finally {
      busy = false;
    }
  }

  /**
   * Export CSV: one raw-values file per data kind present (time / freq / tf),
   * mirroring the "save the whole dataset" theme of Save Dataset + Matlab.
   * Built in pure TS to reproduce pydvma export_to_csv exactly.
   */
  async function exportCsv(): Promise<void> {
    if (!exporter) return;
    busy = true;
    try {
      const files = buildCsvFiles(exporter, dataBaseName());
      if (files.length === 0) {
        toasts.push('No data to export yet.', { level: 'info' });
        return;
      }
      const enc = new TextEncoder();
      for (const f of files) await write(f.name, enc.encode(f.text));
      const kinds = files.map((f) => f.name.replace(/^.*-(\w+)\.csv$/, '$1')).join(' + ');
      toasts.push(`Exported CSV (${kinds})`, { level: 'success' });
    } catch (e) {
      toasts.push(`CSV export failed: ${e instanceof Error ? e.message : e}`, { level: 'error' });
    } finally {
      busy = false;
    }
  }
</script>

<section class="ctx-card card-controls" aria-label="Export stage controls">
  <div class="ctx-name"><span class="cn-t">Export</span><span class="cn-s">save</span></div>
  <div class="ctx-body">
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">dataset</span>
        <div class="grp-ctl">
          <button class="btn" onclick={onsave}>Save Dataset</button>
          <button
            class="btn"
            disabled={busy || !hasData || !exporter}
            title={exporter
              ? 'Export all data as a Matlab .mat file'
              : 'Data export unavailable — engine not connected'}
            onclick={exportMatlab}>Export Matlab</button>
          <button
            class="btn"
            disabled={busy || !hasData || !exporter}
            title={exporter
              ? 'Export data as CSV (one file per kind: time / freq / tf)'
              : 'Data export unavailable — engine not connected'}
            onclick={exportCsv}>Export CSV</button>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">figure format</span>
        <div class="grp-ctl">
          <label class="chk"><input type="checkbox" bind:checked={png} aria-label="PNG" /> PNG</label>
          <label class="chk"><input type="checkbox" bind:checked={pdf} aria-label="PDF" /> PDF</label>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">background</span>
        <div class="grp-ctl">
          <label class="chk"><input type="radio" name="figbg" value="white" bind:group={bg} /> white</label>
          <label class="chk"><input type="radio" name="figbg" value="transparent" bind:group={bg} /> transparent</label>
          <label class="chk"><input type="radio" name="figbg" value="dark" bind:group={bg} /> dark</label>
        </div>
      </div>
      <div class="grp">
        <span class="grp-lab">filename</span>
        <div class="grp-ctl">
          <input type="text" bind:value={filename} style="width:210px" aria-label="figure filename" />
        </div>
      </div>
    </div>
    <div class="ctx-row">
      <div class="grp">
        <span class="grp-lab">session</span>
        <div class="grp-ctl">
          <label class="switch">
            <input type="checkbox" bind:checked={autosaveEnabled} onchange={onAutosaveToggle} aria-label="autosave" />
            Autosave to browser storage after every change
          </label>
        </div>
      </div>
    </div>
  </div>
  <div class="ctx-primary">
    <!-- The execute verb — the top bar's "Save Figure" opens this stage; this
         button writes the ticked formats. Distinct label avoids two identical
         "Save Figure" buttons on screen at once. -->
    <button class="btn indigo" disabled={busy || !hasData} onclick={saveFigure}>Export</button>
  </div>
</section>

<style>
  .chk {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--text);
    cursor: pointer;
    white-space: nowrap;
  }
  .chk input {
    margin: 0;
    accent-color: var(--indigo);
    cursor: pointer;
  }
</style>
