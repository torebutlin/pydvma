# Wave B design brief — `pydvma serve` local bridge

Scout output (read-only Opus agent, 2026-07-07) for Wave B of
`dev/plans/2026-07-07-full-gui-replacement-plan.md`. Orchestrator
decisions locked at the end. Spot-check line refs before relying.

## A. Python acquisition surface to wrap

- `streams.py:158 start_stream(settings)` dispatches on
  `settings.device_driver` in {'mock','soundcard','nidaq'} and sets
  module globals REC/REC_SC/REC_NI/REC_MOCK (`streams.py:31-34`).
  Serve calls `start_stream` UNCHANGED and reads `streams.REC`.
- Recorders share one attribute surface (`Recorder` :336,
  `Recorder_NI_nidaqmx` :555/903, `MockRecorder` :1141):
  `osc_time_data (num_chunks*chunk_size, ch)`, `stored_time_data
  (stored_num_chunks*chunk_size, ch)`, `osc_time_axis`,
  `init_stream/end_stream`. Chunks shift-left + append
  (`osc_data_chunk (chunk_size, ch)`). Trigger state machine
  (docstring :352-397) checks the second-oldest chunk against
  `pretrig_threshold`; `pretrig_samples` capped at chunk_size.
- Capture: `acquisition.log_data(settings, test_name, rec, output)`
  (`acquisition.py:20`) rebuilds via start_stream, waits, wraps the
  buffer tail into DataSet/TimeData IN VOLTS with
  `channel_cal_factors = 1/channel_sensitivities`. Also
  `output_signal` (:279), `signal_generator` (:313, sweep/gaussian/
  uniform), `stream_snapshot(rec)` (:392) = non-blocking osc grab —
  ideal for the monitor feed.
- Enumeration: `get_devices_soundcard()` (`streams.py:305`);
  `_ni_backend.enumerate_devices()` (`_ni_backend.py:112`) →
  `{name, product_type, is_chassis, ai/ao counts, module_*}`;
  channel strings :203/225; `supports_hw_ao_sync` :288;
  `resolve_terminal_config` :44. All Mac-testable with mocked
  `nidaqmx.system` (see tests/test_ni_backend.py).
- MockRecorder synthesises `0.1*sin(2π·100·(k+1)·t)` per channel k
  into both buffers at construction; `trigger_detected` stays False.
  Doubles as protocol test double + demo source.
- MySettings kwargs the bridge `configure` accepts
  (`options.py:211-241`): channels, fs, chunk_size, num_chunks,
  viewed_time, stored_time, pretrig_*, device_driver, device_index,
  input_channels_spec, VmaxNI, VmaxSC, iepe_excit_current_A,
  channel_sensitivities, NI_mode, output_*.
- Packaging: extras at `pyproject.toml:23-29`; python floor 3.11;
  package-data currently `pydvma = ["*.png"]` only — shipping
  webui/dist needs real packaging work (see decisions).

## B. Protocol (v1)

One WebSocket, same-origin (`ws://host:port/ws`). JSON text frames =
control; binary frames = sample chunks. Modeled on the worker RPC
(`webui/src/lib/worker/client.ts` — injectable transport testing).

Client→server: `hello` → `capabilities`; `configure {settings}`
(→ MySettings → start_stream); `start_monitor` / `stop_monitor`;
`log {duration, pretrigger|null}`; `cancel`.

Server→client: `capabilities {v, backends, devices{soundcard, nidaq},
fs_ladders, max_channels, pretrigger, ao}`; `log_result` (metadata +
a `.dvma` container as a following binary frame — the UI already
parses .dvma natively, so bridged sets flow through the existing
`actions.addRecordedSet` path); `status`; `error`.

Binary sample-chunk header (LE, 20 bytes):
`u8 magic 0xDV | u8 ver=1 | u8 msgType(1=chunk) | u8 dtype(0=f32) |
u16 streamId | u16 nChannels | u32 seq | u32 nSamples | f32 fs`,
payload = interleaved row-major (nSamples × nChannels) — matches the
Web-Audio MonitorChunk so BridgeSource hands the store a
byte-identical chunk.

## C. Webui side

- Fork risk: `acquire.ts:13` and `monitor.ts:26` import source.ts
  functions DIRECTLY. New seam: `SourceProvider` interface
  (`webui/src/lib/audio/provider.ts`) with kind, capabilities(),
  enumerateInputDevices(), startRecording(), startMonitor().
  WebAudioProvider wraps source.ts verbatim; BridgeProvider
  (`webui/src/lib/audio/bridge.ts`) implements the SAME
  MonitorHandle/RecordConfig/Recording/RecordingHandle interfaces
  (`source.ts:37-143` — frozen). Stores take the provider (small
  acquire.ts/monitor.ts edits); tests inject a fake provider.
- Mode detection (App.svelte near :159): BridgeProvider when served
  by pydvma serve (`/config` fetch or `window.__pydvma_bridge`), or
  `?bridge=ws://…` param, else Web Audio. Bridge presence also flips
  `liveSource`.
- SetupCard already has the marked nidaq slot (`SetupCard.svelte:251`)
  and a device dropdown (:128) to merge bridge devices into; the NI
  group (IEPE, terminal config, pretrigger) renders when
  capabilities.backends includes 'nidaq'.
- Launch-config: `/config` endpoint the UI fetches on boot (preferred
  over URL params) — `pydvma serve --settings` / notebook helper.

## D. Testing

- pytest `tests/test_serve_protocol.py`: drive the handler against
  `device_driver='mock'` — hello/capabilities, configure→MySettings,
  monitor frames (header + deterministic Mock sine), log→valid .dvma,
  cancel/error. `_clean_streams_state` fixture pattern
  (tests/test_acquisition_mock.py:30). NI enumeration via mocked
  nidaqmx.system. In-process handler or 127.0.0.1 loopback.
- vitest `webui/tests/audio/bridge.test.ts`: BridgeProvider against a
  fake ws transport; frame parse → MonitorChunk; stop sends
  stop_monitor; recording resolves; error/reconnect.
- e2e idea: Playwright project spawning `pydvma serve --mock` as
  webServer, app at `?bridge=`; Log Data round-trips a set into the
  tray. CI-safe (no hardware).

## Orchestrator decisions (locked 2026-07-07)

1. **Dep = `websockets`** (pure-Python, zero transitive deps); static
   file serving of webui/dist on the same port via process_request.
   Fallback if fiddly: aiohttp (flag before switching).
2. **Port 8760** default, `--port` flag; bind **127.0.0.1 only**, no
   auth (lab-local stance; token-in-/config is the cheap upgrade).
3. **Backpressure: lossy latest-state** — send `stream_snapshot`-style
   newest osc state at a fixed cadence (~30 Hz), drop-oldest
   semantics matching the ring buffer. Never queue unboundedly.
4. **.dvma save: bridge returns bytes → browser saves** through the
   existing workdir path (ONE save story). Optional server-side write
   later.
5. **Wheel ships built UI**: package-data glob + a build step staging
   webui/dist into the package. If it turns into a yak-shave, ship
   `--ui-dir` (serve from a path, default = repo webui/dist) and
   leave wheel-embedding as a follow-up task — do not block the
   bridge on packaging.
6. **streams.py/acquisition.py verbatim** — serve.py is purely
   additive (compat contract #1).

## Task split

- **Agent B-python**: pydvma/serve.py (new), pyproject.toml ([serve]
  extra + packaging), tests/test_serve_protocol.py (new), optional
  __init__ lazy entry. Fully disjoint — dispatched first.
- **Agent B-webui**: provider.ts + bridge.ts (new), acquire.ts /
  monitor.ts provider injection, SetupCard nidaq group, App.svelte
  mode selection, tests. HELD until Wave-A1 releases App.svelte.
