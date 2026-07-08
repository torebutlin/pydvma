# 2026-07-08 — Windows PC NI recheck (post-Qt-teardown handoff)

The handoff item from the Mac session: re-verify the web-logger stack
against the real NI devices, close the standing multi-channel gap
(everything since round 5 was single-ch on Mac + mock/protocol only),
and eyeball the two round-D notes on real hardware. All done; one new
finding (flagged, not fixed).

Hardware present: cDAQ-9174 (cDAQ1Mod1 = NI 9234, cDAQ1Mod2 = NI 9260
BNC), USB-6212 (Dev2), USB-6003 (Dev3); ao0→ai0 loopback live on **all
three** devices (no loopback-preflight skips — the Dev3 wiring caveat
did not bite).

## 1. Full pytest with hardware live — GREEN

`352 passed, 15 skipped` (2m17s). All 15 skips are legitimate
capability gates: needs-2-AI-module-chassis (6), multiplexed-ghosting
isolation (2), no-IEPE-on-USB-devices (4), IEPE-unsupported-covering
test skipped on cDAQ (1), DSA-only rate-ladder tests on non-DSA (2).
Stimulus-driven pretrigger tests ran on every device.

## 2. Bridge-level recheck — 38/38 (new harness: `dev/bridge_hw_check.py`)

Headless WebSocket client against a real `pydvma-serve --driver nidaq`:

- **Capabilities**: 3 NI devices; chassis caps correctly merged from
  modules (`entry_capabilities`): 9260 `ao_vmax = 4.24264068712`,
  9234 `ai_vmax = 5.0`, IEPE `[0.002]`, simultaneous, PseudoDiff,
  max_channels 4-in/2-out.
- **DSA coerced-fs**: configure at 8000 Hz → `configured` reports
  8533.333 Hz on the real 9234.
- **Multi-channel (the standing gap)**: 4-channel log through the
  bridge with a 1 V sweep on the 9260 → container `(17066, 4)` at
  8533.3 Hz; loopback ch0 rms 0.567 / peak 1.00 V, open channels
  rms ~0.0002. Multi-channel is real, ordered, and scaled.
- **Pretrigger + output sweep on every device** (cDAQ, 6212, 6003):
  armed → triggered → log_result, 2-ch, ~2 s of samples, signal onset
  lands at the pretrigger point (1024 samples) within ~140 samples
  (trigger-threshold crossing offset, as expected).

## 3. Round-D notes eyeballed in the real UI (built webui, real bridge)

Drove a real browser at the served UI (`npm run build`, then
`pydvma-serve --driver nidaq` serving `webui/dist`):

- Setup-full NI group with the cDAQ selected shows
  **"rail in ±5 out ±4.24 V"** and **"output clamped to device rail
  ±4.24 V (default 5 V would saturate)"**; the output-vmax field is
  pre-clamped to 4.24264068712. IEPE options "off / 2 mA" come from
  the live 9234.
- Requesting 8 kHz and starting the monitor produces the
  `setup-coerced-fs` note: **"device runs at 8533.3 Hz (requested
  8000)"** — exactly the round-D wording.
- Bonus UI-path checks: the live scope streamed **4 real channels**
  (ch_0..ch_3) from the 9234, and a Log press captured a real
  4-channel set that landed in the tray and plotted in Time.
- The NI device select re-bounds the fs ladder when a device is
  picked (8k–48k for the 9234, capped below its 51.2k max).

## 4. New finding (flagged as a follow-up task, not fixed)

**webui never sets `output_fs`**, and `MySettings` defaults it to
`fs`. On the USB-6003 (AO max 5000 S/s), any input fs > 5000 with a
stimulus enabled fails at log time with a loud, actionable bridge
error ("output_fs = 8000 Hz exceeds the maximum AO sample rate of
Dev3 (5000 Hz)"). The UI already has `ao_max_rate` in `device_caps`,
so it could clamp `output_fs` and show a note — same pattern as the
existing voltage-rail clamp. Flagged as background task
(task_01e8edaf); until then the error message tells the user what to
do.

## What's left (unchanged from the handoff, minus what closed today)

- Tore's solo hands-on over days/weeks — feedback-driven sessions.
  Round-7 surface: shared-pole fitting, Best match / x(iω) scaling,
  /config prefill, sono single-targeting, brush v2, dark mode;
  analysis-side checks with `data/examples/`.
- Pre-existing flagged follow-ups: CSD phase (complex Pxy), browser
  (Web-Audio-path) pretrig threshold control, log-y CWT heat
  rendering, CSD pair auto-enable on hidden channel, orphan-fit
  browser e2e (task_c158292c), PWA manifest.
- New: webui output_fs clamp (task_01e8edaf, above).
- IEPE with a real accelerometer (loopback can't exercise a live IEPE
  sensor chain; pytest covers task-level IEPE config on the 9234).
