# Round 12 — 2i2 coherence collapse, zero-starts, fs dropdown, TF tray labels

Date: 2026-08-20. Reported from the lab that morning (photos + two
`.dvma` files in `data/not-working-examples/`, all captured with
v2.4.0-era code on the lab PC): on the Scarlett 2i2, TF coherence had
become inconsistent and very poor (worse for longer captures, fine on
NI with identical settings and rig, fine on the 2i2 "before"), every
capture's time data started with a stretch of zeros, the fs dropdown
showed the typed value twice as the only option, and TF-view tray cards
listed two channel rows for what the view draws as one paired line.

Diagnosed and fixed the same day on the office Windows PC with the 2i2
plus a Rigol DG1022Z (driven over USBTMC/pyvisa) as a phase-trackable
signal source: sines on L (1 kHz) and R (1.7 kHz), so any dropped block
of D samples appears as a `-2π·f0·D/fs` step in the detrended
demodulated phase, localised to the sample. That method — now kept as
`dev/soundcard_drop_check.py` — sees drops COMMON to both channels,
which inter-channel coherence cannot; common drops are exactly what
destroys input→output TF coherence on a resonant rig, because the
filter memory spans the excised samples.

## Root causes (five distinct ones)

### 1. O(buffer) work in the audio callback → input overflow → coherence collapse

`streams.Recorder.callback` shifted the WHOLE `stored_time_data` array
left by one chunk on every callback. For a 30 s × 48 kHz × 2 ch capture
that is a ~23 MB memmove (measured 3.4 ms on this PC) against a
`chunk_size/fs` budget of 2.08 ms at the default `chunk_size=100` —
the callback can NEVER keep up, and PortAudio answers by dropping
input. Every drop time-warps the capture; `|H|` (a ratio of averages)
survives, coherence does not. Evidence chain:

- Lab data: per-2 s-block mean coherence in the 30 s capture alternates
  0.955 (clean — better than NI's 0.94) and ~0.83 (corrupted blocks at
  12/14/18/24 s). The 2 s captures are clean → "30 s worse than 2 s".
- Bench: raw `sd.rec` 30 s control = 0 phase-step events, resid 0.002
  rad. `pydvma` same capture = 5–11 events, resid ~1700 rad, steps
  simultaneous on both channels (interleave intact — whole frames
  dropped). At fs=3000 (capture 48 k, chunk scaled ×16 → 33 ms budget)
  standalone was clean — but the LAB ran it under the v2.4 serve stack
  (journal spills, autosave frames, websocket monitor — all new GIL
  load since v2.3), which is what turned the marginal budget into the
  intermittent corrupted blocks. That is the "broke since v2.3" delta;
  fs=48000 (2 ms budget) was almost certainly broken for long captures
  in v2.3 too, just untried.

**Fix** (`streams.py`): both capture buffers are now circular rings —
the callback does two O(chunk) ring writes and nothing else.
`osc_time_data` / `stored_time_data` became read-only properties that
unroll the ring into time order (writes to them would be silent no-ops,
so the zeroing in `log_data` goes through the new `zero_stored()`,
which NI/mock recorders also grew). Streams also open with
`latency='high'` instead of `'low'` — deep host buffering absorbs GIL
stalls from the serve process the way DAQmx's C-side buffering always
did for NI; a logger has no use for low latency, and the cost is
~0.1–0.4 s of scope/trigger-status lag.

### 2. Silent drops — PortAudio's overflow flag was ignored

Even fixed, a pathological machine can still drop; before this round it
did so SILENTLY. The callback now counts `status.input_overflow`
(`Recorder.input_overflows`, carried across the armed path's buffer
re-`__init__`), `log_data` warns loudly and parks the per-capture count
in `acquisition.LAST_CAPTURE_OVERFLOWS`, and serve forwards a non-zero
count as an `error` frame — which pins open as a toast in the webui —
just before the `log_result` it annotates. Gap-riddled data that LOOKS
fine is exactly what the operator must not miss.

### 3. Per-log stream rebuild + wall-clock dwell + host priming → leading zeros

Three stacked causes, all fixed:

- `start_stream`'s soundcard branch ALWAYS tore down and reopened the
  stream (the NI branch has had a reuse path since the IEPE work). Now
  it reuses a live stream whose signature matches
  (`_sc_settings_signature`: device/fs/channels/chunk/num_chunks/
  stored_time/VmaxSC + the duplex determinants), so back-to-back logs
  inherit a ring full of real history. The signature is FROZEN at open
  time (`_open_signature`) because the serve bridge mutates one
  settings object in place between logs — after a reuse pass that can
  be the very object the recorder holds, and a live compare would be
  object-vs-itself, always matching, with buffers sized for the old
  duration. (NB the NI reuse path has this same latent aliasing —
  benign today only because the webui reconfigures on any duration
  change; noted in TODO.md.)
- `log_data`'s free-run dwell was wall-clock from `start_stream`, but a
  fresh stream delivers nothing during its startup latency (~0.1 s
  measured), so the snapshot's front was the ring's initial zeros. The
  dwell is now topped up until the recorder has really appended
  `stored_time*fs` samples (`_wait_for_buffer_fill`, bounded by
  `BUFFER_FILL_GRACE`, cancel-aware).
- WDM-KS additionally delivers a BURST of exact-zero priming chunks at
  stream start — real callbacks carrying digital zeros, which no sample
  count can see through. The callback now skips leading all-zero chunks
  until the first nonzero sample, bounded to ~1 s so a genuinely silent
  digital input still proceeds (analogue inputs are never exactly zero —
  noise floor ~2e-6 FS on the 2i2). The oscilloscope ring is NOT
  filtered — the scope shows what the host delivers.

The lab numbers fell out exactly: at fs=3000 every capture had exactly
172 leading zeros (the 2-chunk settle shortfall = 3200 samples at 48 k,
÷16 decimation, minus the anti-alias FIR half-width — deterministic
because the ×16-scaled chunks quantise the latency), and the FIR's
symmetric pre-ringing is the "bit of non-zero just before it kicks in";
at fs=48000 the un-quantised latency gave the variable 100–110 ms
starts. Reproduced to the sample on the office PC before fixing.

### 4. WDM-KS refuses a sub-native rate with -9994, not -9997

`serve._is_unsupported_rate_error` only recognised `Invalid sample
rate`/-9997, but WDM-KS answers an off-ladder RATE with `Sample format
not supported`/-9994 (measured: 2i2 asked for 3 kHz), so `configure`
died instead of stepping the monitor up to a runnable rate. Now
treated as a rate refusal — safely, because the remedy is "retry at a
rate the device does run", where a genuine format problem still fails
and propagates.

### 5. The fs "dropdown" was a Chromium-filtered datalist

Round 11's typed fs combo used a `<datalist>` — and Chromium
PREFIX-FILTERS datalist suggestions by the current text, so with
"44100" in the field the whole ladder collapsed to one entry, shown
twice (value bold + "44100 Hz" label). Replaced by the typed input
plus an arrow-only `<select>` (`setup-fs-pick`) that always lists the
full ladder unfiltered; picking commits the rate, the input stays the
display and accepts anything.

### 6. TF-view tray rows implied two lines where the view draws one

The tray always listed raw per-channel rows. In the TF view the two
source channels pair into ONE line (the legend has said `ch_1/ch_0`
since Task R4), so the cards now do the same: App threads the per-set
`tf.chIn` (`tfChInFor` — the same accessor the legend transform uses)
through `Tray` to `TrayCard`, which labels output rows with
`tfLineLabel` (one source of truth with the legend) and marks the
input row `ch_0 (ref)`, muted italic. Display only — tri-states,
sparklines (source time channels) and double-click rename are
untouched. Active only in the TF view.

## Verification

Live on the 2i2 (WDM-KS over RDP, Rigol tones on):

| case | leading zeros | phase-step events | resid p2p |
|---|---|---|---|
| BEFORE, 48 k 30 s | 4800–5300 (variable) | 5–11 | ~1700 rad |
| BEFORE, 3 k 30 s (standalone) | 172 (always) | 0 | 0.002 rad |
| AFTER, 48 k 30 s fresh stream | **0** | **0** | 0.0011 rad |
| AFTER, 48 k 30 s reused stream | **0** | **0** | 0.0008 rad |
| AFTER, 3 k 30 s | **0** | **0** | 0.0009 rad |
| raw `sd.rec` control 30 s | – | 0 | 0.002 rad |

End-to-end through a real spawned `pydvma-serve --driver soundcard`
with the websocket monitor streaming throughout the 30 s log (the lab
configuration): configure at 3 kHz → monitor stepped up to 48 kHz with
the explanatory deviceNote (the -9994 fix) → capture delivered with
0 leading zeros, 0 step events, overflows=0.

Suites at close: see the session-close CLAUDE.md block. New regression
file `tests/test_streams_ring.py` (rings, wrap, freeze, priming filter
+ its bound, overflow counting incl. through `log_data`, fill-wait,
reuse incl. the frozen-signature aliasing case, latency='high');
`test_serve_protocol.py` gained the -9994 parametrisation and the
overflow→error-frame test.

## Notes / deferred

- The device enumeration REORDERED twice during the bench (RDP audio
  endpoints appearing/vanishing) — the existing name-based
  re-resolution covers the app; bare-index scripts must resolve by
  name (`dev/soundcard_drop_check.py --device` does).
- NI recorder still shifts its buffers O(buffer) per callback and has
  the reuse-aliasing latency described above — both benign in current
  usage (DAQmx buffers deeply; the webui reconfigures on duration
  change) and NOT touched this round: the NI path is hardware-verified
  sample-exact and changes there deserve their own NI-live session.
  In TODO.md.
- The 2i2's "quiet start ~0.6 s" estimate from the lab photos was the
  57 ms zero run plus plot rendering; the measured zero runs are the
  table above.
