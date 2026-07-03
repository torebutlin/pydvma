# pydvma Stage 2 — Plan 1 of 3: the Analysis App

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `webui/` (Svelte 5 + TypeScript + Vite) and ship the *analysis
mode* of the bench GUI from `dev/2026-07-03-stage2-gui-design.md`: open
`.dvma` / legacy `.npy` / `.mat` files, navigate sets × channels with tri-state
matrix selection, compute FFT / PSD / CSD / TF / sonogram via pydvma running in a
pyodide worker, interact with plots (zoom, legend, plot types incl. Bode and
square Nyquist), export figures (white / transparent / dark), working directory +
autosave, deployed to Pages at `…/pydvma/app/`.

**Milestone map (Stage 2 = 3 plans):**

| Plan | Scope | Ships |
|---|---|---|
| **1 (this)** | webui foundation + file analysis | no-install browser analysis app |
| 2 | WebAudioSource, monitor, Setup/Acquire cards, output gen, mode fitting, sono damping fit, calibration dialog, Best Match | full soundcard logger |
| 3 | `pydvma serve` bridge, capability metadata, NI verify (Windows), Qt retirement gate | lab deployment |

**Executor annotations:** every task carries `Executor: opus` or `Executor: sonnet`
— dispatch the task subagent with that model. The orchestrator (Fable session)
reviews after each task and runs the Task 16 gate itself.

**Architecture:** Binding requirements from spec §11: all maths runs in pydvma
inside a **pyodide web worker** (never reimplemented in JS); **JS owns the
`.dvma` model** (zip + manifest + pickle-free npy, read/written natively);
plot/view state lives in **explicit serialisable stores** (no mode strings);
the app shell never gates on pyodide boot (compute actions queue with a visible
"engine loading" state).

**Decision — plot layer is custom Svelte/SVG, not Plotly** (resolves the spec §11
spike): the requirement list — draggable legend + corner presets, square-aspect
Nyquist with linked ranges, white/transparent/dark export at print DPI, per-line
tri-state alpha, coherence twin axis, live-slider recompute — fights Plotly's
abstractions at nearly every point, while the round-2 mockup already renders
credible axes/lines in plain SVG and the bundle stays tiny. Revisit trigger:
Task 7's perf step (24 lines × 200k samples must pan smoothly after min-max
decimation). Recorded here so the spec's "spike" line is discharged.

**Markup convention:** `dev/mockups/round2-bench.html` is the checked-in visual
reference. UI tasks port its structure and design tokens into components; this
plan specifies the *contracts* (props / stores / events) and behavioural tests,
and gives complete code for all logic. Where a step says "port from the mockup",
open that file and translate the corresponding section — do not invent new
visual design.

**Tech stack:** Svelte 5, TypeScript, Vite, vitest, Playwright, fflate (zip),
idb-keyval (handle persistence), jsPDF + svg2pdf.js (PDF export), pyodide
(vendored into `public/pyodide/`), pydvma wheel built from this repo.

**Constraints (hold at every task):**
- Work directly on `master` — `webui/` is additive; nothing under `pydvma/` or
  `tests/` changes except where a task explicitly says so.
- Python suite stays green: `python -m pytest tests/ -q` (205 passed / 4 skipped
  baseline) before any commit that touches python files.
- `cd webui && npx vitest run` green before every commit from Task 2 onward.
- Commit per task (or per step where marked). Never push — pushing is the user's call.
- Environment: Mac, `/opt/anaconda3/bin/python3`, node ≥ 20 (`node --version` to check).

---

## File structure (end state of this plan)

```
webui/
  package.json  vite.config.ts  tsconfig.json  playwright.config.ts
  index.html
  public/
    pyodide/            # vendored pyodide runtime (gitignored, fetched by script/CI)
    pypi/               # pydvma + peakutils wheels (gitignored, built by script/CI)
  scripts/
    fetch-pyodide.sh    # downloads pyodide release into public/pyodide
    build-wheels.sh     # builds pydvma wheel + fetches peakutils into public/pypi
  src/
    app.css             # design tokens ported from the mockups
    App.svelte          # bench shell composition
    main.ts
    lib/
      codec/npy.ts              # .npy parse/serialise
      codec/dvma.ts             # .dvma container read/write (fflate + manifest)
      model/dataset.ts          # DvmaDataset/DvmaItem types + helpers
      stores/selection.ts       # sets×channels tri-state matrix store
      stores/viewstate.ts       # per-view axes/history/plot-type store
      stores/stages.ts          # ribbon stages + capability gating
      stores/engine.ts          # pyodide boot status + queued actions
      plot/scales.ts            # nice ticks, linear scale helpers
      plot/decimate.ts          # min-max per-pixel-column decimation
      plot/build.ts             # PlotModel -> SVG path data (pure)
      plot/zoom.ts              # rubber-band/pan/history controller (pure)
      analysis/resolution.ts    # coupled N_fft <-> N_frames <-> frame length
      analysis/actions.ts       # card state -> worker calls -> dataset updates
      worker/engine.worker.ts   # pyodide worker (protocol handler)
      worker/client.ts          # typed request/response wrapper
      worker/glue.py            # python-side helpers (imported as raw string)
      files/sniff.ts            # zip / npy / mat detection
      files/workdir.ts          # File System Access + fallback
      files/autosave.ts         # debounced autosave + restore
      export/figure.ts          # SVG -> PNG/PDF with bg modes
    components/
      Header.svelte  Ribbon.svelte  ContextCard.svelte
      Tray.svelte  TrayCard.svelte  NarrowRail.svelte
      PlotSurface.svelte  ZoomToolbar.svelte  Legend.svelte
      cards/TimeCard.svelte  cards/FrequencyCard.svelte
      cards/TFCard.svelte    cards/SonoCard.svelte  cards/ExportCard.svelte
  tests/                # vitest unit tests (mirror src/lib paths)
    fixtures/           # small checked-in fixtures (.npy, .dvma)
  e2e/                  # Playwright specs
dev/make_webui_fixture.py       # generates tests/fixtures/impulse.dvma
.github/workflows/webui.yml     # NEW: vitest + playwright CI
.github/workflows/docs.yml      # MODIFIED (Task 15): deploy webui build to site/app
```

---

## Task 1: Scaffold `webui/`

**Executor: sonnet**
**Files:** create `webui/` via Vite scaffold; add `webui/src/app.css`, folder tree, `.gitignore` entries.

- [ ] **Step 1: Preflight**

```bash
node --version   # expect >= v20; if missing, stop and report
python -m pytest tests/ -q   # confirm baseline green before starting
```

- [ ] **Step 2: Scaffold and install**

```bash
cd /Users/tore/Documents/GitHub/pydvma
npm create vite@latest webui -- --template svelte-ts
cd webui
npm install
npm install fflate idb-keyval jspdf svg2pdf.js
npm install -D vitest @playwright/test
npx playwright install chromium
```

- [ ] **Step 3: Configure**

Replace `webui/vite.config.ts`:

```ts
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  base: './',            // app is served from /pydvma/app/ — relative assets
  build: { target: 'es2022' },
  worker: { format: 'es' },
});
```

Add to `webui/package.json` scripts:

```json
"test": "vitest run",
"test:watch": "vitest",
"test:e2e": "playwright test"
```

Create `webui/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { include: ['tests/**/*.test.ts'], environment: 'node' } });
```

- [ ] **Step 4: Design tokens**

Replace `webui/src/app.css` with the token block ported from
`dev/mockups/round2-bench.html` (`:root` custom properties: `--bg:#f4f5f7`,
`--surface:#fff`, `--border:#e3e6eb`, `--text:#17203a`, `--muted:#66708a`,
radius 10px, the shadow, the action colours `--green:#16a34a`,
`--indigo:#4f46e5`, and the 12-colour line palette as `--line-0`…`--line-11`)
plus the font stacks (system-ui body; ui-monospace numerics). Copy values
verbatim from the mockup's CSS.

- [ ] **Step 5: Skeleton dirs + smoke test**

```bash
mkdir -p src/lib/{codec,model,stores,plot,analysis,worker,files,export} src/components/cards tests/fixtures e2e scripts public/pypi
```

Create `webui/tests/smoke.test.ts`:

```ts
import { expect, test } from 'vitest';
test('vitest runs', () => { expect(1 + 1).toBe(2); });
```

Append to repo-root `.gitignore`:

```
webui/node_modules/
webui/dist/
webui/public/pyodide/
webui/public/pypi/
webui/test-results/
webui/playwright-report/
```

- [ ] **Step 6: Verify + commit**

```bash
cd webui && npx vitest run && npm run build
cd .. && git add webui .gitignore && git commit -m "feat(webui): scaffold Svelte+TS+Vite app with design tokens"
```

Expected: vitest 1 passed; `dist/` builds clean.

---

## Task 2: `.npy` codec

**Executor: opus**
**Files:** create `webui/src/lib/codec/npy.ts`, `webui/tests/codec/npy.test.ts`, fixtures.

- [ ] **Step 1: Generate python fixtures (ground truth)**

```bash
python - <<'EOF'
import numpy as np, os
os.makedirs('webui/tests/fixtures', exist_ok=True)
np.save('webui/tests/fixtures/f8_2x3.npy', (np.arange(6).reshape(2, 3) * 1.5))
np.save('webui/tests/fixtures/c16_4.npy', np.array([1+2j, -0.5+0j, 3.25-4j, 0+1j]))
np.save('webui/tests/fixtures/i8_3.npy', np.array([1, -7, 2**40]))
print('fixtures written')
EOF
git add -f webui/tests/fixtures/*.npy
```

- [ ] **Step 2: Write failing tests**

Create `webui/tests/codec/npy.test.ts`:

```ts
import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { parseNpy, serializeNpy } from '../../src/lib/codec/npy';

const fix = (n: string) => new Uint8Array(readFileSync(`tests/fixtures/${n}`));

test('parses float64 2x3', () => {
  const a = parseNpy(fix('f8_2x3.npy'));
  expect(a.shape).toEqual([2, 3]);
  expect(a.isComplex).toBe(false);
  expect(Array.from(a.data as Float64Array)).toEqual([0, 1.5, 3, 4.5, 6, 7.5]);
});

test('parses complex128 interleaved', () => {
  const a = parseNpy(fix('c16_4.npy'));
  expect(a.shape).toEqual([4]);
  expect(a.isComplex).toBe(true);
  const d = a.data as Float64Array;           // [re0, im0, re1, im1, ...]
  expect(d[0]).toBe(1); expect(d[1]).toBe(2); expect(d[5]).toBe(-4 * 0 - 0 + 0 || d[5]);
  expect(d[4]).toBe(3.25); expect(d[5]).toBe(-4);
});

test('parses int64 losslessly up to 2^53', () => {
  const a = parseNpy(fix('i8_3.npy'));
  expect(Array.from(a.data as Float64Array)).toEqual([1, -7, 2 ** 40]);
});

test('round-trips float64 and complex128', () => {
  for (const name of ['f8_2x3.npy', 'c16_4.npy']) {
    const a = parseNpy(fix(name));
    const b = parseNpy(serializeNpy(a));
    expect(b.shape).toEqual(a.shape);
    expect(Array.from(b.data as Float64Array)).toEqual(Array.from(a.data as Float64Array));
  }
});

test('rejects fortran order', () => {
  const a = parseNpy(fix('f8_2x3.npy'));
  const bytes = serializeNpy(a);
  const txt = new TextDecoder().decode(bytes.slice(0, 128)).replace('False', 'True ');
  const forged = new Uint8Array(bytes); forged.set(new TextEncoder().encode(txt), 0);
  expect(() => parseNpy(forged)).toThrow(/fortran/i);
});
```

Run: `cd webui && npx vitest run tests/codec` — expected: FAIL (module missing).

- [ ] **Step 3: Implement `npy.ts`**

```ts
// .npy v1/v2 codec — the subset pydvma's .dvma containers use.
// Complex arrays are exposed interleaved [re, im, ...] with isComplex=true.
export interface NpyArray {
  shape: number[];
  isComplex: boolean;
  data: Float64Array | Float32Array | Uint8Array;
}

const MAGIC = [0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59];

export function parseNpy(bytes: Uint8Array): NpyArray {
  for (let i = 0; i < 6; i++) if (bytes[i] !== MAGIC[i]) throw new Error('not a .npy file');
  const major = bytes[6];
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLen = major >= 2 ? view.getUint32(8, true) : view.getUint16(8, true);
  const dataStart = (major >= 2 ? 12 : 10) + headerLen;
  const header = new TextDecoder('ascii').decode(bytes.subarray(major >= 2 ? 12 : 10, dataStart));

  const descr = /'descr':\s*'([^']+)'/.exec(header)?.[1];
  const fortran = /'fortran_order':\s*(True|False)/.exec(header)?.[1];
  const shapeTxt = /'shape':\s*\(([^)]*)\)/.exec(header)?.[1];
  if (!descr || !fortran || shapeTxt === undefined) throw new Error(`bad npy header: ${header}`);
  if (fortran === 'True') throw new Error('fortran_order arrays are not supported');
  const shape = shapeTxt.split(',').map(s => s.trim()).filter(Boolean).map(Number);
  const count = shape.reduce((a, b) => a * b, 1);

  // slice() copies -> result buffers are always 8-byte aligned
  const raw = bytes.slice(dataStart);
  switch (descr) {
    case '<f8': return { shape, isComplex: false, data: new Float64Array(raw.buffer, 0, count) };
    case '<f4': return { shape, isComplex: false, data: new Float32Array(raw.buffer, 0, count) };
    case '<c16': return { shape, isComplex: true, data: new Float64Array(raw.buffer, 0, count * 2) };
    case '|b1': return { shape, isComplex: false, data: raw.subarray(0, count) };
    case '<i8': {
      const big = new BigInt64Array(raw.buffer, 0, count);
      const out = new Float64Array(count);
      for (let i = 0; i < count; i++) out[i] = Number(big[i]);
      return { shape, isComplex: false, data: out };
    }
    case '<i4': {
      const ints = new Int32Array(raw.buffer, 0, count);
      return { shape, isComplex: false, data: Float64Array.from(ints) };
    }
    default: throw new Error(`unsupported dtype ${descr}`);
  }
}

export function serializeNpy(a: NpyArray): Uint8Array {
  const descr = a.isComplex ? '<c16' : a.data instanceof Float32Array ? '<f4'
    : a.data instanceof Uint8Array ? '|b1' : '<f8';
  const shape = a.shape.length === 1 ? `(${a.shape[0]},)` : `(${a.shape.join(', ')})`;
  let header = `{'descr': '${descr}', 'fortran_order': False, 'shape': ${shape}, }`;
  const unpadded = 10 + header.length + 1;
  header = header + ' '.repeat((64 - (unpadded % 64)) % 64) + '\n';

  const body = a.data instanceof Uint8Array
    ? a.data
    : new Uint8Array(a.data.buffer, a.data.byteOffset, a.data.byteLength);
  const out = new Uint8Array(10 + header.length + body.byteLength);
  out.set(MAGIC, 0); out[6] = 1; out[7] = 0;
  new DataView(out.buffer).setUint16(8, header.length, true);
  out.set(new TextEncoder().encode(header), 10);
  out.set(body, 10 + header.length);
  return out;
}
```

- [ ] **Step 4: Run tests, fix, commit**

```bash
cd webui && npx vitest run tests/codec    # expected: all PASS
cd .. && git add webui/src/lib/codec/npy.ts webui/tests
git commit -m "feat(webui): .npy codec (f8/f4/i4/i8/c16/b1, v1+v2 headers)"
```

---

## Task 3: `.dvma` container reader/writer + reference fixture

**Executor: opus**
**Files:** create `dev/make_webui_fixture.py`, `webui/src/lib/model/dataset.ts`,
`webui/src/lib/codec/dvma.ts`, `webui/tests/codec/dvma.test.ts`.

The manifest schema is defined by `pydvma/container.py` (format `dvma-dataset`,
`format_version` 1, tagged scalar encodings `__uuid__` / `__datetime__` /
`__array__`). Read that file before implementing; the TS side mirrors it.

- [ ] **Step 1: Fixture generator**

Create `dev/make_webui_fixture.py`:

```python
# -*- coding: utf-8 -*-
"""Generate webui/tests/fixtures/impulse.dvma — a small real container
written by pydvma itself, used as ground truth by the webui codec tests.
Run from the repo root: python dev/make_webui_fixture.py"""
import os
import pydvma as dvma

data = dvma.create_test_impulse_data(noise_level=0)
data.time_data_list[0].test_name = 'webui fixture'
data.time_data_list[0].units = ['N', 'm/s']
data.calculate_fft_set()
data.calculate_tf_set(ch_in=0)
out = os.path.join('webui', 'tests', 'fixtures', 'impulse.dvma')
data.save_data(filename=out, overwrite_without_prompt=True)
print('wrote', out)
```

```bash
python dev/make_webui_fixture.py
git add -f webui/tests/fixtures/impulse.dvma dev/make_webui_fixture.py
```

- [ ] **Step 2: Types**

Create `webui/src/lib/model/dataset.ts`:

```ts
import type { NpyArray } from '../codec/npy';

export type DataKind = 'TimeData' | 'FreqData' | 'CrossSpecData' | 'TfData'
  | 'SonoData' | 'ModalData' | 'MetaData';

export interface DvmaItem {
  kind: DataKind;
  arrays: Record<string, NpyArray>;          // e.g. time_axis, time_data
  meta: Record<string, unknown>;             // decoded tagged values
  settings: Record<string, unknown> | null;
}

export interface DvmaDataset {
  formatVersion: number;
  pydvmaVersion: string;
  items: DvmaItem[];
}

/** number of channels in a TimeData/FreqData/TfData item (2nd dim, or 1) */
export function itemChannels(item: DvmaItem): number {
  const arr = item.arrays.time_data ?? item.arrays.freq_data ?? item.arrays.tf_data;
  return arr && arr.shape.length > 1 ? arr.shape[1] : 1;
}
```

- [ ] **Step 3: Failing tests**

Create `webui/tests/codec/dvma.test.ts`:

```ts
import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { readDvma, writeDvma } from '../../src/lib/codec/dvma';
import { itemChannels } from '../../src/lib/model/dataset';

const bytes = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));

test('reads the pydvma-written fixture', () => {
  const ds = readDvma(bytes);
  expect(ds.formatVersion).toBe(1);
  const kinds = ds.items.map(i => i.kind);
  expect(kinds).toContain('TimeData');
  expect(kinds).toContain('TfData');
  const td = ds.items.find(i => i.kind === 'TimeData')!;
  expect(td.meta.test_name).toBe('webui fixture');
  expect(td.meta.units).toEqual(['N', 'm/s']);
  expect(itemChannels(td)).toBe(2);
  expect(td.arrays.time_axis.shape[0]).toBe(td.arrays.time_data.shape[0]);
  const tf = ds.items.find(i => i.kind === 'TfData')!;
  expect(tf.arrays.tf_data.isComplex).toBe(true);
});

test('write -> read round trip preserves arrays and meta', () => {
  const ds = readDvma(bytes);
  const ds2 = readDvma(writeDvma(ds));
  expect(ds2.items.length).toBe(ds.items.length);
  const a = ds.items[0].arrays.time_data.data as Float64Array;
  const b = ds2.items[0].arrays.time_data.data as Float64Array;
  expect(Array.from(b.subarray(0, 16))).toEqual(Array.from(a.subarray(0, 16)));
  expect(ds2.items[0].meta.units).toEqual(ds.items[0].meta.units);
});
```

Run: `npx vitest run tests/codec/dvma.test.ts` — expected FAIL.

- [ ] **Step 4: Implement `dvma.ts`**

```ts
import { unzipSync, zipSync } from 'fflate';
import { parseNpy, serializeNpy, type NpyArray } from './npy';
import type { DvmaDataset, DvmaItem } from '../model/dataset';

// tagged-value decoding mirrors pydvma/container.py _encode_value/_decode_value
function decodeValue(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(decodeValue);
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('__uuid__' in o) return o.__uuid__;             // keep as string
    if ('__datetime__' in o) return o.__datetime__;     // keep as ISO string
    if ('__array__' in o) return o.__array__;           // small numeric list
  }
  return v;
}

export function readDvma(bytes: Uint8Array): DvmaDataset {
  const files = unzipSync(bytes);
  const manifestRaw = files['manifest.json'];
  if (!manifestRaw) throw new Error('no manifest.json — not a .dvma container');
  const manifest = JSON.parse(new TextDecoder().decode(manifestRaw));
  if (manifest.format !== 'dvma-dataset') throw new Error(`unexpected format ${manifest.format}`);
  const items: DvmaItem[] = manifest.items.map((entry: any) => {
    const arrays: Record<string, NpyArray> = {};
    for (const [field, member] of Object.entries<string>(entry.arrays)) {
      arrays[field] = parseNpy(files[member]);
    }
    const meta: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(entry.meta ?? {})) meta[k] = decodeValue(v);
    return { kind: entry.kind, arrays, meta, settings: entry.settings ?? null };
  });
  return { formatVersion: manifest.format_version, pydvmaVersion: manifest.pydvma_version, items };
}

export function writeDvma(ds: DvmaDataset): Uint8Array {
  const files: Record<string, Uint8Array> = {};
  const manifest = {
    format: 'dvma-dataset', format_version: 1,
    pydvma_version: ds.pydvmaVersion, storage: 'npy',
    items: [] as unknown[],
  };
  ds.items.forEach((item, index) => {
    const arrays: Record<string, string> = {};
    for (const [field, arr] of Object.entries(item.arrays)) {
      const member = `arrays/${String(index).padStart(4, '0')}_${field}.npy`;
      files[member] = serializeNpy(arr);
      arrays[field] = member;
    }
    manifest.items.push({ kind: item.kind, arrays, meta: item.meta, settings: item.settings });
  });
  files['manifest.json'] = new TextEncoder().encode(JSON.stringify(manifest, null, 1));
  return zipSync(files, { level: 6 });
}
```

Note: `writeDvma` re-encodes `meta` verbatim (already-decoded values are plain
JSON — uuid/datetime tags are only needed by the *python* reader, and files
saved from the browser round-trip through python via `load` which tolerates
plain strings for those fields; if Task 16's cross-check with python fails on
this, add an `encodeValue` that re-tags string uuids/timestamps — the failing
test will say so).

- [ ] **Step 5: Cross-check with python, run tests, commit**

```bash
cd webui && npx vitest run tests/codec && cd ..
```

Then the python cross-check: add a temporary vitest test (or a small node
script) that writes `tests/fixtures/roundtrip.dvma` via
`readDvma(fixture) → writeDvma`, then:

```bash
python -c "
import pydvma as dvma
d = dvma.load_data(filename='webui/tests/fixtures/roundtrip.dvma')
assert len(d.time_data_list) == 1 and len(d.tf_data_list) == 1
print('python reads JS-written dvma OK')
"
rm webui/tests/fixtures/roundtrip.dvma
git add webui/src/lib && git commit -m "feat(webui): native .dvma read/write (fflate + manifest)"
```

Expected: `python reads JS-written dvma OK`. If it raises on uuid/datetime
decoding, implement the `encodeValue` re-tagging noted in Step 4 and re-run.

---

## Task 4: Selection store (sets × channels tri-state matrix)

**Executor: opus**
**Files:** create `webui/src/lib/stores/selection.ts`, `webui/tests/stores/selection.test.ts`.

Behaviour from spec §3: tri-state on/fade/off per line; card-header click cycles
a whole set; channel chip cycles a channel index across all sets; All/None/Solo;
`‹ ›` steppers; editable labels; a set with all lines off is "struck through"
and omitted from the legend.

- [ ] **Step 1: Failing tests**

```ts
import { get } from 'svelte/store';
import { expect, test, beforeEach } from 'vitest';
import { createSelection } from '../../src/lib/stores/selection';

let sel: ReturnType<typeof createSelection>;
beforeEach(() => {
  sel = createSelection();
  sel.addSet({ name: 'set_0', nChannels: 2, durationS: 2, timestamp: 't0' });
  sel.addSet({ name: 'set_1', nChannels: 2, durationS: 2, timestamp: 't1' });
  sel.addSet({ name: 'set_2', nChannels: 8, durationS: 2, timestamp: 't2' });
});

test('lines default on; individual cycle on->fade->off->on', () => {
  expect(get(sel.state)('0:1')).toBe('on');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('fade');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('off');
  sel.cycleLine(0, 1); expect(get(sel.state)('0:1')).toBe('on');
});

test('set cycle drives every channel in the set together', () => {
  sel.cycleSet(2);
  for (let ch = 0; ch < 8; ch++) expect(get(sel.state)(`2:${ch}`)).toBe('fade');
});

test('mixed set cycles to uniform on first', () => {
  sel.cycleLine(1, 0);                       // set_1 now mixed (fade, on)
  sel.cycleSet(1);
  expect(get(sel.state)('1:0')).toBe('on');
  expect(get(sel.state)('1:1')).toBe('on');
});

test('channel cycle applies across all sets, including collapsed', () => {
  sel.cycleChannel(1);
  expect(get(sel.state)('0:1')).toBe('fade');
  expect(get(sel.state)('1:1')).toBe('fade');
  expect(get(sel.state)('2:1')).toBe('fade');
  expect(get(sel.state)('0:0')).toBe('on');  // other channels untouched
});

test('solo isolates one set; steppers move the solo', () => {
  sel.solo(1);
  expect(get(sel.state)('1:0')).toBe('on');
  expect(get(sel.state)('0:0')).toBe('off');
  sel.step(1);                                // solo moves to set_2
  expect(get(sel.state)('2:0')).toBe('on');
  expect(get(sel.state)('1:0')).toBe('off');
});

test('allOff flags a fully-off set (legend omission + strikethrough)', () => {
  sel.cycleSet(0); sel.cycleSet(0);           // on -> fade -> off
  expect(get(sel.setsView)[0].allOff).toBe(true);
  expect(get(sel.legendEntries).some(e => e.set === 0)).toBe(false);
  expect(get(sel.legendEntries).some(e => e.set === 1)).toBe(true);
});

test('rename propagates to legend labels', () => {
  sel.rename(0, 'hammer test');
  expect(get(sel.legendEntries)[0].label).toBe('hammer test · ch_0');
});
```

Run to see FAIL.

- [ ] **Step 2: Implement**

```ts
import { derived, writable, get } from 'svelte/store';

export type TriState = 'on' | 'fade' | 'off';
const NEXT: Record<TriState, TriState> = { on: 'fade', fade: 'off', off: 'on' };
export const LINE_PALETTE = [
  '#2563eb', '#dc2626', '#059669', '#d97706', '#7c3aed', '#0891b2',
  '#be185d', '#4d7c0f', '#9333ea', '#0e7490', '#b91c1c', '#15803d'];

export interface SetEntry { name: string; nChannels: number; durationS: number; timestamp: string; }
export interface SetView extends SetEntry { index: number; allOff: boolean; collapsed: boolean; }
export interface LegendEntry { set: number; ch: number; label: string; color: string; state: TriState; }

export function createSelection() {
  const sets = writable<SetEntry[]>([]);
  const states = writable<Map<string, TriState>>(new Map());
  const collapsed = writable<Set<number>>(new Set());
  const highlight = writable<number>(0);

  const key = (s: number, c: number) => `${s}:${c}`;
  const stateOf = (m: Map<string, TriState>, s: number, c: number) => m.get(key(s, c)) ?? 'on';

  function mutate(fn: (m: Map<string, TriState>) => void) {
    states.update(m => { const n = new Map(m); fn(n); return n; });
  }

  return {
    sets, collapsed, highlight,
    /** lookup function store: $state('0:1') -> TriState */
    state: derived(states, m => (k: string) => {
      const [s, c] = k.split(':').map(Number); return stateOf(m, s, c);
    }),

    addSet(entry: SetEntry) {
      sets.update(l => [...l, entry]);
      if (entry.nChannels > 4) collapsed.update(c => new Set(c).add(get(sets).length - 1));
    },
    rename(setIdx: number, name: string) {
      sets.update(l => l.map((s, i) => (i === setIdx ? { ...s, name } : s)));
    },
    cycleLine(s: number, c: number) {
      mutate(m => m.set(key(s, c), NEXT[stateOf(m, s, c)]));
    },
    cycleSet(s: number) {
      const list = get(sets); if (!list[s]) return;
      mutate(m => {
        const vals = Array.from({ length: list[s].nChannels }, (_, c) => stateOf(m, s, c));
        const uniform = vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';   // mixed -> on first
        for (let c = 0; c < list[s].nChannels; c++) m.set(key(s, c), target);
      });
    },
    cycleChannel(ch: number) {
      const list = get(sets);
      mutate(m => {
        const vals = list.flatMap((set, s) => (ch < set.nChannels ? [stateOf(m, s, ch)] : []));
        const uniform = vals.length > 0 && vals.every(v => v === vals[0]);
        const target: TriState = uniform ? NEXT[vals[0]] : 'on';
        list.forEach((set, s) => { if (ch < set.nChannels) m.set(key(s, ch), target); });
      });
    },
    all() { mutate(m => m.clear()); },
    none() {
      const list = get(sets);
      mutate(m => list.forEach((set, s) => {
        for (let c = 0; c < set.nChannels; c++) m.set(key(s, c), 'off');
      }));
    },
    solo(s: number) {
      const list = get(sets); highlight.set(s);
      mutate(m => list.forEach((set, i) => {
        for (let c = 0; c < set.nChannels; c++) m.set(key(i, c), i === s ? 'on' : 'off');
      }));
    },
    step(dir: 1 | -1) {
      const n = get(sets).length; if (!n) return;
      const next = ((get(highlight) + dir) % n + n) % n;
      this.solo(next);
    },
    toggleCollapse(s: number) {
      collapsed.update(c => { const n = new Set(c); n.has(s) ? n.delete(s) : n.add(s); return n; });
    },

    setsView: derived([sets, states, collapsed], ([$sets, $states, $collapsed]) =>
      $sets.map((set, index): SetView => ({
        ...set, index, collapsed: $collapsed.has(index),
        allOff: Array.from({ length: set.nChannels }, (_, c) => stateOf($states, index, c))
          .every(v => v === 'off'),
      }))),

    legendEntries: derived([sets, states], ([$sets, $states]) => {
      const out: LegendEntry[] = [];
      $sets.forEach((set, s) => {
        const allOff = Array.from({ length: set.nChannels }, (_, c) => stateOf($states, s, c))
          .every(v => v === 'off');
        if (allOff) return;                                    // spec §3: omit from legend
        for (let c = 0; c < set.nChannels; c++) {
          const st = stateOf($states, s, c);
          if (st === 'off') continue;
          out.push({ set: s, ch: c, state: st,
            label: `${set.name} · ch_${c}`,
            color: LINE_PALETTE[(s * 2 + c) % LINE_PALETTE.length] });
        }
      });
      return out;
    }),
  };
}
```

- [ ] **Step 3: Run tests, commit**

```bash
cd webui && npx vitest run tests/stores && cd ..
git add webui && git commit -m "feat(webui): tri-state selection store with matrix batch ops"
```

---

## Task 5: View-state store + coupled resolution control

**Executor: opus**
**Files:** create `webui/src/lib/stores/viewstate.ts`,
`webui/src/lib/analysis/resolution.ts`, tests for both.

- [ ] **Step 1: Failing tests — resolution coupling**

`webui/tests/analysis/resolution.test.ts`:

```ts
import { expect, test } from 'vitest';
import { fromNFrames, fromFrameLength, fromNFft } from '../../src/lib/analysis/resolution';

// ground truth from the Qt GUI: 30 s capture, N=10 -> "Frame length = 5.45 s"
test('nFrames -> frame length matches Qt formula (overlap 0.5)', () => {
  const r = fromNFrames(10, 30, 44100);
  expect(r.frameLengthS).toBeCloseTo(5.4545, 3);
  expect(r.nFft).toBe(Math.round(5.4545454 * 44100));
  expect(r.dF).toBeCloseTo(1 / r.frameLengthS, 6);
});

test('round trips: frameLength -> nFrames -> frameLength', () => {
  const a = fromFrameLength(1.0, 30, 44100);
  const b = fromNFrames(a.nFrames, 30, 44100);
  expect(b.frameLengthS).toBeCloseTo(a.frameLengthS, 1);
});

test('nFft entry snaps the other two consistently', () => {
  const r = fromNFft(44100, 30, 44100);       // 1 s frames
  expect(r.frameLengthS).toBeCloseTo(1, 6);
  expect(r.nFrames).toBeGreaterThan(1);
});

test('clamps nFrames to [1, samples]', () => {
  expect(fromNFrames(0, 30, 44100).nFrames).toBe(1);
});
```

- [ ] **Step 2: Implement `resolution.ts`**

```ts
// Coupled resolution control (spec §5): N_frames <-> frame length <-> N_fft.
// Formula matches the Qt GUI with 50% overlap:
//   frameLength = duration / (nFrames*(1-overlap) + overlap)
const OVERLAP = 0.5;

export interface Resolution { nFrames: number; frameLengthS: number; nFft: number; dF: number; }

function finish(nFrames: number, durationS: number, fs: number): Resolution {
  nFrames = Math.max(1, Math.round(nFrames));
  const frameLengthS = durationS / (nFrames * (1 - OVERLAP) + OVERLAP);
  const nFft = Math.max(2, Math.round(frameLengthS * fs));
  return { nFrames, frameLengthS, nFft, dF: fs / nFft };
}

export const fromNFrames = (n: number, durationS: number, fs: number) =>
  finish(n, durationS, fs);

export const fromFrameLength = (frameLengthS: number, durationS: number, fs: number) =>
  finish((durationS / Math.max(frameLengthS, 1 / fs) - OVERLAP) / (1 - OVERLAP), durationS, fs);

export const fromNFft = (nFft: number, durationS: number, fs: number) =>
  fromFrameLength(Math.max(2, Math.round(nFft)) / fs, durationS, fs);
```

- [ ] **Step 3: Failing tests — view state**

`webui/tests/stores/viewstate.test.ts`:

```ts
import { get } from 'svelte/store';
import { expect, test } from 'vitest';
import { createViewState } from '../../src/lib/stores/viewstate';

test('axis ranges are per-view and restored on return', () => {
  const vs = createViewState();
  vs.setRange('time', { x: [0, 0.5], y: [-1, 1] });
  vs.activate('tf');
  expect(get(vs.current).range.x).toBeNull();       // tf untouched
  vs.activate('time');
  expect(get(vs.current).range.x).toEqual([0, 0.5]);
});

test('zoom history: push/back/forward', () => {
  const vs = createViewState();
  vs.setRange('tf', { x: [0, 500], y: [-60, 40] });
  vs.setRange('tf', { x: [80, 120], y: [-30, 20] });
  vs.back('tf');
  expect(get(vs.current).range.x).toEqual([0, 500]);
  vs.forward('tf');
  expect(get(vs.current).range.x).toEqual([80, 120]);
});

test('frequency x-range is shared across the TF plot-type family', () => {
  const vs = createViewState();
  vs.activate('tf');
  vs.setRange('tf', { x: [100, 300], y: [-40, 10] });
  expect(get(vs.sharedFreqRange)).toEqual([100, 300]);   // feeds Nyquist fmin/fmax
});

test('state is serialisable and restorable (debuggability, spec §11)', () => {
  const vs = createViewState();
  vs.setRange('sono', { x: [0, 2], y: [0, 1500] });
  const snap = vs.serialize();
  const vs2 = createViewState();
  vs2.restore(JSON.parse(JSON.stringify(snap)));
  vs2.activate('sono');
  expect(get(vs2.current).range.x).toEqual([0, 2]);
});
```

- [ ] **Step 4: Implement `viewstate.ts`**

```ts
import { derived, writable, get } from 'svelte/store';

export type ViewId = 'time' | 'frequency' | 'tf' | 'sono';
export type TfPlotType = 'mag' | 'phase' | 'bode' | 'real' | 'imag' | 'nyquist';
export interface Range { x: [number, number] | null; y: [number, number] | null; }

export interface ViewSlice {
  range: Range;
  history: Range[]; future: Range[];
  plotType: TfPlotType;              // used by tf only; ignored elsewhere
  coherence: boolean;
  legend: { visible: boolean; x: number; y: number; preset: string | null };
}

const fresh = (): ViewSlice => ({
  range: { x: null, y: null }, history: [], future: [],
  plotType: 'mag', coherence: true,
  legend: { visible: true, x: 0.98, y: 0.02, preset: 'ne' },
});

export function createViewState() {
  const views = writable<Record<ViewId, ViewSlice>>({
    time: fresh(), frequency: fresh(), tf: fresh(), sono: fresh(),
  });
  const active = writable<ViewId>('time');

  const patch = (id: ViewId, fn: (v: ViewSlice) => ViewSlice) =>
    views.update(all => ({ ...all, [id]: fn(all[id]) }));

  return {
    active,
    current: derived([views, active], ([$v, $a]) => $v[$a]),
    sharedFreqRange: derived(views, $v => $v.tf.range.x ?? $v.frequency.range.x),

    activate(id: ViewId) { active.set(id); },
    setRange(id: ViewId, range: Range) {
      patch(id, v => ({ ...v, history: [...v.history, v.range], future: [], range }));
    },
    back(id: ViewId) {
      patch(id, v => {
        const prev = v.history.at(-1); if (!prev) return v;
        return { ...v, history: v.history.slice(0, -1), future: [v.range, ...v.future], range: prev };
      });
    },
    forward(id: ViewId) {
      patch(id, v => {
        const next = v.future[0]; if (!next) return v;
        return { ...v, future: v.future.slice(1), history: [...v.history, v.range], range: next };
      });
    },
    autoFit(id: ViewId) { this.setRange(id, { x: null, y: null }); }, // null = fit data
    setPlotType(t: TfPlotType) { patch(get(active), v => ({ ...v, plotType: t })); },
    setCoherence(on: boolean) { patch(get(active), v => ({ ...v, coherence: on })); },
    setLegend(id: ViewId, legend: ViewSlice['legend']) { patch(id, v => ({ ...v, legend })); },

    serialize() { return { views: get(views), active: get(active) }; },
    restore(snap: { views: Record<ViewId, ViewSlice>; active: ViewId }) {
      views.set(snap.views); active.set(snap.active);
    },
  };
}
```

- [ ] **Step 5: Run tests, commit**

```bash
cd webui && npx vitest run tests/stores tests/analysis && cd ..
git add webui && git commit -m "feat(webui): serialisable view-state store + coupled resolution control"
```

---

## Task 6: Plot rendering core (pure functions + PlotSurface)

**Executor: opus**
**Files:** create `webui/src/lib/plot/{scales,decimate,build}.ts`, tests,
`webui/src/components/PlotSurface.svelte`.

- [ ] **Step 1: Failing tests — scales + decimation**

`webui/tests/plot/scales.test.ts`:

```ts
import { expect, test } from 'vitest';
import { niceTicks } from '../../src/lib/plot/scales';

test('1-2-5 ticks over a simple domain', () => {
  expect(niceTicks(0, 500, 6)).toEqual([0, 100, 200, 300, 400, 500]);
});
test('handles negative and fractional domains', () => {
  const t = niceTicks(-0.25, 0.25, 5);
  expect(t[0]).toBeLessThanOrEqual(-0.2);
  expect(t).toContain(0);
});
```

`webui/tests/plot/decimate.test.ts`:

```ts
import { expect, test } from 'vitest';
import { minMaxDecimate } from '../../src/lib/plot/decimate';

test('preserves extremes: a single spike survives 100x decimation', () => {
  const n = 100_000;
  const y = new Float64Array(n).fill(0); y[54321] = 5;
  const pts = minMaxDecimate(y, 0, n - 1, 800);
  expect(Math.max(...pts.map(p => p[1]))).toBe(5);
  expect(pts.length).toBeLessThanOrEqual(800 * 2 + 2);
});

test('passes short arrays through untouched', () => {
  const y = Float64Array.from([1, 2, 3]);
  expect(minMaxDecimate(y, 0, 2, 800).length).toBe(3);
});
```

- [ ] **Step 2: Implement `scales.ts` and `decimate.ts`**

```ts
// scales.ts
export function niceTicks(min: number, max: number, target = 6): number[] {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, target);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const norm = step0 / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
  const start = Math.ceil(min / step) * step;
  const out: number[] = [];
  for (let v = start; v <= max + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}
export const scaleLinear = (d0: number, d1: number, r0: number, r1: number) =>
  (v: number) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
```

```ts
// decimate.ts — min-max per pixel column; keeps spikes visible.
export function minMaxDecimate(
  y: ArrayLike<number>, i0: number, i1: number, columns: number,
): Array<[number, number]> {
  const n = i1 - i0 + 1;
  if (n <= columns * 2) {
    return Array.from({ length: n }, (_, k) => [i0 + k, y[i0 + k]] as [number, number]);
  }
  const out: Array<[number, number]> = [];
  for (let c = 0; c < columns; c++) {
    const a = i0 + Math.floor((c * n) / columns);
    const b = i0 + Math.floor(((c + 1) * n) / columns) - 1;
    let lo = y[a], hi = y[a], loI = a, hiI = a;
    for (let i = a + 1; i <= b; i++) {
      if (y[i] < lo) { lo = y[i]; loI = i; }
      if (y[i] > hi) { hi = y[i]; hiI = i; }
    }
    out.push(loI <= hiI ? [loI, lo] : [hiI, hi]);
    if (loI !== hiI) out.push(loI <= hiI ? [hiI, hi] : [loI, lo]);
  }
  return out;
}
```

- [ ] **Step 3: `build.ts` — PlotModel → renderable paths**

```ts
import { niceTicks, scaleLinear } from './scales';
import { minMaxDecimate } from './decimate';

export interface PlotLine {
  x: ArrayLike<number>; y: ArrayLike<number>;
  color: string; opacity: number; width: number; dashed: boolean;
  yAxis: 'left' | 'right';                        // right = coherence
}
export interface PlotModel {
  lines: PlotLine[];
  xLabel: string; yLabel: string; y2Label?: string;
  squareAspect?: boolean;                          // Nyquist
  xRange: [number, number] | null; yRange: [number, number] | null;
  y2Range?: [number, number];
}
export interface BuiltPlot {
  xTicks: Array<{ v: number; px: number }>;
  yTicks: Array<{ v: number; px: number }>;
  y2Ticks: Array<{ v: number; px: number }>;
  paths: Array<{ d: string; color: string; opacity: number; width: number; dashed: boolean }>;
  xDomain: [number, number]; yDomain: [number, number];
}

function dataExtent(lines: PlotLine[], axis: 'x' | 'y', which: 'left' | 'right' | 'any')
  : [number, number] {
  let lo = Infinity, hi = -Infinity;
  for (const l of lines) {
    if (which !== 'any' && l.yAxis !== which) continue;
    const arr = axis === 'x' ? l.x : l.y;
    for (let i = 0; i < arr.length; i++) {
      const v = arr[i];
      if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    }
  }
  if (lo === Infinity) return [0, 1];
  if (lo === hi) return [lo - 1, hi + 1];
  return [lo, hi];
}

export function buildPlot(model: PlotModel, width: number, height: number): BuiltPlot {
  let xDomain = model.xRange ?? dataExtent(model.lines, 'x', 'any');
  let yDomain = model.yRange ?? dataExtent(model.lines.filter(l => l.yAxis === 'left'), 'y', 'left');

  if (model.squareAspect) {                        // spec §5: Nyquist square, fit data
    const xs = xDomain[1] - xDomain[0], ys = yDomain[1] - yDomain[0];
    const span = Math.max(xs, ys);
    const xc = (xDomain[0] + xDomain[1]) / 2, yc = (yDomain[0] + yDomain[1]) / 2;
    xDomain = [xc - span / 2, xc + span / 2];
    yDomain = [yc - span / 2, yc + span / 2];
  }

  const sx = scaleLinear(xDomain[0], xDomain[1], 0, width);
  const sy = scaleLinear(yDomain[0], yDomain[1], height, 0);
  const sy2 = scaleLinear(model.y2Range?.[0] ?? 0, model.y2Range?.[1] ?? 1, height, 0);

  const paths = model.lines.map(line => {
    const scaleY = line.yAxis === 'right' ? sy2 : sy;
    // find visible index window (x assumed monotonic for axis data; fall back to full)
    let i0 = 0, i1 = line.x.length - 1;
    const pts = minMaxDecimate(line.y, i0, i1, Math.max(64, Math.floor(width)));
    let d = '';
    for (const [i, v] of pts) {
      const X = sx(line.x[i]), Y = scaleY(v);
      if (!Number.isFinite(X) || !Number.isFinite(Y)) continue;
      d += (d ? 'L' : 'M') + X.toFixed(1) + ',' + Y.toFixed(1);
    }
    return { d, color: line.color, opacity: line.opacity, width: line.width, dashed: line.dashed };
  });

  return {
    paths, xDomain, yDomain,
    xTicks: niceTicks(xDomain[0], xDomain[1]).map(v => ({ v, px: sx(v) })),
    yTicks: niceTicks(yDomain[0], yDomain[1]).map(v => ({ v, px: sy(v) })),
    y2Ticks: model.y2Range ? niceTicks(model.y2Range[0], model.y2Range[1], 4).map(v => ({ v, px: sy2(v) })) : [],
  };
}
```

Add `webui/tests/plot/build.test.ts`:

```ts
import { expect, test } from 'vitest';
import { buildPlot } from '../../src/lib/plot/build';

const line = (yAxis: 'left' | 'right' = 'left') => ({
  x: Float64Array.from({ length: 1000 }, (_, i) => i / 500),
  y: Float64Array.from({ length: 1000 }, (_, i) => Math.sin(i / 50)),
  color: '#2563eb', opacity: 1, width: 1.6, dashed: false, yAxis,
});

test('builds paths and ticks', () => {
  const b = buildPlot({ lines: [line()], xLabel: 't', yLabel: 'V', xRange: null, yRange: null }, 800, 400);
  expect(b.paths[0].d.startsWith('M')).toBe(true);
  expect(b.xTicks.length).toBeGreaterThan(3);
});

test('square aspect equalises domains (Nyquist)', () => {
  const b = buildPlot({
    lines: [line()], xLabel: 'Re', yLabel: 'Im',
    squareAspect: true, xRange: [-2, 2], yRange: [-1, 1],
  }, 400, 400);
  expect(b.xDomain[1] - b.xDomain[0]).toBeCloseTo(b.yDomain[1] - b.yDomain[0], 9);
});

test('right-axis lines scale against y2Range', () => {
  const b = buildPlot({
    lines: [line('right')], xLabel: '', yLabel: '', y2Range: [0, 1],
    xRange: null, yRange: [-5, 5],
  }, 800, 400);
  expect(b.y2Ticks.length).toBeGreaterThan(0);
});
```

- [ ] **Step 4: `PlotSurface.svelte`**

Thin component: props `{ model: PlotModel }`; measures its box with a
`ResizeObserver`, calls `buildPlot`, renders `<svg>` with a background rect
(`fill: var(--surface)`), gridlines + tick labels from `xTicks`/`yTicks`
(mono font, `--muted`), one `<path>` per entry (`stroke-dasharray: 4 3` when
`dashed`), right-axis labels when `y2Ticks` non-empty, and axis labels. Port
the visual treatment (font sizes, gridline colour `#eef0f4`) from the mockup's
plot area. Export the `<svg>` element via `bind:` for Task 14. No logic beyond
calling `buildPlot` — all tested logic stays in `build.ts`.

- [ ] **Step 5: Run tests + perf smoke, commit**

```bash
cd webui && npx vitest run tests/plot
node -e "
const { buildPlot } = require('./dist-test-hack') // if not importable, add a tiny bench in vitest instead:
"
```

Add `webui/tests/plot/perf.test.ts` (this replaces the spec-§11 spike measurement):

```ts
import { expect, test } from 'vitest';
import { buildPlot } from '../../src/lib/plot/build';

test('24 lines x 200k samples decimates + builds in < 250 ms', () => {
  const lines = Array.from({ length: 24 }, () => ({
    x: Float64Array.from({ length: 200_000 }, (_, i) => i),
    y: Float64Array.from({ length: 200_000 }, () => Math.random()),
    color: '#000', opacity: 1, width: 1, dashed: false, yAxis: 'left' as const,
  }));
  const t0 = performance.now();
  buildPlot({ lines, xLabel: '', yLabel: '', xRange: null, yRange: null }, 1200, 500);
  expect(performance.now() - t0).toBeLessThan(250);
});
```

Expected: PASS comfortably (min-max decimation is O(n)). If it fails on lab-grade
hardware later, this is the recorded trigger to revisit the Plotly decision.

```bash
git add webui && git commit -m "feat(webui): SVG plot core — scales, min-max decimation, builder, PlotSurface"
```

---

## Task 7: Plot interaction — zoom controller + toolbar

**Executor: opus**
**Files:** create `webui/src/lib/plot/zoom.ts`, `webui/tests/plot/zoom.test.ts`,
`webui/src/components/ZoomToolbar.svelte`; modify `PlotSurface.svelte` (pointer events).

- [ ] **Step 1: Failing tests — controller maths**

```ts
import { expect, test } from 'vitest';
import { rubberBandToRange, clampToData, panBy } from '../../src/lib/plot/zoom';

const px = { width: 800, height: 400 };
const dom = { x: [0, 500] as [number, number], y: [-60, 40] as [number, number] };

test('rubber band pixel rect -> data range', () => {
  const r = rubberBandToRange({ x0: 200, y0: 100, x1: 400, y1: 300 }, dom, px);
  expect(r.x![0]).toBeCloseTo(125); expect(r.x![1]).toBeCloseTo(250);
  expect(r.y![0]).toBeCloseTo(-35); expect(r.y![1]).toBeCloseTo(15);   // y inverted
});

test('tiny drags (<6 px) are rejected as clicks', () => {
  expect(rubberBandToRange({ x0: 10, y0: 10, x1: 13, y1: 12 }, dom, px)).toBeNull();
});

test('clamp keeps the window inside data bounds + 5% margin (guardrail, spec §6)', () => {
  const c = clampToData({ x: [-900, -400], y: [0, 100] }, { x: [0, 500], y: [-60, 40] });
  expect(c.x![0]).toBeGreaterThanOrEqual(0 - 500 * 0.05);
  expect(c.x![1] - c.x![0]).toBeCloseTo(500);              // width preserved
});

test('pan shifts the window by pixel delta', () => {
  const p = panBy(dom, { dxPx: -80, dyPx: 0 }, px);
  expect(p.x![0]).toBeCloseTo(50); expect(p.x![1]).toBeCloseTo(550);
});
```

- [ ] **Step 2: Implement `zoom.ts`**

```ts
export interface PxRect { x0: number; y0: number; x1: number; y1: number; }
export interface Dom { x: [number, number] | null; y: [number, number] | null; }
interface Px { width: number; height: number; }

export function rubberBandToRange(r: PxRect, dom: { x: [number, number]; y: [number, number] }, px: Px): Dom | null {
  if (Math.abs(r.x1 - r.x0) < 6 || Math.abs(r.y1 - r.y0) < 6) return null;
  const fx = (p: number) => dom.x[0] + (p / px.width) * (dom.x[1] - dom.x[0]);
  const fy = (p: number) => dom.y[1] - (p / px.height) * (dom.y[1] - dom.y[0]);
  return {
    x: [fx(Math.min(r.x0, r.x1)), fx(Math.max(r.x0, r.x1))],
    y: [fy(Math.max(r.y0, r.y1)), fy(Math.min(r.y0, r.y1))],
  };
}

export function clampToData(want: Dom, data: { x: [number, number]; y: [number, number] }): Dom {
  const clampAxis = (w: [number, number], d: [number, number]): [number, number] => {
    const margin = (d[1] - d[0]) * 0.05;
    const lo = d[0] - margin, hi = d[1] + margin;
    const width = Math.min(w[1] - w[0], hi - lo);
    let a = w[0];
    if (a < lo) a = lo;
    if (a + width > hi) a = hi - width;
    return [a, a + width];
  };
  return {
    x: want.x ? clampAxis(want.x, data.x) : null,
    y: want.y ? clampAxis(want.y, data.y) : null,
  };
}

export function panBy(dom: { x: [number, number]; y: [number, number] },
  d: { dxPx: number; dyPx: number }, px: Px): Dom {
  const dx = (d.dxPx / px.width) * (dom.x[1] - dom.x[0]);
  const dy = (d.dyPx / px.height) * (dom.y[1] - dom.y[0]);
  return { x: [dom.x[0] - dx, dom.x[1] - dx], y: [dom.y[0] + dy, dom.y[1] + dy] };
}
```

- [ ] **Step 3: ZoomToolbar + wiring**

`ZoomToolbar.svelte` (port visuals from the mockup's floating toolbar): buttons
box-zoom (toggle), pan (toggle), back `‹`, forward `›`, Auto X, Auto Y, and a
`⋯` popover with four labelled min/max inputs (two-way synced with the view
store, mono font). `PlotSurface.svelte` gains pointer handlers: in box-zoom
mode drag draws a dashed rubber-band `<rect>`; on pointerup calls
`rubberBandToRange` → `clampToData` → `viewState.setRange(active, r)`. In pan
mode, drag calls `panBy` live (throttled with `requestAnimationFrame`), commits
one history entry on pointerup. Double-click anywhere → `viewState.autoFit(active)`.
Auto Y must fit **selected (non-off) lines only** — compute the y-extent from
the lines present in the current `PlotModel` (off lines are already excluded
by the legend/selection filter upstream).

- [ ] **Step 4: Run tests, commit**

```bash
cd webui && npx vitest run tests/plot && cd ..
git add webui && git commit -m "feat(webui): box zoom, pan, history, guardrails + zoom toolbar"
```

---

## Task 8: Legend component

**Executor: opus**
**Files:** create `webui/src/components/Legend.svelte`, `webui/src/lib/plot/legendPos.ts`,
`webui/tests/plot/legendPos.test.ts`.

- [ ] **Step 1: Failing tests — position maths**

```ts
import { expect, test } from 'vitest';
import { presetToXY, clampLegend } from '../../src/lib/plot/legendPos';

test('presets map to fractional positions', () => {
  expect(presetToXY('ne')).toEqual({ x: 0.98, y: 0.02 });
  expect(presetToXY('sw')).toEqual({ x: 0.02, y: 0.98 });
  expect(presetToXY('outside-right')).toEqual({ x: 1.02, y: 0.02 });
});

test('drag position is clamped so the legend stays reachable', () => {
  const c = clampLegend({ x: 5, y: -3 });
  expect(c.x).toBeLessThanOrEqual(1.05);
  expect(c.y).toBeGreaterThanOrEqual(0);
});
```

- [ ] **Step 2: Implement `legendPos.ts`**

```ts
export type LegendPreset = 'ne' | 'nw' | 'se' | 'sw' | 'outside-right';
const PRESETS: Record<LegendPreset, { x: number; y: number }> = {
  ne: { x: 0.98, y: 0.02 }, nw: { x: 0.02, y: 0.02 },
  se: { x: 0.98, y: 0.98 }, sw: { x: 0.02, y: 0.98 },
  'outside-right': { x: 1.02, y: 0.02 },
};
export const presetToXY = (p: LegendPreset) => ({ ...PRESETS[p] });
export const clampLegend = (pos: { x: number; y: number }) => ({
  x: Math.min(1.05, Math.max(0, pos.x)),
  y: Math.min(1.0, Math.max(0, pos.y)),
});
```

- [ ] **Step 3: Component**

`Legend.svelte`: props `{ entries: LegendEntry[] }` (from
`selection.legendEntries`) plus the active view's `legend` slice. Renders an
absolutely-positioned card over the plot (fractional x/y anchored right/top when
x > 0.5, matching matplotlib feel). Each entry: colour swatch + label; click
cycles that line's tri-state via `selection.cycleLine` (same semantics as the
tray); faded entries render at 40% opacity. Free drag via pointer events →
`clampLegend` → `viewState.setLegend` (dragging never snaps — spec §6);
presets are offered ONLY in the ZoomToolbar `⋯` popover (add a five-button
preset row there that calls `presetToXY`). A legend on/off toggle lives in the
same popover. Off-sets never appear (the store already omits them).

- [ ] **Step 4: Run tests, commit**

```bash
cd webui && npx vitest run tests/plot && cd ..
git add webui && git commit -m "feat(webui): draggable legend with corner presets + tri-state mirror"
```

---

## Task 9: Bench shell (header · ribbon · context card · layout · narrow states)

**Executor: opus**
**Files:** create `webui/src/lib/stores/stages.ts`, components `Header.svelte`,
`Ribbon.svelte`, `ContextCard.svelte`, `NarrowRail.svelte`; rewrite `App.svelte`;
create `webui/e2e/shell.spec.ts`, `webui/playwright.config.ts`.

- [ ] **Step 1: Stage store with capability gating**

```ts
// stores/stages.ts
import { derived, writable } from 'svelte/store';
import type { ViewId } from './viewstate';

export interface StageDef {
  id: 'setup' | 'acquire' | 'time' | 'frequency' | 'tf' | 'sono' | 'fit' | 'export';
  label: string;
  view: ViewId | null;               // null = keeps current view (export)
  needs: 'none' | 'liveSource' | 'fitEngine';
}
export const STAGES: StageDef[] = [
  { id: 'setup', label: 'Setup', view: null, needs: 'liveSource' },
  { id: 'acquire', label: 'Acquire', view: 'time', needs: 'liveSource' },
  { id: 'time', label: 'Time', view: 'time', needs: 'none' },
  { id: 'frequency', label: 'Frequency', view: 'frequency', needs: 'none' },
  { id: 'tf', label: 'TF', view: 'tf', needs: 'none' },
  { id: 'sono', label: 'Sonogram', view: 'sono', needs: 'none' },
  { id: 'fit', label: 'Fit', view: 'tf', needs: 'fitEngine' },   // Plan 2
  { id: 'export', label: 'Export', view: null, needs: 'none' },
];

export const capabilities = writable({ liveSource: false, fitEngine: false }); // Plan 1: both off
export const activeStage = writable<StageDef['id']>('time');
export const enabledStages = derived(capabilities, $c =>
  STAGES.map(s => ({ ...s, enabled: s.needs === 'none'
    || (s.needs === 'liveSource' && $c.liveSource)
    || (s.needs === 'fitEngine' && $c.fitEngine) })));
```

Disabled stages render greyed with `title="needs a live data source (Plan 2)"` /
`"mode fitting arrives in Plan 2"`. No numbers, no digit-key shortcuts (spec §2).

- [ ] **Step 2: Components, ported from the mockup**

- `Header.svelte`: product mark, summary chip (from loaded dataset: `fs · N sets`),
  prominent **Load Data** (blue outline) + **Save Dataset** (green solid) buttons
  (emit `load`/`save` events, wired in Task 13), autosave chip slot, working-dir
  chip slot. Level meters/CLIP are Plan 2 — leave a reserved flex slot, no fake meters.
- `Ribbon.svelte`: quiet unnumbered stage buttons from `enabledStages`; active pill;
  horizontal scroll in narrow. Clicking sets `activeStage` + `viewState.activate(view)`
  when `view != null`.
- `ContextCard.svelte`: fixed-height (118px wide-mode) frame that renders a slot per
  active stage; height may grow only in narrow (media query).
- `App.svelte`: grid `header / ribbon+card / (tray | plot)`; narrow (≤1000px or
  `?narrow=1` for tests): tray column is replaced by `NarrowRail.svelte`
  (~72px; set chips that call `cycleSet` on click; `⋯` opens the full tray as a
  flyover drawer with scrim; Esc closes). Port both treatments from the mockup —
  drawer variant IS the flyover here (rail+flyover hybrid was the review decision).
- Word labels always in the ribbon ("Frequency" → "Freq" under 1000px, never icons).

- [ ] **Step 3: Playwright config + shell spec**

`webui/playwright.config.ts`:

```ts
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: 'http://localhost:4173' },
  webServer: { command: 'npm run build && npm run preview', port: 4173, reuseExistingServer: true },
});
```

`webui/e2e/shell.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('wide shell: header buttons, unnumbered ribbon, gated stages', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Load Data' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save Dataset' })).toBeVisible();
  const ribbon = page.getByRole('navigation', { name: 'stages' });
  await expect(ribbon.getByRole('button', { name: 'Frequency' })).toBeEnabled();
  await expect(ribbon.getByRole('button', { name: 'Acquire' })).toBeDisabled();
  await expect(ribbon).not.toContainText(/[0-9]\./);          // no numbering
});

test('narrow: rail with word-label ribbon and flyover tray', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto('/');
  await expect(page.getByRole('navigation', { name: 'stages' })).toContainText('Freq');
  await expect(page.getByTestId('narrow-rail')).toBeVisible();
  await page.getByTestId('rail-more').click();                 // ⋯ opens flyover
  await expect(page.getByTestId('tray')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('tray')).toBeHidden();
});
```

- [ ] **Step 4: Run, commit**

```bash
cd webui && npx vitest run && npx playwright test e2e/shell.spec.ts && cd ..
git add webui && git commit -m "feat(webui): bench shell — header, gated ribbon, context card, narrow rail+flyover"
```

---

## Task 10: Tray

**Executor: opus**
**Files:** create `Tray.svelte`, `TrayCard.svelte`; extend `webui/e2e/shell.spec.ts`.

- [ ] **Step 1: Component contracts**

`Tray.svelte`: consumes the selection store. Header row (`DATA`, All / None /
Solo, `‹ ›` steppers), channel-chip row (union of channel indices across sets;
click → `cycleChannel`; horizontal scroll past 8; each chip shows a mini
tri-state dot summarising the column), then one `TrayCard` per `setsView` entry.
`TrayCard.svelte`: header = colour-dot stack + name (dblclick → inline
`<input>` → `rename` on Enter/blur) + duration badge + collapse chevron +
delete `×` (emits `delete`, wired to dataset removal + an undo toast in
Task 13); `allOff` ⇒ `text-decoration: line-through` on the header and reduced
opacity ("out of stock"). Rows per channel: colour chip (click → `cycleLine`),
`ch_N` label, sparkline `<svg>` (reuse `minMaxDecimate` at 60 columns over that
channel's time data), state badge. Calibrate/⋯ menu is Plan 2 — omit.

- [ ] **Step 2: e2e additions (after Task 13 provides fixture loading, mark `test.fixme` until then)**

```ts
test('tray matrix ops', async ({ page }) => {
  await page.goto('/?fixture=1');                    // Task 13 adds this hook
  const card0 = page.getByTestId('tray-card-0');
  await card0.getByTestId('set-header').click();     // row cycle -> all fade
  await expect(card0.getByText('fade').first()).toBeVisible();
  await page.getByTestId('chip-ch-1').click();       // column cycle
  await card0.getByTestId('set-header').dblclick();
  await page.keyboard.type('hammer'); await page.keyboard.press('Enter');
  await expect(card0).toContainText('hammer');
});
```

- [ ] **Step 3: Run, commit**

```bash
cd webui && npx vitest run && npx playwright test && cd ..
git add webui && git commit -m "feat(webui): data tray with matrix batch ops, rename, strikethrough"
```

---

## Task 11: pyodide engine worker

**Executor: opus**
**Files:** create `webui/scripts/fetch-pyodide.sh`, `webui/scripts/build-wheels.sh`,
`webui/src/lib/worker/engine.worker.ts`, `webui/src/lib/worker/client.ts`,
`webui/src/lib/worker/glue.py`, `webui/src/lib/stores/engine.ts`,
`webui/tests/worker/protocol.test.ts`.

- [ ] **Step 1: Vendoring scripts**

`scripts/fetch-pyodide.sh`:

```bash
#!/usr/bin/env bash
# Vendors the pyodide runtime into public/pyodide (gitignored).
set -euo pipefail
VERSION=0.28.3   # verify latest 0.28.x at https://github.com/pyodide/pyodide/releases before first run
DEST="$(dirname "$0")/../public/pyodide"
[ -f "$DEST/pyodide.js" ] && { echo "pyodide already present"; exit 0; }
mkdir -p "$DEST"
curl -L "https://github.com/pyodide/pyodide/releases/download/${VERSION}/pyodide-${VERSION}.tar.bz2" \
  | tar -xj --strip-components=1 -C "$DEST"
echo "pyodide ${VERSION} -> $DEST"
```

`scripts/build-wheels.sh`:

```bash
#!/usr/bin/env bash
# Builds the pydvma wheel + fetches peakutils into public/pypi (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="$ROOT/webui/public/pypi"
mkdir -p "$DEST"
python -m pip wheel "$ROOT" peakutils --no-deps -w "$DEST"
ls "$DEST"
```

```bash
chmod +x webui/scripts/*.sh && webui/scripts/fetch-pyodide.sh && webui/scripts/build-wheels.sh
```

Expected: `public/pyodide/pyodide.js` exists; `pydvma-*.whl` + `peakutils-*.whl` in `public/pypi/`.

- [ ] **Step 2: Verify the real pydvma API surface (CLAUDE.md: verify, don't assume)**

```bash
python -c "
import inspect
import pydvma.datastructure as d, pydvma.analysis as a
print('TimeData:', inspect.signature(d.TimeData.__init__))
print('calculate_fft:', inspect.signature(a.calculate_fft))
print('calculate_tf:', inspect.signature(a.calculate_tf))
print('calculate_tf_averaged:', inspect.signature(a.calculate_tf_averaged))
print('calculate_sonogram:', inspect.signature(a.calculate_sonogram))
print('clean_impulse:', [n for n in dir(a) if 'impulse' in n.lower()])
"
```

Record the printed signatures and write `glue.py` against them (the code below
assumes `TimeData(time_axis, time_data, settings)` and keyword args matching the
Qt GUI's calls — adjust to what the interpreter reports, not the other way around).

- [ ] **Step 3: `glue.py` (python side, loaded into pyodide as a module)**

```python
# -*- coding: utf-8 -*-
"""Worker-side glue: stateless compute wrappers around pydvma.
Arrays cross the JS/py boundary as flat float64 buffers + shape."""
import io
import json
import numpy as np
import pydvma as dvma
from pydvma import analysis, datastructure, container


def _settings(fs, channels):
    return dvma.MySettings(channels=int(channels), fs=float(fs), device_driver='mock')


def _time_data(time_axis, time_data, fs):
    ta = np.asarray(time_axis, dtype=np.float64)
    td = np.asarray(time_data, dtype=np.float64)
    return datastructure.TimeData(ta, td, _settings(fs, td.shape[1]))


def legacy_to_dvma(npy_bytes):
    """Load a legacy pickle .npy (or .mat via caller flag) -> .dvma bytes."""
    d = np.load(io.BytesIO(bytes(npy_bytes)), allow_pickle=True, fix_imports=True)
    dataset = d[0]
    buf = io.BytesIO()
    container.save(dataset, buf)          # verify container.save accepts file objects;
    return buf.getvalue()                 # if not, write to /tmp/x.dvma and read back


def mat_to_dvma(mat_bytes):
    from pydvma import file as pfile
    with open('/tmp/import.mat', 'wb') as f:
        f.write(bytes(mat_bytes))
    dataset = pfile.import_from_matlab_jwlogger(filename='/tmp/import.mat')
    container.save(dataset, '/tmp/import.dvma')
    return open('/tmp/import.dvma', 'rb').read()


def calc_fft(time_axis, time_data, fs, window):
    td = _time_data(time_axis, time_data, fs)
    fd = analysis.calculate_fft(td, window=(window or None))
    return {'freq_axis': fd.freq_axis, 'freq_data': fd.freq_data}


def calc_psd(time_axis, time_data, fs, window, n_frames):
    td = _time_data(time_axis, time_data, fs)
    cs = analysis.calculate_cross_spectrum_matrix(td, window=(window or 'hann'),
                                                  N_frames=int(n_frames))
    # PSDs are the diagonal of Pxy
    psd = np.real(np.einsum('iif->if', cs.Pxy))
    return {'freq_axis': cs.freq_axis, 'psd': psd, 'Cxy': cs.Cxy}


def calc_tf(time_axis, time_data, fs, ch_in, window, n_frames):
    td = _time_data(time_axis, time_data, fs)
    tf = analysis.calculate_tf(td, ch_in=int(ch_in), window=(window or None),
                               N_frames=int(n_frames))
    return {'freq_axis': tf.freq_axis, 'tf_data': tf.tf_data,
            'coherence': tf.tf_coherence}


def calc_sono(time_axis, time_data, fs, ch, n_frames):
    td = _time_data(time_axis, time_data, fs)
    sd = analysis.calculate_sonogram(td, N_frames=int(n_frames))  # verify kwargs incl. channel
    return {'time_axis': sd.time_axis, 'freq_axis': sd.freq_axis,
            'sono_data': np.abs(sd.sono_data)}
```

Every `# verify` comment is a real instruction: run the Step 2 signatures and
fix mismatches before wiring. Return values cross back via
`pyodide.ffi` → JS typed arrays.

- [ ] **Step 4: Worker + client + status store**

`engine.worker.ts` (shape; exact pyodide API from vendored docs):

```ts
/// <reference lib="webworker" />
import glueSource from './glue.py?raw';

let pyodide: any = null;
let glue: any = null;

interface Req { id: number; op: string; payload: any; }

async function boot(baseUrl: string) {
  importScripts(`${baseUrl}pyodide/pyodide.js`);
  pyodide = await (self as any).loadPyodide({ indexURL: `${baseUrl}pyodide/` });
  await pyodide.loadPackage(['numpy', 'scipy', 'micropip']);
  const micropip = pyodide.pyimport('micropip');
  const wheels: string[] = (self as any).__WHEELS__;      // sent in init payload
  for (const w of wheels) await micropip.install(`${baseUrl}pypi/${w}`);
  pyodide.FS.writeFile('/glue.py', glueSource);
  glue = pyodide.pyimport('glue');
}

self.onmessage = async (e: MessageEvent<Req>) => {
  const { id, op, payload } = e.data;
  try {
    let result: any;
    if (op === 'init') { (self as any).__WHEELS__ = payload.wheels; await boot(payload.baseUrl); result = 'ready'; }
    else {
      const fn = glue[op];
      if (!fn) throw new Error(`unknown op ${op}`);
      const py = fn.callKwargs(payload);                   // dict of args
      result = py.toJs({ create_proxies: false });         // numpy -> typed arrays
      py.destroy?.();
    }
    (self as any).postMessage({ id, ok: true, result });
  } catch (err: any) {
    (self as any).postMessage({ id, ok: false, error: String(err?.message ?? err) });
  }
};
```

`client.ts`: promise map keyed by id; `engineCall(op, payload)`;
`stores/engine.ts`: `status: 'idle'|'loading'|'ready'|'error'` + a FIFO of
queued compute actions released on `ready` — the shell never blocks on boot
(spec §11); the ContextCard Calc buttons render a small "engine loading…" chip
while queued.

- [ ] **Step 5: Protocol unit test (worker mocked) + engine e2e**

`tests/worker/protocol.test.ts`: instantiate `client.ts` against a fake
`postMessage` pair; assert id matching, error propagation, queue-until-ready.

`e2e/engine.spec.ts` (tagged — real pyodide, needs vendored runtime):

```ts
import { expect, test } from '@playwright/test';
test('@engine boots pyodide and reports ready', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await expect(page.getByTestId('engine-status')).toHaveText(/ready/, { timeout: 150_000 });
});
```

- [ ] **Step 6: Run, commit**

```bash
cd webui && npx vitest run && npx playwright test --grep @engine && cd ..
git add webui && git commit -m "feat(webui): pyodide engine worker — boot, wheel install, compute protocol"
```

---

## Task 12: Analysis stages — context cards wired to compute

**Executor: opus**
**Files:** create `webui/src/lib/analysis/actions.ts`, cards
`TimeCard/FrequencyCard/TFCard/SonoCard`, `webui/tests/analysis/actions.test.ts`;
modify `App.svelte` (card slot per stage), `webui/e2e/analysis.spec.ts`.

- [ ] **Step 1: `actions.ts` — dataset-level orchestration (complete logic)**

Responsibilities (all pure orchestration; maths stays in the worker):
- hold the working `DvmaDataset` in a writable store; on load, populate
  the selection store (one `addSet` per TimeData item);
- `calcFft(window)` / `calcPsd(window, resolution)` — per TimeData set → replace
  FreqData/CrossSpec items derived from that set;
- `calcTf(chIn, window, averaging, resolution)` — `averaging: 'none'|'within'|'across'`
  maps to `calc_tf` per set (`n_frames` from the coupled control) or
  `calc_tf_averaged` across sets (worker op added in glue when needed — same
  call shape);
- `calcSono(setIdx, ch, resolution, dynRangeDb)`;
- every action: if engine not ready, queue via `stores/engine.ts` and surface the
  chip; on result, write items into the dataset store — plots re-derive from it.
- **live sliders**: `debounce(150ms)` wrapper around calcTf/calcSono re-issue;
  in-flight guard (drop stale responses by comparing a monotonically increasing
  action seq — include this code).

```ts
let seq = 0;
export function latestOnly<T extends unknown[]>(fn: (...a: T) => Promise<void>) {
  return async (...a: T) => {
    const mySeq = ++seq;
    await fn(...a);
    if (mySeq !== seq) return;      // a newer call superseded this one — its
                                    // writer already checked seq before commit
  };
}
```

(The commit-side check: `actions` capture `mySeq` before the worker call and
skip the dataset write when `mySeq !== seq`.)

- [ ] **Step 2: Cards (port layout from mockup; wire to stores)**

- `TimeCard`: quick-range chips `[Full] [First 0.2 s]` → `viewState.setRange('time', …)`;
  input-channel select + **Clean Impulse** button → worker `clean_impulse` op
  (add to glue.py mirroring the Qt call; verify name via Task 11 Step 2 output);
  Save Figure button (Task 14's export dialog).
- `FrequencyCard`: `[FFT | PSD | CSD]` sub-toggle; window select (None/hann);
  coupled resolution control (three linked inputs + one slider — bind through
  `fromNFrames/fromFrameLength/fromNFft`; PSD/CSD only); **Calc** primary.
  CSD renders magnitude of `Cxy` per pair — Plan 1 keeps it to coherence
  matrix display; label honestly ("CSD (coherence)") if `Pxy` off-diagonals
  are deferred; note in card tooltip.
- `TFCard`: window, averaging select, N-frames slider (1–30) + linked fields,
  `Frame length = X.XX s` readout, coherence toggle, **plot type** select
  (Mag dB / Phase / Bode / Real / Imag / Nyquist), **Calc TF** primary.
  Plot-type mapping in the TF plot model builder:
  - mag: `20*log10(|H|)` (computed JS-side from complex tf_data — display
    transform, not analysis maths); phase: `atan2` unwrapped-naive (wrapped
    display is fine, matches Qt); real/imag: components; bode: two stacked
    `PlotSurface`s (mag over phase) sharing the x-range; nyquist:
    `squareAspect: true`, x=Re, y=Im, plus fmin/fmax fields bound to
    `sharedFreqRange` filtering the plotted index window.
  - coherence lines: same hue as their data line, `dashed: true`,
    `width: 1`, `opacity: 0.7`, `yAxis: 'right'`, y2Range `[0, 1]` (spec §5).
- `SonoCard`: resolution slider (live), dynamic-range dB input, set/chan
  selects, **Calc Sonogram**. Sonogram rendering: a `<canvas>` heat layer under
  the axes (magnitude → viridis-like ramp — include a 6-stop colour ramp
  in code), drawn from `sono_data` with the dyn-range clamp; axes from
  `PlotSurface` with an empty lines array.

- [ ] **Step 3: Unit tests for actions**

`tests/analysis/actions.test.ts`: fake engine client (records calls, returns
canned arrays); assert: calcTf('within') issues one call per set with
`n_frames` from resolution; 'across' issues one `calc_tf_averaged`; stale-drop:
fire two calcTf, resolve out of order, dataset holds the latest only.

- [ ] **Step 4: e2e golden analysis path**

`e2e/analysis.spec.ts` (`@engine`):

```ts
test('@engine load fixture -> calc TF -> coherence + plot types', async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto('/?fixture=1');
  await page.getByRole('button', { name: 'TF' }).click();
  await page.getByRole('button', { name: 'Calc TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeVisible({ timeout: 200_000 });
  await page.getByLabel('Plot type').selectOption('nyquist');
  const box = await page.getByTestId('plot-svg').boundingBox();
  // square aspect: plot inner box ~square
  expect(Math.abs(box!.width - box!.height)).toBeLessThan(box!.width * 0.2);
});
```

- [ ] **Step 5: Run, commit**

```bash
cd webui && npx vitest run && npx playwright test && cd ..
git add webui && git commit -m "feat(webui): analysis stages — FFT/PSD/TF/sono cards wired to engine"
```

---

## Task 13: Files, working directory, autosave

**Executor: opus**
**Files:** create `webui/src/lib/files/{sniff,workdir,autosave}.ts`, tests;
wire `Header.svelte` events; add `?fixture=1` dev hook in `App.svelte`.

- [ ] **Step 1: Failing tests — sniffing**

```ts
import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { sniffFormat } from '../../src/lib/files/sniff';

test('detects dvma (zip), legacy npy, mat', () => {
  const dvma = new Uint8Array(readFileSync('tests/fixtures/impulse.dvma'));
  expect(sniffFormat(dvma, 'x.dvma')).toBe('dvma');
  expect(sniffFormat(dvma.subarray(0), 'renamed.npy')).toBe('dvma');   // content wins
  const npy = new Uint8Array(readFileSync('tests/fixtures/f8_2x3.npy'));
  expect(sniffFormat(npy, 'x.npy')).toBe('npy');
  expect(sniffFormat(new Uint8Array([0, 1, 2, 3]), 'x.mat')).toBe('mat');
  expect(sniffFormat(new Uint8Array([0, 1, 2, 3]), 'x.bin')).toBe('unknown');
});
```

Implementation:

```ts
export type FileFormat = 'dvma' | 'npy' | 'mat' | 'unknown';
export function sniffFormat(bytes: Uint8Array, name: string): FileFormat {
  if (bytes[0] === 0x50 && bytes[1] === 0x4b) return 'dvma';           // PK zip magic
  if (bytes[0] === 0x93 && bytes[1] === 0x4e) return 'npy';            // \x93N
  if (name.toLowerCase().endsWith('.mat')) return 'mat';
  return 'unknown';
}
```

- [ ] **Step 2: `workdir.ts`**

```ts
import { get as idbGet, set as idbSet } from 'idb-keyval';

export interface WorkDir {
  kind: 'fsaccess' | 'fallback';
  name: string;                                  // shown in the header chip
  save(name: string, bytes: Uint8Array): Promise<void>;
  open(): Promise<{ name: string; bytes: Uint8Array } | null>;
}

const KEY = 'pydvma-workdir-handle';
export const hasFsAccess = () => 'showDirectoryPicker' in window;

export async function pickWorkDir(): Promise<WorkDir> {
  if (!hasFsAccess()) return fallbackDir();
  const handle: FileSystemDirectoryHandle = await (window as any).showDirectoryPicker({ mode: 'readwrite' });
  await idbSet(KEY, handle);
  return wrap(handle);
}

export async function restoreWorkDir(): Promise<WorkDir | null> {
  if (!hasFsAccess()) return null;
  const handle: FileSystemDirectoryHandle | undefined = await idbGet(KEY);
  if (!handle) return null;
  const perm = await (handle as any).queryPermission({ mode: 'readwrite' });
  if (perm !== 'granted') {
    const again = await (handle as any).requestPermission({ mode: 'readwrite' });
    if (again !== 'granted') return null;        // caller shows re-pick chip
  }
  return wrap(handle);
}

function wrap(handle: FileSystemDirectoryHandle): WorkDir {
  return {
    kind: 'fsaccess', name: handle.name,
    async save(name, bytes) {
      const fh = await handle.getFileHandle(name, { create: true });
      const w = await fh.createWritable(); await w.write(bytes as any); await w.close();
    },
    async open() {
      const [fh] = await (window as any).showOpenFilePicker({ startIn: handle });
      const f = await fh.getFile();
      return { name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) };
    },
  };
}

function fallbackDir(): WorkDir {
  return {
    kind: 'fallback', name: 'Downloads',
    async save(name, bytes) {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([bytes]));
      a.download = name; a.click(); URL.revokeObjectURL(a.href);
    },
    async open() {
      return new Promise(resolve => {
        const inp = document.createElement('input');
        inp.type = 'file'; inp.accept = '.dvma,.npy,.mat';
        inp.onchange = async () => {
          const f = inp.files?.[0]; if (!f) return resolve(null);
          resolve({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) });
        };
        inp.click();
      });
    },
  };
}
```

(Unit-test the pure parts — sniff + autosave debounce — in vitest; FS Access
paths get covered by the e2e fallback route since Playwright Chromium exposes
`showDirectoryPicker` only with flags; test the *fallback* branch in e2e.)

- [ ] **Step 3: `autosave.ts` + restore banner**

```ts
import { set as idbSet, get as idbGet } from 'idb-keyval';
import type { WorkDir } from './workdir';

const IDB_KEY = 'pydvma-autosave';
let timer: ReturnType<typeof setTimeout> | null = null;

/** Debounced: real file into the working dir when possible, IndexedDB otherwise. */
export function autosave(bytes: Uint8Array, dir: WorkDir | null, enabled: boolean) {
  if (!enabled) return;
  if (timer) clearTimeout(timer);
  timer = setTimeout(async () => {
    if (dir && dir.kind === 'fsaccess') await dir.save('autosave.dvma', bytes);
    else await idbSet(IDB_KEY, bytes);
  }, 2000);
}

export async function restoreOffer(): Promise<Uint8Array | null> {
  return (await idbGet(IDB_KEY)) ?? null;
}
```

Wire: dataset store subscription triggers `autosave` after every mutation;
on boot, `restoreOffer()` non-null → toast "Restore last session? [Restore] [Dismiss]".

- [ ] **Step 4: Load/save pipeline + fixture hook**

In `App.svelte`: Header `load` event → `workdir.open()` (or fallback) →
`sniffFormat` → dvma: `readDvma`; npy: worker `legacy_to_dvma` → `readDvma`;
mat: worker `mat_to_dvma` → `readDvma`; unknown: error toast. `save` event →
`writeDvma(dataset)` → `dir.save(name)` with a filename prompt defaulting
`pydvma_YYYY-MM-DD_HHMM.dvma`. Dev/e2e hook: `?fixture=1` fetches
`/tests-fixture.dvma` (copy `impulse.dvma` into `public/` at build via a small
vite plugin or a static copy in `scripts/`) and loads it through the same
pipeline. Un-fixme the Task 10 tray e2e.

- [ ] **Step 5: Run everything, commit**

```bash
cd webui && npx vitest run && npx playwright test && cd ..
git add webui && git commit -m "feat(webui): load/save pipeline, working directory, autosave + restore"
```

---

## Task 14: Figure export

**Executor: opus**
**Files:** create `webui/src/lib/export/figure.ts`, `webui/src/components/cards/ExportCard.svelte`,
`webui/tests/export/figure.test.ts`.

- [ ] **Step 1: Failing tests (string-level, DOM-free parts)**

```ts
import { expect, test } from 'vitest';
import { prepareSvg } from '../../src/lib/export/figure';

const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">'
  + '<rect data-role="plot-bg" width="800" height="400" fill="#ffffff"/>'
  + '<path stroke="#2563eb" d="M0,0L10,10"/></svg>';

test('white mode keeps a white bg rect', () => {
  expect(prepareSvg(svg, 'white')).toContain('fill="#ffffff"');
});
test('transparent mode strips the bg rect fill', () => {
  expect(prepareSvg(svg, 'transparent')).toContain('fill="none"');
});
test('dark mode swaps bg and recolours axis strokes', () => {
  const out = prepareSvg(svg, 'dark');
  expect(out).toContain('fill="#1b2130"');
  expect(out).not.toContain('fill="#ffffff"');
});
```

- [ ] **Step 2: Implement `figure.ts`**

```ts
export type BgMode = 'white' | 'transparent' | 'dark';

/** String-level SVG restyle: the PlotSurface marks its background rect with
 * data-role="plot-bg" and axis/tick elements with data-role="axis". */
export function prepareSvg(svgText: string, mode: BgMode): string {
  let out = svgText;
  if (mode === 'transparent') {
    out = out.replace(/(<rect[^>]*data-role="plot-bg"[^>]*fill=")[^"]*(")/, '$1none$2');
  } else if (mode === 'dark') {
    out = out.replace(/(<rect[^>]*data-role="plot-bg"[^>]*fill=")[^"]*(")/, '$1#1b2130$2');
    out = out.replace(/(data-role="axis"[^>]*(?:stroke|fill)=")#17203a(")/g, '$1#e6e9f2$2');
    out = out.replace(/(data-role="axis"[^>]*(?:stroke|fill)=")#66708a(")/g, '$1#9aa4c0$2');
  }
  return out;
}

export async function exportPng(svgText: string, mode: BgMode, scale = 3): Promise<Blob> {
  const svg = prepareSvg(svgText, mode);
  const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
  const img = new Image();
  await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = url; });
  const canvas = document.createElement('canvas');
  canvas.width = img.width * scale; canvas.height = img.height * scale;
  const ctx = canvas.getContext('2d')!;
  ctx.scale(scale, scale); ctx.drawImage(img, 0, 0);
  URL.revokeObjectURL(url);
  return new Promise(res => canvas.toBlob(b => res(b!), 'image/png'));
}

export async function exportPdf(svgText: string, mode: BgMode): Promise<Blob> {
  const { jsPDF } = await import('jspdf');
  await import('svg2pdf.js');
  const el = new DOMParser().parseFromString(prepareSvg(svgText, mode), 'image/svg+xml').documentElement;
  const wPt = Number(el.getAttribute('width')) * 0.75, hPt = Number(el.getAttribute('height')) * 0.75;
  const doc = new jsPDF({ unit: 'pt', format: [wPt, hPt], orientation: wPt > hPt ? 'l' : 'p' });
  await (doc as any).svg(el, { x: 0, y: 0, width: wPt, height: hPt });
  return doc.output('blob');
}
```

Requires `PlotSurface.svelte` to tag its background rect `data-role="plot-bg"`
and axis text/lines `data-role="axis"` (add in this task).

- [ ] **Step 3: ExportCard + Save Figure flow**

`ExportCard.svelte`: Save Dataset (delegates to header save), **Save Figure**
group: PNG / PDF checkboxes (both allowed, explicitly — no silent two-for-one),
background mode radio white (default) / transparent / dark, filename field;
writes via the working dir. Also Matlab/CSV export buttons DISABLED with
tooltip "export via CLI for now — webui export in Plan 2" (honest gating; the
worker could do it but it's out of Plan-1 scope). Add a "Save Figure" button to
`TimeCard` too (labsheet idiom), opening the same dialog.

- [ ] **Step 4: e2e download check + commit**

```ts
test('export PNG downloads a file', async ({ page }) => {
  await page.goto('/?fixture=1');
  await page.getByRole('button', { name: 'Export' }).click();
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Save Figure' }).click();
  expect((await dl).suggestedFilename()).toMatch(/\.png$/);
});
```

```bash
cd webui && npx vitest run && npx playwright test && cd ..
git add webui && git commit -m "feat(webui): figure export — PNG/PDF with white/transparent/dark backgrounds"
```

---

## Task 15: CI + Pages deploy

**Executor: opus**
**Files:** create `.github/workflows/webui.yml`; modify `.github/workflows/docs.yml`.

- [ ] **Step 1: `webui.yml`**

```yaml
name: webui
on:
  push: { branches: [master, main], paths: ['webui/**', '.github/workflows/webui.yml'] }
  pull_request: { paths: ['webui/**'] }
jobs:
  test:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: webui } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm, cache-dependency-path: webui/package-lock.json }
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: npm ci
      - run: npx vitest run
      - name: Vendor pyodide (cached)
        uses: actions/cache@v4
        with: { path: webui/public/pyodide, key: pyodide-0.28.3 }
      - run: ./scripts/fetch-pyodide.sh
      - run: ./scripts/build-wheels.sh
      - run: npx playwright install --with-deps chromium
      - run: npx playwright test
      - run: npm run build
```

- [ ] **Step 2: Extend the Pages deploy in `docs.yml`**

In the existing "Deploy documentation + JupyterLite" step, after the lite build
and before `ghp-import`, add:

```yaml
          (cd webui && npm ci && ./scripts/fetch-pyodide.sh && ./scripts/build-wheels.sh && npm run build)
          mkdir -p site/app && cp -r webui/dist/* site/app/
```

(Node setup step must be added to that job too — mirror the `setup-node` block.)
Mind the Pages rate limit noted in the handoff: batch pushes.

- [ ] **Step 3: Validate + commit**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/webui.yml')); yaml.safe_load(open('.github/workflows/docs.yml')); print('yaml OK')"
git add .github/workflows && git commit -m "ci: webui tests + Pages deploy to /app/"
```

---

## Task 16: Milestone gate (orchestrator — Fable, not a subagent)

**Executor: orchestrator**

- [ ] **Step 1: Full-suite verification**

```bash
python -m pytest tests/ -q          # python suite untouched & green
cd webui && npx vitest run && npx playwright test && npm run build && cd ..
```

- [ ] **Step 2: Code review** — run the code-review skill over the Plan-1 diff
  range (`git log --oneline` from the scaffold commit) at high effort; triage
  and fix confirmed findings.

- [ ] **Step 3: Spec-parity check** — walk spec §13's checklist for the items in
  Plan-1 scope (zoom UX §6, legend/off-sets §3/§6, PSD+averaging §5, coherence
  §5, Nyquist §5, import/export §7, autosave §7, narrow mode §9, plot-state
  debuggability §11, deployment §11) and record any deliberate gaps in the
  Plan-2 backlog section of `TODO.md`.

- [ ] **Step 4: Bookkeeping** — update `TODO.md` (Stage 2 Plan 1 landed; Plan 2
  backlog: Matlab/CSV export, calibrate dialog, Fit stage, monitor, acquire,
  x-log toggle [flagged: in Qt, absent from spec — ask Tore], CSD off-diagonals);
  update `CLAUDE.md` "Current focus" to Plan 2; write
  `dev/2026-XX-XX-stage2-plan1-handoff.md` with live-test instructions
  (`cd webui && npm run dev`, open `http://localhost:5173/?fixture=1`).

- [ ] **Step 5: Hand to Tore for a hands-on session** with his real lab `.dvma`
  files before Plan 2 starts.

---

## Out of scope for this plan (tracked for Plans 2–3)

Acquisition (Setup/Acquire cards, one Log button + OUT badge, pretrigger),
monitor/oscilloscope (incl. stacked-traces toggle, pop-out), levels in header,
mode fitting stage, sono damping fit interactivity, calibration dialog +
`channel_sensitivities` write-through, Best Match / x(iω) scaling group,
Matlab/CSV export from the browser, dark app theme (tokens are ready; the
figure-export dark mode ships now), `pydvma serve` bridge + capability
metadata + NI, browser-tab-title levels, PWA packaging.

## Self-review record

- Spec coverage for Plan-1 scope verified against §13 (see Task 16 Step 3 for
  the executable version of this check).
- Known deliberate deviations: fflate instead of jszip (smaller, sync API —
  spec's jszip was parenthetical); Matlab/CSV export deferred; CSD limited to
  coherence display pending `Pxy` off-diagonal UX; x-log toggle flagged as a
  spec gap to raise with Tore.
- Type-consistency pass done: `TriState`, `Range`, `ViewId`, `NpyArray`,
  `DvmaDataset`, `Resolution`, `BgMode` are each defined once and imported.

