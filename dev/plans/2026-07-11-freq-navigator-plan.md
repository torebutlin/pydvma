# Frequency Navigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A collapsible frequency-navigator strip (generalised from the Nyquist brush) on all frequency-x views, with a progressive scope ribbon, peak-step buttons, and fitted-mode ticks — per `dev/plans/2026-07-11-freq-navigator-design.md`.

**Architecture:** Pure webui change (no engine/wheel). `NyquistBrush.svelte` becomes `FreqNavigator.svelte` (strip maps a *scope* domain instead of the full extent; a thin ribbon appears when scoped). New pure helpers in `lib/plot/peaks.ts` (client-side peak detection + step targeting). `viewstate.ts` gains a shared `freqScope` store + per-view `navigator` override. App mounts the navigator via one snippet on the frequency/tf views; the ZoomToolbar gains a toggle.

**Tech Stack:** Svelte 5 (runes), TypeScript, vitest (from `webui/`), Playwright (ONLY from `webui/` — root cwd fakes a "duplicate test()" error), MkDocs (`python -m mkdocs build --strict` from repo root).

**Conventions that bite (from CLAUDE.md / memory):**
- Commit small coherent changes to `master` directly as you go; do NOT push.
- Gate on `npm run check` (app tsconfig), NOT bare `svelte-check`.
- SVG plot lines fail Playwright `toBeVisible` (zero-height bbox) → use `toBeAttached`.
- No new calc actions here, so no `engine.boot()` concern.
- Update any docstring you touch if it has drifted.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `webui/src/lib/stores/viewstate.ts` | modify | `navigator: boolean\|null` per view; shared `freqScope` store + setters; serialize/restore |
| `webui/tests/stores/viewstate.test.ts` | modify | tests for the above |
| `webui/src/lib/plot/peaks.ts` | create | `detectPeaks` + `stepWindow` pure helpers |
| `webui/tests/plot/peaks.test.ts` | create | tests for the helpers |
| `webui/src/components/FreqNavigator.svelte` | create (git mv from `NyquistBrush.svelte`) | strip + scope ribbon + ⤢ + ‹ › + mode ticks + off-scope arrows |
| `webui/src/components/NyquistBrush.svelte` | delete (via git mv) | absorbed |
| `webui/src/App.svelte` | modify | `navModel`/`navOpen`/`scope` derivations, snippet mount on freq/tf/bode/nyquist blocks, handlers |
| `webui/src/components/ZoomToolbar.svelte` | modify | navigator toggle button |
| `webui/e2e/axis-nav.spec.ts` | modify | testid rename `nyquist-brush*` → `freq-nav*` |
| `webui/e2e/freq-nav.spec.ts` | create | toggle/drag/scope/peak-step/auto-open e2e (fixture, no engine) |
| `webui/e2e/fit.spec.ts` | modify | mode-tick assertion after Fit 2 |
| `docs/web-logger/analysis.md`, `docs/web-logger/modal-fitting.md` | modify | user docs |

All `npm`/`npx` commands run from `/Users/tore/Documents/GitHub/pydvma/webui`. Git commands from the repo root are fine.

---

### Task 1: viewstate — `navigator` flag + shared `freqScope`

**Files:**
- Modify: `webui/src/lib/stores/viewstate.ts`
- Test: `webui/tests/stores/viewstate.test.ts`

- [ ] **Step 1: Write the failing tests** — append to `webui/tests/stores/viewstate.test.ts`:

```ts
// ── Frequency navigator (dev/plans/2026-07-11-freq-navigator-design.md) ────
test('freqScope: defaults null; set/clear pushes NO history (not undoable)', () => {
  const vs = createViewState();
  expect(get(vs.freqScope)).toBeNull();
  vs.setFreqScope([100, 500]);
  expect(get(vs.freqScope)).toEqual([100, 500]);
  vs.activate('tf');
  expect(get(vs.current).history.length).toBe(0);
  vs.setFreqScope(null);
  expect(get(vs.freqScope)).toBeNull();
});

test('navigator override: per-view, defaults null (auto)', () => {
  const vs = createViewState();
  vs.activate('tf');
  expect(get(vs.current).navigator).toBeNull();
  vs.setNavigator('tf', true);
  expect(get(vs.current).navigator).toBe(true);
  vs.activate('frequency');
  expect(get(vs.current).navigator).toBeNull();   // per-view, tf untouched elsewhere
});

test('freqScope + navigator survive a serialize/restore JSON round-trip', () => {
  const vs = createViewState();
  vs.setFreqScope([50, 2000]);
  vs.setNavigator('tf', true);
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  const vs2 = createViewState();
  vs2.restore(snap);
  expect(get(vs2.freqScope)).toEqual([50, 2000]);
  vs2.activate('tf');
  expect(get(vs2.current).navigator).toBe(true);
});

test('legacy snapshot (no freqScope / navigator fields) restores to defaults', () => {
  const vs = createViewState();
  const snap = JSON.parse(JSON.stringify(vs.serialize()));
  delete snap.freqScope;
  for (const id of ['time', 'frequency', 'tf', 'sono']) delete snap.views[id].navigator;
  const vs2 = createViewState();
  vs2.setFreqScope([1, 2]);          // must be OVERWRITTEN back to null by restore
  vs2.setNavigator('tf', false);
  vs2.restore(snap);
  expect(get(vs2.freqScope)).toBeNull();
  vs2.activate('tf');
  expect(get(vs2.current).navigator).toBeNull();
});

test('restore rejects a malformed freqScope (inverted / wrong shape → null)', () => {
  for (const bad of [[500, 100], [1, 1], ['a', 'b'], [1], 42, {}]) {
    const vs = createViewState();
    const snap = JSON.parse(JSON.stringify(vs.serialize()));
    snap.freqScope = bad;
    const vs2 = createViewState();
    vs2.restore(snap);
    expect(get(vs2.freqScope)).toBeNull();
  }
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run tests/stores/viewstate.test.ts`
Expected: the 5 new tests FAIL (`vs.freqScope is undefined` / `setFreqScope is not a function`); all pre-existing tests PASS.

- [ ] **Step 3: Implement** in `webui/src/lib/stores/viewstate.ts`:

3a. Add to the `ViewSlice` interface (after `sonoColour`), with this doc line appended to the interface's docstring block:

```ts
  // ── frequency navigator (2026-07-11 design) ──
  navigator: boolean | null;         // freq-navigator visibility override; null = auto
```

Docstring addition (inside the big `ViewSlice` comment, after the sono paragraph):

```
 * `navigator` is the frequency-navigator visibility OVERRIDE for this view:
 * `null` (default) = auto — App resolves auto to open in the Fit stage and on
 * the tf Nyquist plotType (where the strip is the primary frequency control),
 * closed otherwise; an explicit boolean (set by the toolbar toggle) wins. A
 * display mode like `legend` — serialized, never in undo history.
```

3b. In `fresh()` add `navigator: null,` after `sonoFreqScale: 'lin', sonoColour: 'db',`.

3c. Inside `createViewState()`, after `const active = writable<ViewId>('time');`:

```ts
  /**
   * The shared frequency SCOPE — the navigator's bandwidth-of-interest
   * (dev/plans/2026-07-11-freq-navigator-design.md). One value across the
   * frequency-x views (a property of the measurement, like `sharedFreqRange`),
   * `null` = unscoped (the strip spans the full data extent). Purely
   * navigational: never moves the committed window or the plot, so scope
   * changes are NOT recorded in undo history — but the value IS serialized.
   */
  const freqScope = writable<[number, number] | null>(null);
```

3d. New methods (near `setLegend`):

```ts
  /** Set or clear (null) the shared frequency scope. No history entry. */
  function setFreqScope(s: [number, number] | null) { freqScope.set(s); }

  /**
   * Set view `id`'s navigator visibility override (`true`/`false`), or `null`
   * to return it to auto. A display mode — not recorded in history.
   */
  function setNavigator(id: ViewId, open: boolean | null) {
    patch(id, v => ({ ...v, navigator: open }));
  }
```

3e. `serialize()` becomes:

```ts
  function serialize() { return { views: get(views), active: get(active), freqScope: get(freqScope) }; }
```

3f. In `restore()`, after the `views.set(merged); active.set(...)` lines, add (and extend the restore docstring with one sentence: "`freqScope` restores to `null` unless the snapshot carries a valid `[lo, hi]` pair."):

```ts
    const fsRaw = (s as { freqScope?: unknown }).freqScope;
    const fsOk = Array.isArray(fsRaw) && fsRaw.length === 2
      && typeof fsRaw[0] === 'number' && typeof fsRaw[1] === 'number'
      && Number.isFinite(fsRaw[0]) && Number.isFinite(fsRaw[1]) && fsRaw[1] > fsRaw[0];
    freqScope.set(fsOk ? [fsRaw[0] as number, fsRaw[1] as number] : null);
```

3g. Add to the returned object: `freqScope,` (the store — expose read-only by convention like `active`) and `setFreqScope, setNavigator,` in the setters list.

Note: `navigator: null` for legacy snapshots needs NO restore change — `restore()` already merges each slice over `fresh()`.

- [ ] **Step 4: Run tests**

Run: `npx vitest run tests/stores/viewstate.test.ts`
Expected: ALL PASS.

- [ ] **Step 5: Type-check + commit**

Run: `npm run check` — expected 0 errors, 0 warnings.

```bash
git add webui/src/lib/stores/viewstate.ts webui/tests/stores/viewstate.test.ts
git commit -m "feat(webui): viewstate freqScope + per-view navigator override

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `peaks.ts` — peak detection + step targeting

**Files:**
- Create: `webui/src/lib/plot/peaks.ts`
- Test: `webui/tests/plot/peaks.test.ts`

- [ ] **Step 1: Write the failing tests** — create `webui/tests/plot/peaks.test.ts`:

```ts
import { expect, test } from 'vitest';
import { detectPeaks, stepWindow } from '../../src/lib/plot/peaks';

/** Synthetic |H|(f)-in-dB line: three Lorentzian-ish peaks + mild ripple. */
function threePeakLine(): { x: Float64Array; y: Float64Array } {
  const N = 2000;
  const x = new Float64Array(N), y = new Float64Array(N);
  const modes = [{ fn: 120, a: 40 }, { fn: 470, a: 55 }, { fn: 810, a: 35 }];
  for (let i = 0; i < N; i++) {
    const f = (i / (N - 1)) * 1000;                    // 0..1000 Hz
    let v = 0;
    for (const m of modes) v += m.a / (1 + ((f - m.fn) / 12) ** 2);
    x[i] = f;
    // Ripple prominence ≈ 2·amp = 2.0, safely below the 5% gate (~2.9 of the
    // ~58 span) — decisive, not marginal.
    y[i] = v + 1.0 * Math.sin(f / 3);
  }
  return { x, y };
}

test('detectPeaks finds the three synthetic modes (and nothing else)', () => {
  const peaks = detectPeaks([threePeakLine()], [0, 1000]);
  expect(peaks.length).toBe(3);
  expect(Math.abs(peaks[0] - 120)).toBeLessThan(5);
  expect(Math.abs(peaks[1] - 470)).toBeLessThan(5);
  expect(Math.abs(peaks[2] - 810)).toBeLessThan(5);
});

test('detectPeaks respects the scope (only peaks inside it)', () => {
  const peaks = detectPeaks([threePeakLine()], [300, 700]);
  expect(peaks.length).toBe(1);
  expect(Math.abs(peaks[0] - 470)).toBeLessThan(5);
});

test('detectPeaks: composite max-envelope across lines', () => {
  const a = threePeakLine();
  // Second line with one big extra peak at 650 Hz.
  const N = a.x.length;
  const y2 = new Float64Array(N);
  for (let i = 0; i < N; i++) y2[i] = 60 / (1 + ((a.x[i] - 650) / 10) ** 2);
  const peaks = detectPeaks([a, { x: a.x, y: y2 }], [0, 1000]);
  expect(peaks.some((p) => Math.abs(p - 650) < 5)).toBe(true);
  expect(peaks.some((p) => Math.abs(p - 470) < 5)).toBe(true);
});

test('detectPeaks: degenerate input → []', () => {
  expect(detectPeaks([], [0, 1000])).toEqual([]);
  expect(detectPeaks([threePeakLine()], [500, 500])).toEqual([]);
  const flat = { x: new Float64Array([0, 1, 2]), y: new Float64Array([1, 1, 1]) };
  expect(detectPeaks([flat], [0, 2])).toEqual([]);
});

test('stepWindow: keep-width, centred on the next peak beyond the centre', () => {
  const peaks = [120, 470, 810];
  const next = stepWindow(peaks, [100, 300], [0, 1000], 1);   // centre 200, width 200
  expect(next).not.toBeNull();
  expect(next![1] - next![0]).toBeCloseTo(200, 6);
  expect((next![0] + next![1]) / 2).toBeCloseTo(470, 6);
  const prev = stepWindow(peaks, [400, 540], [0, 1000], -1);  // centre 470 → back to 120
  expect((prev![0] + prev![1]) / 2).toBeCloseTo(120, 6);
});

test('stepWindow clamps into the scope (hugs the edge, width kept)', () => {
  const next = stepWindow([950], [500, 900], [0, 1000], 1);   // centred window would overhang
  expect(next).toEqual([600, 1000]);
});

test('stepWindow: no further peak → null (disable the button)', () => {
  expect(stepWindow([120, 470], [400, 540], [0, 1000], 1)).toBeNull();   // centre 470, none beyond
  expect(stepWindow([470], [400, 540], [0, 1000], -1)).toBeNull();
  expect(stepWindow([], [0, 100], [0, 1000], 1)).toBeNull();
});

test('stepWindow: a clamped-at-edge window skips to a genuinely different window', () => {
  // Window already hugging the hi edge, its centre (800) below the only peak (950):
  // re-targeting 950 reproduces the same clamped window → must return null, not loop.
  expect(stepWindow([950], [600, 1000], [0, 1000], 1)).toBeNull();
});

test('stepWindow: window ≥90% of scope steps at scope/10 width (the "home" rule)', () => {
  // Window [0,900] spans exactly 90% ⇒ home rule; its centre (450) is below
  // the peak (470), so › targets it at the reduced width.
  const next = stepWindow([470], [0, 900], [0, 1000], 1);
  expect(next![1] - next![0]).toBeCloseTo(100, 6);
  expect((next![0] + next![1]) / 2).toBeCloseTo(470, 6);
});

test('stepWindow log mode preserves width as a RATIO (brush translate semantics)', () => {
  const next = stepWindow([100, 400], [80, 125], [10, 1000], 1, true);  // ratio 125/80
  expect(next).not.toBeNull();
  expect(next![1] / next![0]).toBeCloseTo(125 / 80, 6);
  expect(Math.sqrt(next![0] * next![1])).toBeCloseTo(400, 4);           // log-centred on the peak
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `npx vitest run tests/plot/peaks.test.ts`
Expected: FAIL — cannot resolve `../../src/lib/plot/peaks`.

- [ ] **Step 3: Implement** — create `webui/src/lib/plot/peaks.ts`:

```ts
/**
 * Peak detection + peak-step targeting for the frequency navigator
 * (dev/plans/2026-07-11-freq-navigator-design.md).
 *
 * Runs client-side on the navigator strip's own magnitude lines — no engine
 * round-trip. The composite max-envelope across all lines is binned onto a
 * uniform grid over the scope (uniform in log10 space when `log`), local
 * maxima are found on the compacted (gap-free) envelope, and each must clear
 * a prominence threshold measured as a fraction of the envelope's total
 * y-span — so noise ripple never becomes a "peak".
 */

/** One strip line: paired x (frequency, Hz) / y (magnitude, any units) arrays. */
export interface NavLine { x: ArrayLike<number>; y: ArrayLike<number>; }

/** Envelope grid resolution (bins across the scope). */
const N_BINS = 512;
/** Min peak prominence as a fraction of the envelope's y-span. */
const PROMINENCE_FRAC = 0.05;

/**
 * Detect peak frequencies (ascending, Hz) of the composite max-envelope of
 * `lines` within `scope`. `log` bins uniformly in log10(f) — pass the strip's
 * axis mode so detection resolution matches what the user sees. Degenerate
 * input (no lines, empty scope, flat envelope) returns `[]`.
 */
export function detectPeaks(lines: NavLine[], scope: [number, number], log = false): number[] {
  const [lo, hi] = scope;
  if (!(hi > lo) || lines.length === 0) return [];
  const L = log && lo > 0;
  const tLo = L ? Math.log10(lo) : lo;
  const tHi = L ? Math.log10(hi) : hi;

  // 1) composite max-envelope on a uniform grid (in axis space)
  const env = new Float64Array(N_BINS).fill(-Infinity);
  for (const l of lines) {
    const n = Math.min(l.x.length, l.y.length);
    for (let i = 0; i < n; i++) {
      const x = l.x[i], y = l.y[i];
      if (!Number.isFinite(x) || !Number.isFinite(y) || x < lo || x > hi) continue;
      const t = L ? Math.log10(x) : x;
      const b = Math.min(N_BINS - 1, Math.max(0, Math.floor(((t - tLo) / (tHi - tLo)) * N_BINS)));
      if (y > env[b]) env[b] = y;
    }
  }

  // 2) compact away empty bins (sparse data ⇒ gaps; local-max tests need neighbours)
  const ys: number[] = [], centres: number[] = [];
  for (let b = 0; b < N_BINS; b++) {
    if (env[b] === -Infinity) continue;
    ys.push(env[b]);
    const tc = tLo + ((b + 0.5) / N_BINS) * (tHi - tLo);
    centres.push(L ? 10 ** tc : tc);
  }
  if (ys.length < 3) return [];
  let yMin = Infinity, yMax = -Infinity;
  for (const y of ys) { if (y < yMin) yMin = y; if (y > yMax) yMax = y; }
  const minProm = (yMax - yMin) * PROMINENCE_FRAC;
  if (!(minProm > 0)) return [];   // flat envelope

  // 3) local maxima + prominence: walk each side to the nearest HIGHER sample
  //    (or the end), tracking the valley minimum; prominence = peak − the
  //    higher of the two valley minima (the standard definition).
  const peaks: number[] = [];
  for (let i = 1; i < ys.length - 1; i++) {
    if (!(ys[i] > ys[i - 1] && ys[i] >= ys[i + 1])) continue;
    let lMin = ys[i], rMin = ys[i];
    for (let j = i - 1; j >= 0; j--) { if (ys[j] > ys[i]) break; if (ys[j] < lMin) lMin = ys[j]; }
    for (let j = i + 1; j < ys.length; j++) { if (ys[j] > ys[i]) break; if (ys[j] < rMin) rMin = ys[j]; }
    if (ys[i] - Math.max(lMin, rMin) >= minProm) peaks.push(centres[i]);
  }
  return peaks;
}

/**
 * The window produced by ONE peak-step press: centre the current window
 * (width kept — as a log10 RATIO when `log`, matching the brush's translate
 * semantics) on the nearest peak beyond the window centre in direction `dir`,
 * clamped inside `scope` (hugging the edge, width preserved). Candidates
 * whose clamped window reproduces the CURRENT window are skipped (an
 * edge-clamped window must not re-target the same peak forever). Returns
 * `null` when no candidate yields a different window ⇒ disable the button.
 *
 * Special case (the "home" rule): a window spanning ≥90% of the scope — where
 * keep-width is meaningless — steps at scope-span/10 width instead.
 */
export function stepWindow(
  peaks: number[],
  window: [number, number],
  scope: [number, number],
  dir: 1 | -1,
  log = false,
): [number, number] | null {
  const [sLo, sHi] = scope;
  if (!(sHi > sLo) || peaks.length === 0) return null;
  const L = log && sLo > 0;
  const fwd = (v: number) => (L ? Math.log10(v) : v);
  const inv = (t: number) => (L ? 10 ** t : t);
  const tSLo = fwd(sLo), tSHi = fwd(sHi);
  const span = tSHi - tSLo;

  let width = fwd(window[1]) - fwd(window[0]);
  let centre = (fwd(window[0]) + fwd(window[1])) / 2;
  if (!Number.isFinite(width) || width <= 0 || width >= 0.9 * span) width = span / 10;
  if (!Number.isFinite(centre)) centre = (tSLo + tSHi) / 2;

  const cands = peaks.map(fwd)
    .filter((t) => Number.isFinite(t) && t >= tSLo && t <= tSHi)
    .filter((t) => (dir === 1 ? t > centre : t < centre))
    .sort((a, b) => (dir === 1 ? a - b : b - a));

  const tol = (sHi - sLo) * 1e-6;
  for (const t of cands) {
    let lo = t - width / 2, hi = t + width / 2;
    if (width >= span) { lo = tSLo; hi = tSHi; }
    else if (lo < tSLo) { lo = tSLo; hi = tSLo + width; }
    else if (hi > tSHi) { hi = tSHi; lo = tSHi - width; }
    const out: [number, number] = [inv(lo), inv(hi)];
    if (Math.abs(out[0] - window[0]) > tol || Math.abs(out[1] - window[1]) > tol) return out;
  }
  return null;
}
```

- [ ] **Step 4: Run tests**

Run: `npx vitest run tests/plot/peaks.test.ts`
Expected: ALL PASS. (If the 3-peak detection is off: the test's ripple amplitude 1.5 vs peak 55 is far below the 5% prominence gate — debug the envelope/prominence code, do NOT weaken the test.)

- [ ] **Step 5: Type-check + commit**

Run: `npm run check` — expected 0/0.

```bash
git add webui/src/lib/plot/peaks.ts webui/tests/plot/peaks.test.ts
git commit -m "feat(webui): client-side peak detection + step targeting for the freq navigator

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `FreqNavigator.svelte` — scope domain, ribbon, ⤢, home

**Files:**
- Create: `webui/src/components/FreqNavigator.svelte` via `git mv webui/src/components/NyquistBrush.svelte webui/src/components/FreqNavigator.svelte`
- (App.svelte still imports NyquistBrush after this task — `npm run check` will fail until Task 5. That is expected; gate this task on vitest only and note it in the commit.)

Work from the moved file. It currently maps everything against `fullExtent`; the core change is a `domain = scope ?? fullExtent` indirection plus the new chrome.

- [ ] **Step 1: Rename + reprops.** Update the header docstring: it is now the FREQUENCY NAVIGATOR for all frequency-x views (frequency + every tf plotType; the Nyquist view mounts it as before) per `dev/plans/2026-07-11-freq-navigator-design.md`; keep the brush-history paragraphs (v2 live re-windowing, drag-anchor rationale). Replace the props block with:

```ts
  let {
    lines,
    fullExtent,
    band,
    scope = null,
    xScale = 'lin',
    modeTicks = [],
    onchange,
    onpreview,
    onstart,
    oncancel,
    onhome,
    onscope,
  }: {
    /** Magnitude lines (y in the strip's own units) over the FULL extent. */
    lines: StripLine[];
    /** Full frequency extent [fmin, fmax] of the data. */
    fullExtent: [number, number];
    /** Current committed frequency window [lo, hi] (the highlighted band). */
    band: [number, number];
    /** Bandwidth-of-interest the strip spans; null ⇒ full extent (no ribbon). */
    scope?: [number, number] | null;
    /** Frequency axis scale, matched to the main plot's x scale. */
    xScale?: 'lin' | 'log';
    /** Fitted-mode markers (fn in Hz + muted flag); empty ⇒ no ticks. */
    modeTicks?: { fn: number; muted: boolean }[];
    /** Fired once on release (numeric-field commit / peak-step) with the new window. */
    onchange: (lo: number, hi: number) => void;
    /** Per-animation-frame live band while dragging (no history entry). */
    onpreview?: (lo: number, hi: number) => void;
    /** Fired at drag start so the parent can open a transient (one-undo) gesture. */
    onstart?: () => void;
    /** Fired when a drag is abandoned — parent reverts any live preview. */
    oncancel?: () => void;
    /** Double-click the strip: window → scope (or full extent when unscoped). */
    onhome: () => void;
    /** Scope commit: ⤢ button / ribbon drag release; null clears the scope. */
    onscope: (s: [number, number] | null) => void;
  } = $props();
```

- [ ] **Step 2: Domain indirection.** Immediately after the constants block add:

```ts
  /** The interval the strip spans: the scope, else the full extent. */
  const domain = $derived<[number, number]>(scope ?? fullExtent);
```

Then mechanically replace `fullExtent` with `domain` in: the `log`/`lfmin`/`lfmax` deriveds, `toPx`, `toF`, and the two end tick `<text>` labels. (`fullExtent` remains in use only by the ribbon, Step 4.) In `pathFor`, skip samples outside the domain so a scoped strip doesn't pile clamped points at its edges:

```ts
      if (l.x[i] < domain[0] || l.x[i] > domain[1]) continue;
```

(add as the first line of the loop body). Likewise restrict `yExtent` to in-domain samples so the strip auto-scales to what it shows — change its inner loop to iterate `i` over `l.x`/`l.y` pairs and `continue` when `l.x[i]` is outside `domain` (same guard), keeping the finite-check on `l.y[i]`.

- [ ] **Step 3: Head controls.** In the markup, replace `ondblclick={onfull}` with `ondblclick={onhome}` (and delete the old `onfull` prop — it no longer exists). In `.brush-head`, after `.brush-lab`, insert the button cluster (peak-step buttons come in Task 4 — add the ⤢ now):

```svelte
    <span class="nav-btns">
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-scope-btn"
        title="Scope the strip to the current window (double-click the ribbon to clear)"
        onclick={() => onscope([band[0], band[1]])}
      >⤢</button>
    </span>
```

with styles (append to the `<style>` block):

```css
  .nav-btns { display: inline-flex; align-items: center; gap: 2px; }
  .nbtn {
    width: 22px; height: 20px;
    border: 1px solid var(--border, #e3e6eb);
    border-radius: 5px;
    background: var(--control-bg, #fff);
    color: var(--muted, #66708a);
    font: 12px/1 var(--font-body, system-ui, sans-serif);
    cursor: pointer;
    padding: 0;
  }
  .nbtn:hover:not(:disabled) { color: var(--text, #1b2437); border-color: var(--accent-soft-border, #c7d2fe); }
  .nbtn:disabled { opacity: 0.35; cursor: default; }
```

- [ ] **Step 4: Scope ribbon.** Above the strip `{#if width > 0}` block, render when scoped. Full markup + logic:

```svelte
{#if scope && width > 0}
  <!-- Context ribbon: full extent in miniature, the scope highlighted. Body
       drag translates, edge drag resizes, double-click clears the scope.
       Local preview only; onscope fires once on release (scope is not
       undoable, so no transient protocol needed). -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <svg
    class="ribbon"
    viewBox="0 0 {width} {RH}"
    height={RH}
    data-testid="freq-nav-ribbon"
    style="cursor: {ribbonCursor}"
    aria-label="Scope: {shownScope[0].toFixed(1)} to {shownScope[1].toFixed(1)} Hz of {fullExtent[0].toFixed(1)}–{fullExtent[1].toFixed(1)} Hz"
    onpointerdown={rbDown}
    onpointermove={rbMove}
    onpointerup={rbUp}
    onpointercancel={rbCancel}
    ondblclick={() => onscope(null)}
  >
    <rect class="strip-bg" x={PAD_L} y={1} width={innerW} height={RH - 2} />
    <rect class="mask" x={PAD_L} y={1} width={Math.max(0, rLoPx - PAD_L)} height={RH - 2} />
    <rect class="mask" x={rHiPx} y={1} width={Math.max(0, PAD_L + innerW - rHiPx)} height={RH - 2} />
    <rect class="rband" data-testid="freq-nav-ribbon-band"
      x={rLoPx} y={1} width={Math.max(1, rHiPx - rLoPx)} height={RH - 2} />
  </svg>
{/if}
```

Ribbon script (add after the numeric-fields section). It maps against `fullExtent` with the same lin/log rule as the strip:

```ts
  // ── scope ribbon (full-extent miniature; only rendered when scoped) ──
  const RH = 14;                     // ribbon height (px)
  const rLog = $derived(xScale === 'log' && fullExtent[0] > 0 && fullExtent[1] > 0);
  const rlMin = $derived(rLog ? Math.log10(fullExtent[0]) : 0);
  const rlMax = $derived(rLog ? Math.log10(fullExtent[1]) : 1);

  function toPxR(f: number): number {
    const [fmin, fmax] = fullExtent;
    const t = rLog
      ? (Math.log10(Math.max(f, fmin)) - rlMin) / (rlMax - rlMin || 1)
      : (f - fmin) / (fmax - fmin || 1);
    return PAD_L + Math.min(1, Math.max(0, t)) * innerW;
  }
  function toFR(px: number): number {
    const [fmin, fmax] = fullExtent;
    const t = Math.min(1, Math.max(0, (px - PAD_L) / (innerW || 1)));
    const f = rLog ? 10 ** (rlMin + t * (rlMax - rlMin)) : fmin + t * (fmax - fmin);
    return Math.min(fmax, Math.max(fmin, f));
  }

  type RbZone = 'move' | 'resize-lo' | 'resize-hi' | null;
  let rbMode = $state<RbZone>(null);
  let rbPointer = 0;
  let rbGrabOffset = 0;
  let rbBaseLo = 0, rbBaseHi = 0;
  let rbPreview = $state<[number, number] | null>(null);
  let rbHover = $state<RbZone>(null);

  const shownScope = $derived<[number, number]>(rbPreview ?? (scope ?? fullExtent));
  const rLoPx = $derived(toPxR(shownScope[0]));
  const rHiPx = $derived(toPxR(shownScope[1]));

  function rbZoneAt(px: number): RbZone {
    if (!scope) return null;
    const lo = toPxR(scope[0]), hi = toPxR(scope[1]);
    const edge = Math.min(HANDLE_PX, (hi - lo) * 0.25);
    if (hi - lo > 6 && Math.abs(px - lo) <= edge) return 'resize-lo';
    if (hi - lo > 6 && Math.abs(px - hi) <= edge) return 'resize-hi';
    if (px >= lo && px <= hi) return 'move';
    return null;
  }
  const ribbonCursor = $derived.by(() => {
    const z = rbMode ?? rbHover;
    if (z === 'move') return rbMode ? 'grabbing' : 'grab';
    if (z === 'resize-lo' || z === 'resize-hi') return 'ew-resize';
    return 'default';
  });

  function rbLocalX(e: PointerEvent): number {
    const el = e.currentTarget as SVGSVGElement;
    const r = el.getBoundingClientRect();
    const sx = r.width ? width / r.width : 1;
    return (e.clientX - r.left) * sx;
  }
  function rbDown(e: PointerEvent) {
    if (e.button !== 0 || !scope) return;
    const px = rbLocalX(e);
    const z = rbZoneAt(px);
    if (!z) return;
    rbMode = z; rbBaseLo = scope[0]; rbBaseHi = scope[1];
    rbGrabOffset = px - toPxR(scope[0]);
    rbPreview = [rbBaseLo, rbBaseHi];
    rbPointer = e.pointerId;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }
  function rbMove(e: PointerEvent) {
    if (rbMode === null) { rbHover = rbZoneAt(rbLocalX(e)); return; }
    if (e.pointerId !== rbPointer) return;
    const px = rbLocalX(e);
    const f = toFR(px);
    const [fmin, fmax] = fullExtent;
    let lo = rbBaseLo, hi = rbBaseHi;
    if (rbMode === 'resize-lo') lo = Math.min(f, rbBaseHi);
    else if (rbMode === 'resize-hi') hi = Math.max(f, rbBaseLo);
    else {
      const basePxW = toPxR(rbBaseHi) - toPxR(rbBaseLo);
      const newLoPx = px - rbGrabOffset;
      lo = toFR(newLoPx); hi = toFR(newLoPx + basePxW);
      if (hi >= fmax) { hi = fmax; lo = toFR(toPxR(fmax) - basePxW); }
      if (lo <= fmin) { lo = fmin; hi = toFR(toPxR(fmin) + basePxW); }
    }
    rbPreview = [Math.max(fmin, lo), Math.min(fmax, hi)];
  }
  function rbUp(e: PointerEvent) {
    if (rbMode === null || e.pointerId !== rbPointer) return;
    try { (e.currentTarget as Element).releasePointerCapture(e.pointerId); } catch { /* released */ }
    const p = rbPreview;
    rbMode = null; rbPointer = 0; rbPreview = null;
    if (!p || !(p[1] > p[0])) return;
    if (p[0] === rbBaseLo && p[1] === rbBaseHi) return;   // click / no-move
    onscope(p);
  }
  function rbCancel(e: PointerEvent) {
    if (e.pointerId !== rbPointer) return;
    rbMode = null; rbPointer = 0; rbPreview = null;
  }
```

Ribbon styles (append):

```css
  .ribbon { display: block; width: 100%; touch-action: none; margin-bottom: 2px; }
  .rband {
    fill: var(--indigo, #4f46e5);
    fill-opacity: 0.22;
    stroke: var(--indigo, #4f46e5);
    stroke-opacity: 0.7;
    stroke-width: 1;
  }
```

- [ ] **Step 5: Off-scope window arrows.** After the band/handles group in the strip SVG add:

```svelte
      <!-- The committed window lies (partly) beyond the scoped strip: point at it. -->
      {#if band[1] < domain[0]}
        <path class="offscope" data-testid="freq-nav-offscope"
          d="M{PAD_L + 12},{TOP + plotH / 2 - 5} l-7,5 l7,5 z" />
      {:else if band[0] > domain[1]}
        <path class="offscope" data-testid="freq-nav-offscope"
          d="M{PAD_L + innerW - 12},{TOP + plotH / 2 - 5} l7,5 l-7,5 z" />
      {/if}
```

```css
  .offscope { fill: var(--indigo, #4f46e5); opacity: 0.8; pointer-events: none; }
```

- [ ] **Step 6: Testid + label sweep.** In this file rename every `data-testid`: `nyquist-brush` → `freq-nav`, `nyquist-brush-min` → `freq-nav-min`, `nyquist-brush-max` → `freq-nav-max`, `nyquist-brush-band` → `freq-nav-band`, `nyquist-brush-handle-lo/hi` → `freq-nav-handle-lo/hi`. Keep the visible label `frequency band`.

- [ ] **Step 7: Vitest + commit** (`npm run check` is EXPECTED to fail until Task 5 rewires App — do not chase it now):

Run: `npx vitest run` — expected: all pass (no component unit tests; this catches accidental lib breakage).

```bash
git add -A webui/src/components/FreqNavigator.svelte webui/src/components/NyquistBrush.svelte
git commit -m "feat(webui): FreqNavigator — NyquistBrush + scope domain, ribbon, scope-to-window, home

App still imports NyquistBrush; npm run check red until the wiring lands (next commits).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: FreqNavigator — peak-step buttons + mode ticks

**Files:**
- Modify: `webui/src/components/FreqNavigator.svelte`

- [ ] **Step 1: Peak-step wiring.** Import at the top of the script:

```ts
  import { detectPeaks, stepWindow } from '../lib/plot/peaks';
```

Add deriveds (after `domain`):

```ts
  // Peak-step targets (design §peak-stepping): detection runs on the strip's
  // own lines within the domain; a null target disables that button. Uses the
  // COMMITTED band (not the live preview) so targets are stable mid-drag.
  const peaks = $derived(detectPeaks(lines, domain, log));
  const prevTarget = $derived(stepWindow(peaks, band, domain, -1, log));
  const nextTarget = $derived(stepWindow(peaks, band, domain, 1, log));
```

In `.nav-btns`, BEFORE the ⤢ button, add:

```svelte
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-prev"
        title="Previous peak (window keeps its width)"
        disabled={!prevTarget}
        onclick={() => prevTarget && onchange(prevTarget[0], prevTarget[1])}
      >‹</button>
      <button
        class="nbtn"
        type="button"
        data-testid="freq-nav-next"
        title="Next peak (window keeps its width)"
        disabled={!nextTarget}
        onclick={() => nextTarget && onchange(nextTarget[0], nextTarget[1])}
      >›</button>
```

- [ ] **Step 2: Mode ticks.** In the strip SVG, after the edge-tick `<text>` labels, add:

```svelte
      <!-- Fitted-mode markers: one triangle per mode fn inside the domain
           (dimmed when muted) — the strip doubles as a mode map. -->
      {#each modeTicks as t, i (i)}
        {#if t.fn >= domain[0] && t.fn <= domain[1]}
          <path class="mtick" class:muted={t.muted} data-testid="freq-nav-tick"
            d="M{toPx(t.fn)},{TOP + 7} l-4,-7 l8,0 z" />
        {/if}
      {/each}
```

```css
  .mtick { fill: var(--indigo, #4f46e5); opacity: 0.85; pointer-events: none; }
  .mtick.muted { opacity: 0.3; }
```

- [ ] **Step 3: Vitest + commit** (`npm run check` still red on App's stale import — expected):

Run: `npx vitest run` — expected: all pass.

```bash
git add webui/src/components/FreqNavigator.svelte
git commit -m "feat(webui): FreqNavigator peak-step buttons + fitted-mode ticks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: App + ZoomToolbar wiring

**Files:**
- Modify: `webui/src/App.svelte` (imports ~line 28; deriveds ~lines 780–812; template blocks ~lines 1139–1200)
- Modify: `webui/src/components/ZoomToolbar.svelte`

- [ ] **Step 1: ZoomToolbar toggle.** Add three props to the props type + destructuring (after `freqExtent`):

```ts
    /**
     * Show the frequency-navigator toggle (freq-navigator design 2026-07-11).
     * App passes true on the frequency/tf views; the button reports state via
     * `navOpen` and flips it through `onnavtoggle` (the state itself lives in
     * the view slice's `navigator` override — resolved in App).
     */
    navControl?: boolean;
    /** Current navigator visibility (drives aria-pressed / the active style). */
    navOpen?: boolean;
    /** Toggle callback — App writes `viewState.setNavigator(view, !navOpen)`. */
    onnavtoggle?: () => void;
```

with defaults `navControl = false, navOpen = false, onnavtoggle = undefined` in the destructuring. Then find the main button row in the markup (the bar with the undo/redo `↶ ↷` buttons and the box/pan mode buttons — grep `zbtn`) and add, as the FIRST button in the row, matching the existing `.zbtn` button structure exactly (same class, same `title`/`aria-label` pattern as its siblings):

```svelte
    {#if navControl}
      <button
        class="zbtn"
        class:active={navOpen}
        type="button"
        data-testid="freq-nav-toggle"
        title={navOpen ? 'Hide frequency navigator' : 'Show frequency navigator'}
        aria-pressed={navOpen}
        onclick={() => onnavtoggle?.()}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <rect x="1.5" y="5" width="13" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.4" />
          <rect x="6" y="5" width="4" height="6" fill="currentColor" opacity="0.6" />
        </svg>
      </button>
    {/if}
```

If `.zbtn` has no existing `active` modifier class, add one consistent with the toolbar's mode buttons (they highlight the active box/pan tool — reuse that exact class/style instead of inventing one).

- [ ] **Step 2: App deriveds.** In `webui/src/App.svelte`: swap the import `NyquistBrush` → `FreqNavigator` (same path pattern). Replace the whole `nyquistMagModel` derived (~line 790) and extend around it:

```ts
  // ── Frequency navigator (dev/plans/2026-07-11-freq-navigator-design.md) ──
  // Which views carry it, and whether it is open: an explicit per-view
  // override (`slice.navigator`, the toolbar toggle) wins; auto (null) opens
  // it in the Fit stage and on Nyquist — where the strip is the primary
  // frequency control (it replaced the round-5 NyquistBrush) — else closed.
  const navView = $derived(view === 'frequency' || view === 'tf');
  const navOpen = $derived(
    navView && ($currentSlice.navigator ?? ($activeStage === 'fit' || nyquist)),
  );

  /**
   * Full-extent magnitude model feeding the navigator strip: the |H|(f) (tf)
   * or FFT/PSD magnitude (frequency view) lines over the WHOLE frequency
   * axis (no window, no committed range), reusing the plot builders so the
   * column remap + cal ratio match the plot. yScale is pinned 'log' (dB) for
   * shape legibility. Built only while the navigator is open.
   */
  const navModel = $derived<PlotModel | null>(
    navOpen
      ? buildPlotModel(
          view === 'tf'
            ? { view: 'tf', sets: setArrays, visible, tfPlotType: 'mag', coherence: false,
                freqRange: null, range: { x: null, y: null }, xScale, yScale: 'log' }
            : { view: 'frequency', sets: setArrays, visible, freqMode, coherence: false,
                freqRange: null, range: { x: null, y: null }, xScale, yScale: 'log' },
        )
      : null,
  );
```

(Check `buildPlotModel`'s frequency-view options in `lib/plot/build.ts` before writing the `'frequency'` branch — pass exactly the fields the main `model` derived passes for that view, minus range/freqRange, plus `yScale: 'log'`. If `freqMode === 'csd'` produces no magnitude lines, that is fine — the strip just renders empty; do not special-case it.)

Update `freqExtent` / `brushBand` to read `navModel` instead of `nyquistMagModel` (same logic). Then add the scope plumbing:

```ts
  const freqScopeStore = viewState.freqScope;
  /**
   * The effective scope: the stored value clamped to the current data extent
   * (loads/appends move the extent), degenerate or ≈full-span ⇒ null
   * (unscoped — a full-width scope must not summon a no-op ribbon).
   */
  const scope = $derived.by<[number, number] | null>(() => {
    const raw = $freqScopeStore;
    if (!raw || !freqExtent) return null;
    const lo = Math.max(raw[0], freqExtent[0]);
    const hi = Math.min(raw[1], freqExtent[1]);
    if (!(hi > lo)) return null;
    const span = freqExtent[1] - freqExtent[0];
    if (lo - freqExtent[0] < 0.001 * span && freqExtent[1] - hi < 0.001 * span) return null;
    return [lo, hi];
  });

  /** Commit a scope from the navigator (⤢ / ribbon), normalising ≈full → clear. */
  function commitScope(s: [number, number] | null) {
    if (!s || !freqExtent) { viewState.setFreqScope(null); return; }
    const span = freqExtent[1] - freqExtent[0];
    if (s[0] - freqExtent[0] < 0.001 * span && freqExtent[1] - s[1] < 0.001 * span) {
      viewState.setFreqScope(null);
      return;
    }
    viewState.setFreqScope([s[0], s[1]]);
  }

  /** Fitted-mode markers for the navigator strip (empty until a fit exists). */
  const modeTicks = $derived($modal.modes.map((m, i) => ({ fn: m.fn, muted: !!$modal.muted[i] })));
```

(If `$modal` is not already used in App.svelte's script, this `$`-subscription is still valid — `modal` is a store-shaped object, exactly how `FitChip` consumes it.)

- [ ] **Step 3: Mount snippet.** In the template, define once (above the plot-host blocks):

```svelte
  {#snippet freqNav()}
    {#if navOpen && freqExtent && brushBand && navModel}
      <FreqNavigator
        lines={navModel.lines}
        fullExtent={freqExtent}
        band={brushBand}
        {scope}
        {xScale}
        {modeTicks}
        onstart={() => viewState.beginTransient(view)}
        onpreview={(lo, hi) => viewState.setRangeLive(view, { x: [lo, hi], y: range.y })}
        onchange={(lo, hi) => viewState.commitTransient(view, { x: [lo, hi], y: range.y })}
        oncancel={() => viewState.cancelTransient(view)}
        onhome={() => {
          const h = scope ?? freqExtent;
          if (h) viewState.setRange(view, { x: [h[0], h[1]], y: range.y });
        }}
        onscope={commitScope}
      />
    {/if}
  {/snippet}
```

Then:
- **Nyquist block** (~line 1145): DELETE the whole `<NyquistBrush …/>` element (including its `{#if freqExtent && brushBand && nyquistMagModel}` wrapper) and put `{@render freqNav()}` in its place.
- **Bode block**: insert `{@render freqNav()}` immediately after its `.plot-nav` div (before the first `.bode-pane`).
- **Default block** (the final `{:else}` `.plot-host.navved` — it also hosts the time view, where `navOpen` is always false): insert `{@render freqNav()}` immediately after its `.plot-nav` div.

- [ ] **Step 4: Toolbar props.** On the ZoomToolbar instances in the nyquist, bode, and default blocks (NOT sono), add:

```svelte
navControl={navView} navOpen={navOpen} onnavtoggle={() => viewState.setNavigator(view, !navOpen)}
```

- [ ] **Step 5: Layout check.** The bode host is `display:flex; flex-direction:column` and the default host gets `.navved` (also a column); the navigator's root `.brush` is `flex: 0 0 auto`, so it slots in without CSS changes. Verify visually in Step 6 — if the navigator stretches or overlaps, fix at the host level the way `.plot-host.nyquist` does (it keeps the strip and plot as siblings in a transparent column).

- [ ] **Step 6: Check + eyeball.**

Run: `npm run check` — expected 0/0 (the Task-3/4 debt clears here).
Run: `npx vitest run` — all pass.
Then start the dev server and verify by hand (load `http://localhost:5173/?fixture=1` in a browser): TF-mag view → toolbar toggle shows/hides the strip; band drag re-windows live; ⤢ scopes + ribbon appears; ribbon double-click clears; ‹ › step between the fixture's resonances; Nyquist view still shows the strip by default.

- [ ] **Step 7: Commit**

```bash
git add webui/src/App.svelte webui/src/components/ZoomToolbar.svelte
git commit -m "feat(webui): mount the frequency navigator on freq/tf views + toolbar toggle

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: e2e coverage

**Files:**
- Modify: `webui/e2e/axis-nav.spec.ts` (testid rename only)
- Create: `webui/e2e/freq-nav.spec.ts`
- Modify: `webui/e2e/fit.spec.ts` (one assertion block)

- [ ] **Step 1: Port the Nyquist brush testids.** In `webui/e2e/axis-nav.spec.ts` replace every `nyquist-brush` with `freq-nav` (9 occurrences: `nyquist-brush`, `-band`, `-min`, `-max` forms).

Run: `npx playwright test e2e/axis-nav.spec.ts` — expected: all pass (the Nyquist strip is auto-open there, so behaviour is unchanged).

- [ ] **Step 2: New spec.** Create `webui/e2e/freq-nav.spec.ts`:

```ts
import { expect, test, type Page } from '@playwright/test';

/**
 * Frequency navigator (dev/plans/2026-07-11-freq-navigator-design.md).
 * NON-ENGINE: `?fixture=1` seeds a TfData on load (several evenly-spaced
 * resonances), so the TF view has real lines without booting pyodide.
 * Covers: the toolbar toggle; band-drag → live re-window + ONE history
 * entry; ⤢ scope + ribbon + double-click clear (via the `freqScope` store
 * hook); peak-step keep-width; Fit-stage auto-open.
 */

/** Read {range.x, historyLen} of the tf slice via the ?fixture=1 hook. */
async function tfRange(page: Page): Promise<{ x: [number, number] | null; historyLen: number }> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      current: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('window.__viewState hook missing (need ?fixture=1)');
    let raw: { range: { x: [number, number] | null }; history: unknown[] } | null = null;
    vs.current.subscribe((v) => { raw = v as typeof raw; })();
    const s = raw as NonNullable<typeof raw>;
    return { x: s.range.x, historyLen: s.history.length };
  });
}

/** Read the shared freqScope store via the hook. */
async function freqScope(page: Page): Promise<[number, number] | null> {
  return page.evaluate(() => {
    const vs = (window as unknown as { __viewState?: {
      freqScope: { subscribe: (f: (v: unknown) => void) => () => void };
    } }).__viewState;
    if (!vs) throw new Error('hook missing');
    let raw: [number, number] | null = null;
    vs.freqScope.subscribe((v) => { raw = v as typeof raw; })();
    return raw;
  });
}

/** Load the fixture and switch to the TF stage (tf-mag plot, no engine). */
async function openTf(page: Page): Promise<void> {
  await page.goto('/?fixture=1');
  await expect(page.getByTestId('tray-card-0')).toBeVisible();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'TF' }).click();
  await expect(page.getByTestId('plot-line').first()).toBeAttached();
  await expect.poll(() => page.evaluate(() =>
    !!(window as unknown as { __viewState?: unknown }).__viewState)).toBe(true);
}

/** Type an exact window into the navigator's numeric fields. */
async function setWindow(page: Page, lo: number, hi: number): Promise<void> {
  await page.getByTestId('freq-nav-min').fill(String(lo));
  await page.getByTestId('freq-nav-min').press('Enter');
  await page.getByTestId('freq-nav-max').fill(String(hi));
  await page.getByTestId('freq-nav-max').press('Enter');
}

test('hidden by default on TF-mag; toggle shows it; band drag = one undo entry', async ({ page }) => {
  await openTf(page);
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
  await page.getByTestId('freq-nav-toggle').click();
  await expect(page.getByTestId('freq-nav')).toBeVisible();

  const before = await tfRange(page);
  const band = page.getByTestId('freq-nav-band');
  const box = (await band.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 60, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  const after = await tfRange(page);
  expect(after.historyLen).toBe(before.historyLen + 1);   // whole drag = ONE entry
  expect(after.x).not.toEqual(before.x);

  await page.getByTestId('freq-nav-toggle').click();
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
});

test('scope: ⤢ scopes to the window, ribbon appears; double-click clears', async ({ page }) => {
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 250, 750);
  await expect(page.getByTestId('freq-nav-ribbon')).not.toBeAttached();
  await page.getByTestId('freq-nav-scope-btn').click();
  await expect(page.getByTestId('freq-nav-ribbon')).toBeVisible();
  const s = await freqScope(page);
  expect(s).not.toBeNull();
  expect(Math.abs(s![0] - 250)).toBeLessThan(1);
  expect(Math.abs(s![1] - 750)).toBeLessThan(1);
  await page.getByTestId('freq-nav-ribbon').dblclick();
  await expect(page.getByTestId('freq-nav-ribbon')).not.toBeAttached();
  expect(await freqScope(page)).toBeNull();
});

test('peak-step › keeps the window width and moves it forward', async ({ page }) => {
  await openTf(page);
  await page.getByTestId('freq-nav-toggle').click();
  await setWindow(page, 50, 250);                        // width 200, low in the band
  const before = await tfRange(page);
  const width = before.x![1] - before.x![0];
  await page.getByTestId('freq-nav-next').click();
  const after = await tfRange(page);
  expect(after.x![1] - after.x![0]).toBeCloseTo(width, 0);         // keep-width
  expect((after.x![0] + after.x![1]) / 2)
    .toBeGreaterThan((before.x![0] + before.x![1]) / 2);           // moved forward
  expect(after.historyLen).toBe(before.historyLen + 1);            // one undo per press
  // And back:
  await page.getByTestId('freq-nav-prev').click();
  const back = await tfRange(page);
  expect((back.x![0] + back.x![1]) / 2).toBeLessThan((after.x![0] + after.x![1]) / 2);
});

test('auto-opens in the Fit stage (navigator override unset)', async ({ page }) => {
  await openTf(page);
  await expect(page.getByTestId('freq-nav')).not.toBeAttached();
  await page.getByRole('navigation', { name: 'stages' }).getByRole('button', { name: 'Fit' }).click();
  await expect(page.getByTestId('freq-nav')).toBeVisible();
});
```

NOTE for the implementer: verify the fixture's TF actually has a peak above 250 Hz before trusting the peak-step test — run it; if `freq-nav-next` is disabled, inspect the seeded TF's resonance positions (grep the fixture-seeding code near `App.svelte:312`) and adjust the `setWindow` values so at least one peak lies beyond the initial window centre in each direction. Adjust the numbers, not the assertions.

- [ ] **Step 3: Run the new spec**

Run: `npx playwright test e2e/freq-nav.spec.ts` — expected: 4 passed.

- [ ] **Step 4: Mode ticks in the fit e2e.** In `webui/e2e/fit.spec.ts`, right after the Fit 2 assertions that establish two mode rows in the chip (find the first `expect` on the chip's mode rows after the Fit 2 click), add:

```ts
    // Freq-navigator mode ticks (2026-07-11 design): the Fit stage auto-opens
    // the navigator and each fitted fn marks the strip.
    await expect(page.getByTestId('freq-nav')).toBeVisible();
    await expect(page.getByTestId('freq-nav-tick')).toHaveCount(2);
```

- [ ] **Step 5: Run the engine spec** (SLOW — pyodide boot, ~3–5 min):

Run: `npx playwright test e2e/fit.spec.ts` — expected: pass.

- [ ] **Step 6: Commit**

```bash
git add webui/e2e/axis-nav.spec.ts webui/e2e/freq-nav.spec.ts webui/e2e/fit.spec.ts
git commit -m "test(webui): freq-navigator e2e — toggle, drag/undo, scope ribbon, peak-step, fit auto-open + mode ticks

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: docs + full-suite gate

**Files:**
- Modify: `docs/web-logger/analysis.md`, `docs/web-logger/modal-fitting.md`

- [ ] **Step 1: analysis.md.** Read the file first; place a `## Frequency navigator` section adjacent to the existing axis-navigation/zoom material (match the surrounding heading level and tone). Content to adapt:

```markdown
## Frequency navigator

On the Frequency and TF views the plot toolbar's navigator button opens a
slim strip above the plot: the magnitude of the visible lines over the whole
measured bandwidth, with a highlighted band showing the current frequency
window. Drag the band to skim along frequency (the plot follows live), drag
its edges to resize, drag on empty strip to draw a fresh window, or type
exact limits in the min–max fields. Double-click the strip to reset the
window. One drag is one undo step.

When the measurement carries more bandwidth than you care about, click ⤢ to
**scope** the strip to the current window: the strip re-scales to span just
that region and a thin ribbon appears above it showing where the scope sits
in the full bandwidth. Drag the ribbon's band to move or resize the scope;
double-click the ribbon to clear it. The scope only changes what the strip
spans — it never moves the window, feeds any calculation, or appears in
undo history (it is saved with your session).

The ‹ › buttons jump the window to the previous/next spectral peak, keeping
the window's width. Peaks are detected on the strip's own curves, so what
you see is what it steps between. The navigator opens automatically in the
Fit stage and on the Nyquist view; the toolbar button shows or hides it
anywhere else, and remembers your choice per view.
```

- [ ] **Step 2: modal-fitting.md.** Read the file; update its workflow description (the part that says to zoom into a peak and fit): the recommended loop is now *set the window on a peak (or press ›), Fit 1, press › to jump to the next peak, Fit 1 again* — and note that fitted modes appear as small markers on the navigator strip, so unmarked peaks are the ones still to fit. Keep the existing zoom instructions as an alternative; do not delete them.

- [ ] **Step 3: Docs gate**

Run from the repo root: `python -m mkdocs build --strict`
Expected: green (no warnings — strict fails on any).

- [ ] **Step 4: Full suites** (from `webui/`):

```
npm run check          # 0 errors 0 warnings
npx vitest run         # all pass (was 660/1 skipped at round 10)
npx playwright test    # all pass bar the known capability skips (was 81/7)
```

- [ ] **Step 5: Commit**

```bash
git add docs/web-logger/analysis.md docs/web-logger/modal-fitting.md
git commit -m "docs(web-logger): frequency navigator — skim, scope ribbon, peak-step fit workflow

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Self-review notes (already applied)

- Spec coverage: window/scope semantics (T1/T3/T5), ⤢ + ribbon + clear (T3/T5/T6), off-scope arrows (T3), peak-step incl. the 90% home rule + log-ratio width (T2/T4/T6), mode ticks (T4/T6), auto-open rule + toggle persistence (T1/T5/T6), Nyquist absorption + testid port (T3/T6), docs (T7). Sono intentionally absent (parked).
- The `onfull` prop is replaced by `onhome` — no stale references remain in App after Task 5.
- `npm run check` is deliberately red between Tasks 3–5 (App imports the moved component); the Task-3 commit message says so. Do not "fix" this early by half-wiring App.
