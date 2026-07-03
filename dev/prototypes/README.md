# Web UI prototypes

## `scope.html` — Stage 2 gate prototype

A self-contained Web Audio oscilloscope (one HTML file, vanilla JS, no
dependencies, no build step). It exists to answer the Stage 2 gate from
`dev/2026-07-01-web-ui-design.md`:

> **Gate criterion: a smooth ≥30 fps scrolling trace of live mic input
> in a real browser.** If this doesn't feel at least as good as the
> Qt/pyqtgraph Oscilloscope, the full web build doesn't start.

It also deliberately exercises the architecture the future NI bridge
will use: chunked producer (AudioWorklet on the audio thread, standing
in for the websocket) → `postMessage` → main-thread ring buffer →
`requestAnimationFrame` canvas render with min-max-per-pixel-column
decimation.

### Run

```bash
python3 -m http.server -d dev/prototypes 8905
# then open http://localhost:8905/scope.html
```

`getUserMedia` needs a secure context: `http://localhost` qualifies,
`file://` does not (the page detects this, disables the mic button and
says so). Synthetic mode works from anywhere.

### Use

- Click **Start — microphone input** (grant permission) or
  **Start — synthetic signal** (220 Hz + 3rd harmonic + noise with a
  slow amplitude wobble, generated inside the worklet so it flows
  through the identical pipeline). If the mic is denied or unavailable
  the page falls back to synthetic with a visible notice.
- Keys match the Qt oscilloscope: `T` / `F` / `L` toggle the time /
  frequency / levels panels (turning all three off is prevented, as in
  Qt), `P` pauses/resumes.
- `viewed time` selects the scrolling window: 0.3 / 1 / 2 s.
- The **Synthetic signal (no mic)** checkbox switches source live.

### Gate evidence

The status bar shows a rolling 1-s average **fps** (green when ≥30),
**p95** frame interval in ms, audio **sample rate**, worklet **chunk**
size, **dropped**-chunk count (sequence gaps in the worklet → main
thread stream), and the current **mode**. The same numbers are exposed
programmatically, refreshed every second:

```js
window.__scopeStats
// { fps, p95FrameMs, sampleRate, droppedChunks, mode, paused, viewedTime }
```

So a scripted check is e.g. (in the devtools console or via any
browser-automation tool):

```js
JSON.stringify(window.__scopeStats)
```

Pass = fps ≥ 30 sustained, p95 frame interval well under 33 ms, dropped
stays at 0, and — subjectively — the trace scrolls like an instrument,
not a slideshow.

### Implementation notes

- The time trace is a true scrolling ring-buffer view: samples are
  written into an 8 s `Float32Array` ring and each frame renders the
  window ending at a software display clock that advances at the sample
  rate and is gently servo-locked to the write head (so scrolling is
  smooth rather than jumping on ~5 ms chunk arrivals).
- Draw decimation is min-max per pixel column (peaks survive, like an
  oscilloscope) whenever window-samples > 2× canvas width.
- The spectrum is a Hann-windowed 4096-point radix-2 FFT implemented
  inline (the time path does not depend on `AnalyserNode`), log-mag dB,
  linear frequency axis to Nyquist, light exponential smoothing.
- All hot-path buffers are preallocated; grids are cached to offscreen
  canvases and only redrawn on resize/setting change; canvases are
  `devicePixelRatio`-aware.
- All waveform drawing funnels through one `drawTrace(ctx, samples, …)`
  function so a later WebGL swap stays contained.
