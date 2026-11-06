# iD44 support and basic acoustics: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pydvma drive an Audient iD44 with measurement mics properly: per-channel gain/pad, calibration to pascals (spec sheet, calibrator, opt-in carry-forward), dB SPL with A/C-weighting and octave bands, and long (1–5 min) recordings that survive the whole served-app path.

**Architecture:**
- **Device facts** live in the `_soundcard_specs` profile.
- **Per-channel full scale** extends `MySettings` so stored data stay volts per channel; a scalar still means "all channels".
- **Acoustics maths** is a new `pydvma/acoustics.py` with a TS twin pinned by shared known-answer vectors.
- **Display transforms** (weighting, dB SPL, bands) live in the web app's plot model and never touch stored data.
- **Calibration provenance** is a new optional `TimeData` meta field.
- **Carry-forward** is web-app state applied when a recording lands.
- **Long recordings** are measured with a headless harness, then each limit hit is fixed.

**Tech stack:**
- Python 3 (numpy, scipy, sounddevice, websockets).
- Svelte 5 + TypeScript (vite, vitest, Playwright).

**Spec:** `dev/plans/2026-11-06-id44-acoustics-design.md` (approved). Read it first.

## Global constraints

**Repo**
- Work on `master` in `/Users/tore/Documents/GitHub/pydvma`. Commit each task. Never push.
- Stage with explicit paths only. Never `git add -A`, `git add .`, `git stash`, `git reset` or `git checkout`: other agents share this tree.

**Commands**
- Python is `/opt/anaconda3/bin/python` (editable install).
  - Tests: `python -m pytest tests/<file> -q` from the repo root.
- Web app commands run **from `webui/`**:
  - `npm run check` must stay 0 errors / 0 warnings.
  - Unit tests: `npx vitest run <paths>`.
  - Playwright only from `webui/`.
- After any `pydvma/*.py` change that the browser engine or the `@engine` specs need, run `(cd webui && npm run vendor:wheels)`.

**Docs and docstrings**
- Every new public Python function, method or class gets a docstring.
- Docstrings are griffe-strict: one parameter per `Args:` line, returns described in prose. `python -m mkdocs build --strict` must pass.
- CHANGELOG entries go under `## Unreleased`. No version bump.

**Hardware and the engine**
- **Implementers never open the iD44** or any audio device: the coordinator does all hardware runs.
  - The iD44 stays at 48 kHz.
  - No stimulus louder than −40 dBFS on its outputs; speakers are connected and Tore is away.
- Bulk numbers never cross into pyodide one by one: always go through `engine.enqueue` and the packed payload path.

**Back-compatibility (anti-goal)**
- Behaviour, settings and file reading must not change for the 2i2, U24 XL, NI or old files.
- A scalar `VmaxSC`, `input_gain_db` or `input_mode` keeps its exact current meaning.

## Review focus

1. **Old files and scalar settings.**
   - A `.dvma` saved before this work restores scalar `VmaxSC` without `__init__` (`container._settings_from_dict`) and must analyse, save and capture-replay unchanged.
   - Owned by Task 2: `test_old_settings_restore_scalar_paths`.
2. **Channel count changes after per-channel values are set.**
   - E.g. 4 gains set, then channels reduced to 2, or the soundcard clamp trims channels.
   - Arrays are truncated or padded, never crash or misalign.
   - Owned by Task 2: `test_per_channel_arrays_follow_channel_count`.
3. **Mixed units.**
   - If any visible line is not in Pa, no "dB re 20 µPa" label appears and no 20 µPa offset is applied; FS-unit mic data must never read as dB SPL.
   - Owned by Task 7: `mixed units keep plain dB`.
4. **Weighting at 0 Hz.**
   - The DC bin gives −inf dB. It must use the existing floor handling: no NaN in autofit, no crash in band sums.
   - Owned by Tasks 6 and 7: `test_weighting_at_zero_hz`, `weighting does not break autofit`.
5. **A reference tone that is clipped, off-frequency or buried in noise.**
   - It returns warnings with the numbers, never a silent factor.
   - Owned by Task 6: `test_reference_tone_warnings`.

---

## Task order and parallelism

| Wave | Tasks | Model |
|---|---|---|
| 1 | T1 (device profile) ∥ T6 (acoustics maths) | sonnet ∥ sonnet |
| 2 | T2 (per-channel MySettings) ∥ T7 (frequency view) | opus ∥ sonnet |
| 3 | T3 (serve caps, scale fields, input health) | sonnet |
| 4 | T4 (web app per-channel plumbing) | opus |
| 5 | T5 (Setup per-channel UI) ∥ T8 (provenance field) | sonnet ∥ sonnet |
| 6 | T9 (calibrator step) | sonnet |
| 7 | T10 (carry-forward) | opus |
| 8 | T11 (long recordings) | opus |
| 9 | T12 (hardware, docs, suites) | coordinator |

Each implementer's report must list the changed files and the test commands it ran.

---

### Task 1: iD44 device profile and the generalised gain model

**Files:**
- Modify: `pydvma/_soundcard_specs.py` (PROFILES 34–88, `full_scale_volts` 216–251, the module docstring)
- Modify: `pydvma/devices.py`
  - `format_inventory` ~840: role text must distinguish 'loopback' from 'optical'.
  - `calibration_status` 187–251: a `per_channel_gain` device with no stated gain is `'needs_gain'`.
- Test: `tests/test_soundcard_specs.py` (new class `TestID44Profile`), `tests/test_devices.py`

**Interfaces (produces):**
- `PROFILES['audient_id44']` with keys:
  - `match=('audient id44',)`, `vendor_match=('audient',)`, `label='Audient iD44'`
  - `channel_roles = ('analogue',)*4 + ('optical',)*16 + ('loopback',)*2`
  - `max_input_dbu={'mic': 18.0, 'line': 28.0, 'inst': 10.0}` (maximum input at the mode's MINIMUM gain)
  - `gain_range_db={'mic': (0.0, 60.0), 'line': (-10.0, 50.0), 'inst': (0.0, 60.0)}`
  - `pad_db=10.0`, `mode_channels={'inst': (0, 1)}`, `per_channel_gain=True`
  - `preferred_fs=48000`, `ein_dbu=-126.0`, `adc_floor_dbfs=-117.0`
  - `max_output_dbu=18.0`, `headphone_output_dbu=14.0`
  - Cite the manual pages (V4: p16, p18, p19, p55) and the 2026-11-06 bench in comments.
  - Mark pad on line/inst as "assumed 10 dB, verified on mic only per manual" in the docstring.
- Existing profiles keep a float `gain_range_db` value meaning `(0.0, value)`.
- `gain_range(name, input_mode, neighbours=None) -> tuple[float, float] | None`
- `full_scale_volts(name, gain_db, input_mode='line', neighbours=None, pad=False) -> float | None`:
  - `V = sqrt(2) * 0.7746 * 10**((L - (G - Gmin) + (pad_db if pad else 0)) / 20)`
  - ValueError when the gain is outside `[Gmin, Gmax]`, or `pad=True` on a profile without `pad_db`.
- `per_channel_gain(name, neighbours=None) -> bool`
- `channel_input_modes(name, channel, neighbours=None) -> list[str] | None`
  - Zero-based channel. `'inst'` only for channels in `mode_channels['inst']`; analogue channels only; `[]` for optical/loopback.
- `optical_channels(name, channels, neighbours=None) -> list[int]`
- `preferred_fs(name, neighbours=None) -> int | None`
- `analogue_floor_dbfs(name, gain_db, input_mode='mic', neighbours=None, pad=False) -> float | None`
  - `10*log10(10**((ein_dbu - FS_dbu_input)/10) + 10**(adc_floor_dbfs/10))`, where `FS_dbu_input = L - (G - Gmin) + pad`.
  - None if the profile lacks `ein_dbu`.

- [ ] **Step 1: Write the failing tests** in `TestID44Profile`:
  - `device_profile('Audient iD44')['label'] == 'Audient iD44'`
  - `channel_roles('Audient iD44', 22)` has 4 analogue, 16 optical, 2 loopback; `loopback_channels(...) == [20, 21]`; `optical_channels('Audient iD44', 22) == list(range(4, 20))`
  - `full_scale_volts('Audient iD44', 0.0, 'mic') == pytest.approx(sqrt(2)*0.7746*10**(18/20))`
  - `full_scale_volts('Audient iD44', 60.0, 'mic') == pytest.approx(sqrt(2)*0.7746*10**(-42/20))`
  - `full_scale_volts('Audient iD44', 60.0, 'mic', pad=True) == pytest.approx(sqrt(2)*0.7746*10**(-32/20))`
  - `full_scale_volts('Audient iD44', -10.0, 'line') == pytest.approx(sqrt(2)*0.7746*10**(28/20))`
  - `full_scale_volts('Audient iD44', 50.0, 'line') == pytest.approx(sqrt(2)*0.7746*10**(-32/20))`
  - `pytest.raises(ValueError)` for gain 61 mic, gain −11 line, and `pad=True` on `'Scarlett 2i2 4th Gen'`
  - `channel_input_modes('Audient iD44', 0) == ['inst','line','mic']`, `channel_input_modes('Audient iD44', 2) == ['line','mic']`, `channel_input_modes('Audient iD44', 5) == []`
  - `per_channel_gain('Audient iD44') is True`, `per_channel_gain('Scarlett 2i2 4th Gen') is False`
  - `preferred_fs('Audient iD44') == 48000`
  - `analogue_floor_dbfs('Audient iD44', 60.0, 'mic') == pytest.approx(-84.0, abs=0.2)`, `analogue_floor_dbfs('Audient iD44', 0.0, 'mic') == pytest.approx(-117.0, abs=0.1)`
  - Regression: every existing 2i2/U24 XL `full_scale_volts` assertion in the file still passes unchanged.
- [ ] **Step 2: Run** `python -m pytest tests/test_soundcard_specs.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the profile and functions above. Update `devices.calibration_status` and `format_inventory`. Add a `tests/test_devices.py` case: an inventory line for a device with optical roles says "optical", not "loopback".
- [ ] **Step 4: Run** `python -m pytest tests/test_soundcard_specs.py tests/test_devices.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(soundcard): Audient iD44 profile; gain ranges with a minimum, pad, optical role`

### Task 2: per-channel full scale in `MySettings` and the capture path

**Files:**
- Modify: `pydvma/options.py`:
  - `_derive_full_scale_volts` 38–72
  - `pretrig_level` 81–115
  - `MySettings.__init__` 412–691
  - `_broadcast_per_channel` 791
  - `input_vmax` 820
- Modify: `pydvma/streams.py`:
  - `_sc_settings_signature` 104–138
  - `_clamp_soundcard_input_channels` 141–181
  - `Recorder.callback` scaling at ~1488
- Modify: `pydvma/acquisition.py`:
  - `exact_zero_dropouts` call 779
  - clip check 865–867 (per channel, input columns only, before the `use_output_as_ch0` prepend)
- Modify: `pydvma/session.py` `_settings_summary` 287–332
- Test: `tests/test_per_channel_scale.py` (new); extend `tests/test_acquisition_guards.py`, `tests/test_streams_trigger.py`, `tests/test_streams_ring.py`, `tests/test_session_launch.py`

**Interfaces:**
- Consumes: Task 1's `full_scale_volts(..., pad=)`, `gain_range`.
- Produces:
  - `MySettings(..., VmaxSC=1.0, input_gain_db=None, input_mode='line', input_pad=False, ...)`:
    - each of these four accepts a scalar or a per-channel sequence;
    - `input_gain_db` entries may be None (channel not stated).
  - After `__init__`:
    - `self.VmaxSC` is a float when every channel's value is equal, else a float `np.ndarray` of shape `(channels,)`.
    - `self.input_gain_db`, `self.input_mode` and `self.input_pad` stay scalar when given scalar, else lists of length `channels`.
  - `MySettings.input_vmax_channels() -> np.ndarray` (shape `(channels,)`; `VmaxNI` repeated on nidaq).
  - `MySettings.input_vmax(channel=None) -> float`: that channel's rail, or the max over channels when None.
  - `MySettings.channels_in_volts() -> np.ndarray[bool]`: True where the rail is a real voltage, i.e. any of:
    - nidaq;
    - a stated gain on a characterised device;
    - a fixed-gain device;
    - an explicit VmaxSC ≠ 1.0 for that channel.
  - `options.pretrig_level(settings)` uses the `pretrig_channel`'s rail.

- [ ] **Step 1: Write the failing tests** in `tests/test_per_channel_scale.py`. Fake device names are set via `monkeypatch` on `streams.soundcard_device_name`, as the existing `TestSettingsIntegration` does.
  - `test_scalar_settings_unchanged`: `MySettings(VmaxSC=2.5).VmaxSC == 2.5` and `input_vmax() == 2.5`; `MySettings(device_driver='nidaq', VmaxNI=5).input_vmax_channels()` equals `[5, 5]` for 2 channels.
  - `test_per_channel_gain_derives_per_channel_vmax`: with an iD44 name, `channels=4, input_gain_db=[60, 60, None, 0], input_mode='mic'`:
    - `VmaxSC` is an array;
    - `[0] == approx(full_scale_volts('Audient iD44', 60, 'mic'))`;
    - `[2] == 1.0`;
    - `channels_in_volts()` equals `[True, True, False, True]`.
  - `test_per_channel_pad`: `input_pad=[False, True, False, False]` raises channel 1's rail by exactly 10 dB.
  - `test_per_channel_arrays_follow_channel_count`: per-channel values for 4 channels, then `channels=2`, give arrays of length 2. Also exercise `streams._clamp_soundcard_input_channels` with arrays.
  - `test_old_settings_restore_scalar_paths`: build a settings object through `container._settings_from_dict` from a dict with scalar `VmaxSC` and no `input_pad`. Then:
    - `input_vmax_channels()`, `pretrig_level`, `streams._sc_settings_signature` and `session._settings_summary` all work;
    - the recorder's scaling of a (chunk, ch) array matches today's.
  - `test_clip_check_per_channel`: drive `acquisition`'s clip decision with a mock capture where channel 1 peaks at 0.97 × its own rail and channel 0 at 0.5 × its rail with rails `[1.0, 0.01]`. Only channel 1 is reported as clipped, and the message names it.
  - `test_use_output_as_ch0_keeps_per_channel_scale`: with `use_output_as_ch0=True`, the per-channel clip check and scaling apply to the input columns, not the prepended output column.
  - `test_pretrig_level_uses_trigger_channel`: rails `[1.0, 0.01]`, `pretrig_channel=1`, `pretrig_threshold=None` gives `pretrig_level == approx(0.05*0.01)`.
- [ ] **Step 2: Run** `python -m pytest tests/test_per_channel_scale.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Broadcasting goes through `_broadcast_per_channel` (precedent `channel_sensitivities`).
  - The recorder multiplies `(frames, channels)` by the per-channel row.
  - `output_VmaxSC` stays scalar and defaults to `max(VmaxSC)` only when VmaxSC was a scalar; otherwise to 1.0 with the existing semantics documented.
  - Update every docstring touched.
- [ ] **Step 4: Run** `python -m pytest tests/test_per_channel_scale.py tests/test_acquisition_guards.py tests/test_streams_trigger.py tests/test_streams_ring.py tests/test_session_launch.py tests/test_session_apply_settings.py tests/test_soundcard_specs.py tests/test_container.py tests/test_dropouts.py -q`, then the full `python -m pytest -q`. Expected: PASS, except the known sounddevice/hardware skips.
- [ ] **Step 5: Commit** `feat(settings): per-channel gain, pad and full scale (VmaxSC) for multi-preamp interfaces`

### Task 3: serve caps, per-channel scale fields, input health

**Files:**
- Modify: `pydvma/serve.py`:
  - `_soundcard_device_caps` 758–865
  - `_input_scale_fields` 868–904
  - a warning frame after capture in `_on_log` ~2390
- Modify: `pydvma/acquisition.py` (new `input_health`, called in `log_data` after the clip check, printing each issue)
- Test: `tests/test_serve_protocol.py` (`TestSoundcardGainModelInCaps`, `TestInputScaleFields`), `tests/test_input_health.py` (new)

**Interfaces:**
- Consumes: Task 1 functions; Task 2 `input_vmax_channels`, `channels_in_volts`.
- Produces:
  - Per-soundcard caps keys, each None/False for uncharacterised devices:
    - `per_channel_gain: bool`
    - `gain_range_db: {mode: [lo, hi]} | None`
    - `pad_db: float | None`
    - `mode_channels: {mode: [int]} | None`
    - `preferred_fs: int | None`
    - `stop_gains_db: {mode: [lo, hi]} | None` (same as `gain_range_db`; named for the UI's stop buttons)
  - `_input_scale_fields(settings)` adds `inputVmaxChannels: list[float]` and `inputVmaxIsVoltsChannels: list[bool]`.
    - It keeps `inputVmax` (= max) and `inputVmaxIsVolts` (= all channels in volts) for old clients.
    - It must never silently return `{}` for a per-channel settings object.
  - `acquisition.input_health(data, settings) -> list[dict]`. Each dict is `{'channel': int (zero-based), 'kind': 'optical_silent'|'no_signal', 'message': str}`:
    - `optical_silent`: an optical-role channel whose samples are all exactly 0.0. Message `"channel {n} is an optical (ADAT) input with nothing connected"`.
    - `no_signal`: an analogue channel with a stated gain whose rms in dBFS is below `analogue_floor_dbfs(...) + 10`. Message `"channel {n} is at the interface's own noise floor: check 48 V phantom, the cable, or the gain"`.
    - Uncharacterised devices and unstated gains produce none.
  - serve sends one `warning` frame per capture listing the issues, through the existing warning sink that the integrity notices use.

- [ ] **Step 1: Write the failing tests.**
  - Caps for a monkeypatched device named `'Audient iD44'` contain `per_channel_gain True`, `pad_db 10.0`, `preferred_fs 48000`, `mode_channels {'inst': [0, 1]}`.
  - A 2i2 has `per_channel_gain False`, `pad_db None`.
  - `_input_scale_fields` for rails `[0.0082, 0.0082, 1.0, 1.0]` gives `inputVmaxChannels` equal to that list, `inputVmaxIsVoltsChannels [True, True, False, False]`, `inputVmax 1.0`, `inputVmaxIsVolts False`.
  - `input_health`: zeros on channel 5 of a 22-ch iD44 capture → one `optical_silent`; a −100 dBFS-rms channel 0 with stated gain 60 mic → `no_signal`; the same with gain unstated → none; a −20 dBFS channel → none.
- [ ] **Step 2: Run** `python -m pytest tests/test_serve_protocol.py tests/test_input_health.py -q -k "Caps or ScaleFields or health"`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python -m pytest tests/test_serve_protocol.py tests/test_input_health.py tests/test_acquisition_mock.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(serve): per-channel gain caps, per-channel input rails, input-health warnings`

### Task 4: web app per-channel plumbing

**Files:**
- Modify: `webui/src/lib/audio/provider.ts`:
  - `DeviceCapsEntry` ~85
  - `ConfiguredInfo` ~337
  - `deviceCapsFor` 378–432
  - `effectiveFullScaleVolts` 604–634
  - `BridgeConfig` 694–754
- Modify: `webui/src/lib/audio/bridge.ts`: `emitConfigured` 378–392, `buildSettings` 649–703, `buildPretrigger` 775–791
- Modify: `webui/src/lib/stores/acquire.ts` (`inputFullScale` 270, `onConfigured` 342–352, `setProvider` 367)
- Modify: `webui/src/lib/stores/monitor.ts` (clip test 263–285)
- Modify: `webui/src/components/LevelBars.svelte` 43–74
- Modify: `webui/src/lib/model/levelCheck.ts` (`reportLevels` 80)
- Modify: `webui/src/lib/model/calibration.ts` (`capturedInVolts` 159)
- Modify: `webui/src/lib/audio/serveConfig.ts` (`mapServeConfig` 146–271)
- Test: `webui/tests/audio/bridge.test.ts`, `webui/tests/stores/acquire.test.ts`, `webui/tests/stores/monitor.test.ts`, `webui/tests/model/levelCheck.test.ts`, `webui/tests/model/calibration.test.ts`, `webui/tests/audio/serveConfig.test.ts`

**Interfaces:**
- Consumes: Task 3 caps keys and `inputVmaxChannels` / `inputVmaxIsVoltsChannels`.
- Produces:
  - `type InputMode = 'line' | 'inst' | 'mic'`
  - `BridgeConfig.inputGainDb?: number | (number | null)[]`, `BridgeConfig.inputMode?: InputMode | InputMode[]`, `BridgeConfig.inputPad?: boolean | boolean[]`
  - `buildSettings` emits `input_gain_db`, `input_mode`, `input_pad` (scalar stays scalar, arrays stay arrays; `null` entries pass through).
  - `DeviceCapsEntry`: `per_channel_gain?: boolean`, `gain_range_db?: Record<string, [number, number]>`, `pad_db?: number | null`, `mode_channels?: Record<string, number[]>`, `preferred_fs?: number | null`
  - `ConfiguredInfo.inputVmaxChannels?: number[]`, `ConfiguredInfo.inputVmaxIsVoltsChannels?: boolean[]`
  - `acquire.inputFullScaleChannels: Readable<number[] | null>`; null until a per-channel reply arrives, reset on provider change.
  - `effectiveFullScaleVolts(caps, deviceId, cfg, channel?: number): number | null`
  - `capturedInVolts(settings, channel?: number): boolean`. Per channel from an array `VmaxSC`; unchanged for scalars.
  - `reportLevels(levels, fullScaleVolts: number | (number | null)[] | null)`
  - `mapServeConfig` maps `VmaxSC`, `input_gain_db`, `input_mode`, `input_pad` (scalar or list) into `BridgeConfig`. Today it maps none of them.
  - monitor clip threshold and `LevelBars` use the channel's own full scale when `inputFullScaleChannels` is set.

- [ ] **Step 1: Write the failing vitest cases.**
  - bridge `buildSettings` with `inputGainDb [60, 60, null, 0]`, `inputMode 'mic'`, `inputPad [false, true, false, false]` → kwargs carry those arrays; scalar config → unchanged kwargs (existing assertions untouched).
  - `emitConfigured` with `inputVmaxChannels` sets `inputFullScaleChannels`.
  - monitor: peaks `[0.9, 0.009]` with full scales `[1, 0.01]` → channel 1 clips, channel 0 does not.
  - `reportLevels` with a per-channel full-scale array converts each channel with its own value.
  - `capturedInVolts({VmaxSC: [0.0082, 1]}, 0) === true` and `(..., 1) === false`.
  - `mapServeConfig({input_gain_db: [60, 60, 60, 60], input_mode: 'mic', input_pad: false})` → `BridgeConfig` with those values.
- [ ] **Step 2: Run** `npx vitest run tests/audio tests/stores/acquire.test.ts tests/stores/monitor.test.ts tests/model/levelCheck.test.ts tests/model/calibration.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command, then `npm run check` and `npx vitest run`. Expected: all PASS, check 0/0.
- [ ] **Step 5: Commit** `feat(webui): per-channel gain/pad and input rails through bridge, meters and level check`

### Task 5: Setup per-channel UI, optical note, preferred rate

**Files:**
- Modify: `webui/src/components/cards/SetupCard.svelte` (gain/mode/VmaxSC block ~1011–1098, notes ~790–834, `loopbackFrom` 229–235)
- Create: `webui/src/lib/model/channelGain.ts` (pure helpers, node-testable)
- Test: `webui/tests/model/channelGain.test.ts`; e2e `webui/e2e/setup-per-channel.spec.ts`
  - Preview server with a stubbed bridge: copy the stub pattern the existing Setup/bridge vitest or e2e fixtures use. If none fits, the e2e is replaced by a coordinator-run live check (Task 12) and this task ships vitest only.

**Interfaces:**
- Consumes: Task 4 types and stores.
- Produces, in `channelGain.ts`:
  - `channelRows(caps: DeviceCapsEntry, channelCount: number, roles: string[]): ChannelGainRow[]`
    - `ChannelGainRow = {ch: number, role: string, modes: InputMode[], gainRange: Record<string, [number, number]>, padAvailable: boolean}`
    - Rows only for analogue channels.
  - `rowFullScaleVolts(caps, row, gainDb: number | null, mode: InputMode, pad: boolean): number | null`. Same arithmetic as Task 1.
  - `opticalRange(roles: string[], channelCount: number): [number, number] | null` (1-based inclusive, for the note)
  - `shouldUsePreferredFs(caps, fs: number, hardwareRates: number[], lpfOn: boolean): boolean`

**UI (test ids fixed):**
- Each analogue channel row has:
  - `setup-ch-gain-{ch}` (number), `setup-ch-gain-top-{ch}` / `setup-ch-gain-bottom-{ch}` (set the mode's range ends);
  - `setup-ch-mode-{ch}` (select);
  - `setup-ch-pad-{ch}` (checkbox), shown only when `pad_db`;
  - `setup-ch-fs-{ch}`, the full-scale preview: "±x.xx V full scale", or "full-scale units (gain not stated)" when blank.
- Rows replace the single gain input only when `per_channel_gain`; every other device keeps today's controls.
- `setup-optical-note`: "channels {a}–{b} are optical (ADAT) inputs: they carry signal only from an external preamp".
- The loopback note must name the loopback channels correctly when optical channels sit between (e.g. "channels 21–22 are the device's digital loopback").
- When the selected device changes and `shouldUsePreferredFs`, set fs to `preferred_fs` and show `setup-preferred-fs-note`: "set to 48 kHz, this interface's native rate".

- [ ] **Step 1: Write the failing tests.**
  - `channelRows` for the iD44 caps with 22 roles and channelCount 22 → 4 rows; rows 0–1 include `'inst'`, rows 2–3 don't.
  - `rowFullScaleVolts(..., 60, 'mic', true)` equals Task 1's value.
  - `opticalRange(roles22, 22)` → `[5, 20]`; with channelCount 4 → `null`.
  - `shouldUsePreferredFs(id44, 10000, [44100, 48000, 88200, 96000], false) === true`; same with fs 48000 → false; with lpfOn → false; a device without `preferred_fs` → false.
- [ ] **Step 2: Run** `npx vitest run tests/model/channelGain.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the helpers and the Setup markup, wired through `acquire.patchBridge`.
- [ ] **Step 4: Run** `npx vitest run tests/model/channelGain.test.ts`, `npm run check`, `npx vitest run`, and the e2e if built. Expected: PASS.
- [ ] **Step 5: Commit** `feat(webui): Setup per-channel gain/pad rows with stop buttons; optical note; preferred rate`

### Task 6: acoustics maths (Python + TS twin) and the reference-tone op

**Files:**
- Create: `pydvma/acoustics.py`
- Modify: `pydvma/verify.py`. `_measure_tone_vrms` moves to `acoustics.tone_rms`; keep `verify._measure_tone_vrms` as a thin alias so nothing breaks.
- Modify: `pydvma/engine.py`: new op `reference_tone_calibration` (template `clean_impulse` 768–779)
- Modify: `pydvma/__init__.py`, exporting the `acoustics` module; `tests/test_packaging.py` `_PUBLIC_SURFACE`
- Create: `webui/src/lib/analysis/acoustics.ts`
- Test: `tests/test_acoustics.py` (new), `webui/tests/analysis/acoustics.test.ts` (new), `tests/test_engine_packed.py` (one case for the op)

**Interfaces (produces, Python):**
- `P_REF = 20e-6`
- `weighting_db(f, curve) -> np.ndarray`
  - `curve` ∈ {'Z', 'A', 'C'}.
  - IEC 61672-1 analytic curves with poles 20.6, 107.7, 737.9, 12194 Hz, normalised to exactly 0 dB at 1 kHz.
  - 'Z' gives zeros; `f <= 0` gives `-inf`.
- `band_table(bands, f_lo, f_hi) -> dict`
  - Keys `centre` (exact base-10 midbands `1000*10**(0.3*x/b)`, b=1 octave or 3 third-octave), `nominal` (IEC nominal labels, e.g. 31.5, 63, 125… / 25, 31.5, 40…), `lower`, `upper` (`centre*10**(∓0.15/b)`).
  - Every band whose `lower >= f_lo` and `upper <= f_hi`.
- `band_levels(f, psd, bands='octave', weighting='Z', min_bins=3) -> dict`
  - `psd` is a DENSITY, shape `(Nf,)` or `(Nc, Nf)`.
  - `power = Σ psd·10**(W/10)·Δf` over bins with `lower <= f < upper`, with Δf from the axis spacing.
  - Bands with fewer than `min_bins` bins are dropped.
  - Returns `band_table` keys plus `power` (shape `(Nb,)` or `(Nc, Nb)`) and `n_bins`.
- `tone_rms(x, fs, freq, bin_neighbours=2) -> float` (moved)
- `reference_tone_calibration(time_data, channel, ref_rms, freq, *, freq_tolerance=0.05) -> dict`
  - Keys: `sensitivity` (stored units per engineering unit = measured/ref), `measured_rms`, `peak_freq`, `tone_to_total_db`, `clipped`, `warnings: list[str]`.
  - Analyse the middle 80 % of the record.
  - Warnings:
    - `peak_freq` more than 5 % from `freq`;
    - broadband rms more than 1 dB above the tone rms (`tone_to_total_db < -1`);
    - peak ≥ 0.95 × the channel's rail (from `time_data.settings.input_vmax(channel)` when settings exist).
  - Each warning includes the numbers.
- `ACOUSTICS_VECTORS`: tuple of `(f, A_db, C_db)` at f = 10, 31.5, 100, 1000, 4000, 16000, frozen from the implementation to 1e-6. The TS test mirrors it verbatim with a `// tests/test_acoustics.py::ACOUSTICS_VECTORS` comment.
- Engine op: `reference_tone_calibration(time_axis, time_data, n_channels, fs, channel, ref_rms, freq, vmax=None)` → the dict above with Python floats/lists.

**Interfaces (produces, TS):**
- `P_REF`, `type Weighting = 'Z'|'A'|'C'`, `type BandKind = 'octave'|'third-octave'`
- `weightingDb(f: number, w: Weighting): number`
- `bandTable(kind, fLo, fHi): BandRow[]` with `BandRow = {centre, nominal, lower, upper}`
- `bandLevels(f: ArrayLike<number>, density: ArrayLike<number>, kind: BandKind, w: Weighting = 'Z', minBins = 3): (BandRow & {power: number, nBins: number})[]`

- [ ] **Step 1: Write the failing Python tests** (`tests/test_acoustics.py`):
  - `test_weighting_iec_table`:
    - A at exact base-10 frequencies for nominals {10: −70.4, 20: −50.5, 31.5: −39.4, 63: −26.2, 100: −19.1, 125: −16.1, 250: −8.6, 500: −3.2, 1000: 0, 2000: 1.2, 4000: 1.0, 8000: −1.1, 10000: −2.5, 16000: −6.6, 20000: −9.3}, within 0.1 dB.
    - C for {10: −14.3, 20: −6.2, 31.5: −3.0, 63: −0.8, 125: −0.2, 250: 0.0, 500: 0.0, 1000: 0, 2000: −0.2, 4000: −0.8, 8000: −3.0, 16000: −8.5, 20000: −11.2}, within 0.1 dB.
    - Exact frequency: `1000*10**(round(10*log10(n/1000))/10)`.
  - `test_weighting_known_answers`: `ACOUSTICS_VECTORS` reproduce to 1e-6. A(1000) == 0 and C(1000) == 0 exactly to 1e-12.
  - `test_weighting_at_zero_hz`: `weighting_db([0.0, 1000.0], 'A')[0] == -inf`; `band_levels` over an axis starting at 0 Hz returns only finite powers.
  - `test_band_table_nominals`: octave between 22 and 22400 → nominal `[31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]`; third-octave between 900 and 1120 → one band, nominal 1000.
  - `test_band_levels_white_noise`: flat density D over 0–24000 at Δf 1 Hz → the 1 kHz octave power ≈ D × (upper − lower) to within one bin.
  - `test_band_levels_tone`: a 1 kHz sine of amplitude 1 at fs 48000, PSD from `scipy.signal.welch(..., scaling='density', window='hann', nperseg=8192)` → 1 kHz octave power ≈ 0.5 to 2 %.
  - `test_band_levels_min_bins`: with Δf 5.86 Hz the 25 Hz third-octave band is dropped.
  - `test_reference_tone_calibration`: synthetic 1 kHz sine of rms 0.0335 V plus noise 60 dB down, ref_rms 1.0 → sensitivity ≈ 0.0335 to 0.1 %, no warnings.
  - `test_reference_tone_warnings`, each warning naming numbers:
    - a 1.3 kHz tone with freq 1000 → frequency warning;
    - noise 3 dB above the tone → noise warning;
    - peak 0.99 of a rail of 1.0 → clipped True and a warning.
  - `test_verify_alias`: `verify._measure_tone_vrms` is `acoustics.tone_rms`, or returns identical values.
- [ ] **Step 2: Write the failing TS tests** (`webui/tests/analysis/acoustics.test.ts`): `ACOUSTICS_VECTORS` mirrored; IEC spot checks; the white-noise and min-bins cases.
- [ ] **Step 3: Run** `python -m pytest tests/test_acoustics.py -q` and `npx vitest run tests/analysis/acoustics.test.ts`. Expected: FAIL.
- [ ] **Step 4: Implement** both sides and the engine op. Add a `tests/test_engine_packed.py` case: the packed call equals the direct call.
- [ ] **Step 5: Run** both suites plus `python -m pytest tests/test_verify.py tests/test_engine_packed.py tests/test_packaging.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(acoustics): A/C weighting, octave bands, reference-tone calibration (Python + TS twin)`

### Task 7: frequency view: dB re 20 µPa, weighting selector, band overlay

**Files:**
- Modify: `webui/src/lib/stores/analysisSettings.ts` (`FreqSettings` 42, default 107)
- Modify: `webui/src/lib/model/dataset.ts` (`DvmaItemUi.analysis.freq` type)
- Modify: `webui/src/lib/plot/model.ts` (`PlotModelArgs` 476–533, frequency branch 726–849)
- Modify: `webui/src/components/cards/FrequencyCard.svelte` (selectors next to `MODES` 101–118, 209–214)
- Modify: `webui/src/App.svelte`:
  - pass `weighting` / `bands` from `settingFor($analysisTarget,'freq')` where `freqMode` is passed (~249);
  - pass `overlays: false` from `navModel` (~1449).
- Test: `webui/tests/plot/model.test.ts` (new describe block `acoustic display`); e2e `webui/e2e/axis-scale.spec.ts` (one new spec)

**Interfaces:**
- Consumes: Task 6 TS `weightingDb`, `bandLevels`, `P_REF`, `Weighting`, `BandKind`.
- Produces:
  - `FreqSettings.weighting: Weighting` (default `'Z'`) and `FreqSettings.bands: 'off' | BandKind` (default `'off'`). Both round-trip through `ui.analysis.freq` automatically; old files get the defaults.
  - `PlotModelArgs.weighting?: Weighting`, `PlotModelArgs.bands?: 'off' | BandKind`, `PlotModelArgs.overlays?: boolean` (default true).
  - Band overlay `PlotLine`s carry `dbY: !linMag`, width 2.5, the parent line's colour, and a new optional `role: 'bands'` field on PlotLine.

**Behaviour (exact copy for labels):**
- **Weighting** multiplies FFT amplitude by `10**(W/20)` and power/density by `10**(W/10)`, in fft, power and density modes only.
- **dB SPL** applies only when `commonUnit` is exactly `'Pa'` and the y scale is dB. Then:
  - FFT y is `20*log10(|X|/P_REF)`;
  - power and density y are `10*log10(P/P_REF**2)`.
- **Label strings** (`{w}` is `(A)` or `(C)` when weighted, empty for Z):

  | Mode | Unit Pa, dB | Other units, dB, weighted | Linear, weighted |
  |---|---|---|---|
  | FFT | `Magnitude (dB{w} re 20 µPa)` | `Magnitude (V, dB, A-weighted)` | `Magnitude (V, A-weighted)` |
  | Power | `Power spectrum (dB{w} re 20 µPa)` | `Power spectrum (V², dB, A-weighted)` | `Power spectrum (V², A-weighted)` |
  | PSD | `PSD (dB{w} re (20 µPa)²/Hz)` | `PSD (V²/Hz, dB, A-weighted)` | `PSD (V²/Hz, A-weighted)` |

  - The other-unit and linear columns show today's label with `, A-weighted` or `, C-weighted` inserted before the closing parenthesis (the V cases are examples).
  - Unweighted non-Pa labels are unchanged.
- **Bands** apply in power and density modes when `bands !== 'off'` and `overlays !== false`. For each visible line:
  - `bandLevels(axis, density, kind, weighting)` with `density = P·cal²/enbw`.
  - In power mode, y = band power; in density mode, y = band power / (upper − lower).
  - Either way it is converted like the parent line (dB SPL when Pa).
  - The line is drawn as a step: x `[lo1, hi1, lo2, hi2, …]`, y `[L1, L1, L2, L2, …]`.
  - Skipped when `enbw` is missing.
- **FrequencyCard selectors:**
  - Weighting: segmented `Z / A / C`, `data-testid="freq-weighting"`, buttons `data-spec` Z/A/C. Shown in fft/power/density modes.
  - Bands: segmented `Off / Oct / ⅓ Oct`, `data-testid="freq-bands"`, buttons `data-spec` off/octave/third-octave. Shown in power/density modes.
  - Both write through `analysisSettings.patch($target, 'freq', …)` and call `actions.notifyUnitsChanged(['frequency'])`.

- [ ] **Step 1: Write the failing vitest cases.** A synthetic set has `psd` with `enbw`, unit Pa through `calFactors`/`units`.
  - Density mode, `'Z'` → y equals `10*log10(D/P_REF²)` and the label is `PSD (dB re (20 µPa)²/Hz)`.
  - `'A'` → y at 100 Hz is lower by 19.145 dB (±0.01) and the label is `PSD (dB(A) re (20 µPa)²/Hz)`.
  - Mixed units: one Pa line and one V line → the label has no `20 µPa` and y has no offset (`mixed units keep plain dB`).
  - `weighting does not break autofit`: an axis starting at 0 Hz with `'A'` → `dataExtent` y range is finite.
  - Bands `'octave'` in power mode → an extra line with `role: 'bands'`, x/y lengths 2·Nb, values equal to Task 6's `bandLevels`.
  - `overlays: false` → no band line.
  - Old `FreqSettings` without the new keys → defaults Z/off.
- [ ] **Step 2: Run** `npx vitest run tests/plot/model.test.ts tests/stores/analysisSettings.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Add one Playwright spec** in `e2e/axis-scale.spec.ts`. Load the demo set, Calc PSD, click `freq-weighting [data-spec=A]`: the y-label contains `A-weighted`. Click `freq-bands [data-spec=octave]`: the plot has one more path than before. Run `npx playwright test e2e/axis-scale.spec.ts`. Expected: PASS.
- [ ] **Step 5: Run** `npm run check` and `npx vitest run`. Expected: PASS, 0/0.
- [ ] **Step 6: Commit** `feat(webui): dB re 20 µPa, A/C weighting and octave-band overlay in the frequency view`

### Task 8: calibration provenance field

**Files:**
- Modify: `pydvma/datastructure.py` (TimeData docstring 1425–1445: document `channel_calibration`)
- Modify: `pydvma/container.py` (`_OPTIONAL_META['TimeData']` 142 gains `'channel_calibration'`)
- Modify: `webui/src/lib/model/calibration.ts` (new type), `webui/src/lib/analysis/actions.ts` (`setCalFactors` 2989–3015 gains a `provenance` option), `webui/src/components/Tray.svelte` (`commitCalibrate` 187–205)
- Modify: `docs/web-logger/dvma-format.md`, `docs/web-logger/calibration.md`
- Test: `tests/test_container.py` (extend `test_v2_optional_analysis_attrs_roundtrip` and `test_v2_optional_attrs_absent_stay_absent`), `webui/tests/analysis/calProvenance.test.ts` (new), `webui/tests/codec/dvma.test.ts`

**Interfaces:**
- Produces:
  - `TimeData.channel_calibration`: optional; when present, a list of length `n_channels`. Each entry is `None` or a dict with keys:
    - `method` (`'sensitivity'` | `'reference_tone'`)
    - `date` (ISO 8601)
    - `sensitivity` (float), `unit` (str)
    - `reference` (None or `{'level': float, 'level_unit': str, 'freq': float}`)
    - `gain_db` (float | None), `input_mode` (str | None), `pad` (bool | None)
    - `device` (str | None), `note` (str), `carried` (bool)
  - TS:
    ```ts
    type ChannelCalibration = {
      method: 'sensitivity' | 'reference_tone'; date: string; sensitivity: number; unit: string;
      reference: { level: number; level_unit: string; freq: number } | null;
      gain_db: number | null; input_mode: string | null; pad: boolean | null;
      device: string | null; note: string; carried: boolean;
    }
    ```
  - `setCalFactors(setId, factors, units?, opts?: {warnFit?: boolean, provenance?: (ChannelCalibration | null)[]})` writes `setItemMeta(ws.time, 'channel_calibration', …)`, keeping existing entries for channels whose provenance is `undefined`.
  - Helper `provenanceFromSet(settings, ch): Pick<ChannelCalibration, 'gain_db' | 'input_mode' | 'pad' | 'device'>` in `calibration.ts`. It reads the set's stored per-channel `input_gain_db` / `input_mode` / `input_pad` (scalar or list) and a device name when stored.
- The dialog Apply writes `method 'sensitivity'` provenance for each channel whose sensitivity or unit changed. It also gains a free-text note field, `cal-note` (one per dialog, copied to each changed channel).

- [ ] **Step 1: Write the failing tests.**
  - Python round trip: a TimeData with `channel_calibration=[{...}, None]` survives `save_bytes` / `load_bytes` equal; absent stays absent (`not hasattr` or None per the existing pattern).
  - vitest: Apply with a changed sensitivity on ch 0 writes `channel_calibration[0].method === 'sensitivity'`, `unit === 'Pa'`, the note, and an ISO date; ch 1 untouched stays null; the `.dvma` write/read keeps it.
- [ ] **Step 2: Run** `python -m pytest tests/test_container.py -q -k optional` and `npx vitest run tests/analysis/calProvenance.test.ts tests/codec/dvma.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same, plus `npx vitest run tests/analysis` and `npm run check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(calibration): per-channel calibration provenance saved with the data`

### Task 9: Calibrate dialog reference-tone step

**Files:**
- Modify: `webui/src/components/CalibrateDialog.svelte` (replace the disabled "known-input calibration…" button 288–292 with a per-row action)
- Modify: `webui/src/components/Tray.svelte` (supply the list of sets and an async `measureReference` callback)
- Modify: `webui/src/lib/analysis/actions.ts` (new `measureReferenceTone`)
- Test: `webui/tests/analysis/referenceTone.test.ts` (new, `fakeEngine` as in `actions.test.ts:102`); `webui/e2e/calibrate.spec.ts` (one `@engine` spec)

**Interfaces:**
- Consumes: Task 6 engine op; Task 8 provenance.
- Produces:
  - `actions.measureReferenceTone(setId: string, ch: number, refRms: number, freq: number): Promise<{sensitivity: number, measuredRms: number, peakFreq: number, warnings: string[], clipped: boolean}>`. It calls `engine.enqueue('reference_tone_calibration', timePayload(...) + {channel, ref_rms, freq, vmax})`.

**Dialog:**
- Each channel row gets `cal-ref-{ch}`, opening an inline panel:
  - `cal-ref-set`: select of the dataset's time-bearing sets; defaults to the current set.
  - `cal-ref-level` (default `94`) with `cal-ref-level-unit`:
    - `dB SPL` when the row unit is Pa;
    - otherwise an rms in the row's unit, default `10` for m/s² and `1` for others.
    - dB SPL converts as `ref_rms = P_REF*10**(L/20)`.
  - `cal-ref-freq` (default `1000`; `159.2` when the row unit is m/s²).
  - `cal-ref-measure` measures and fills that row's sensitivity.
  - `cal-ref-warning` lists the warnings.
  - `cal-ref-stop-note` shows "valid only while this channel's gain knob and pad stay where they were" whenever the chosen set's gain for that channel is unstated or not at a range end.
- Apply then writes `method 'reference_tone'` provenance with `reference {level, level_unit, freq}`.

- [ ] **Step 1: Write the failing vitest.**
  - The fake engine returns sensitivity 0.0335 → `measureReferenceTone` resolves with it.
  - 94 dB SPL → `ref_rms` sent equals 1.0024 (±1e-4).
  - The level unit follows the row unit.
- [ ] **Step 2: Run** `npx vitest run tests/analysis/referenceTone.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Add the `@engine` Playwright spec** in `e2e/calibrate.spec.ts`. Load a fixture with a 1 kHz tone (generate it in the spec via the existing fixture helpers; rms 0.0335), open Calibrate, Measure at 94 dB SPL with unit Pa → the sensitivity field reads `0.0335` (3 s.f.) and Apply makes the y-label read dB re 20 µPa after Calc PSD. Rebuild the engine wheel first. Run `npx playwright test e2e/calibrate.spec.ts`. Expected: PASS.
- [ ] **Step 5: Run** `npm run check`, `npx vitest run`. Expected: PASS.
- [ ] **Step 6: Commit** `feat(webui): calibrate from a reference tone (acoustic or accelerometer calibrator)`

### Task 10: carry calibration forward to new recordings

**Files:**
- Create: `webui/src/lib/stores/carriedCal.ts`
- Modify: `webui/src/components/CalibrateDialog.svelte` (tick `cal-carry`), `webui/src/components/Tray.svelte` (pass through)
- Modify: `webui/src/lib/analysis/actions.ts` (`addRecordedSet` 2331–2382: apply after `applyCaptureDefaults`, skipped for hidden captures)
- Modify: `webui/src/components/cards/SetupCard.svelte` (note + clear)
- Test: `webui/tests/stores/carriedCal.test.ts` (new), `webui/tests/analysis/addRecordedSet.test.ts`

**Interfaces:**
- Consumes: Task 8 `ChannelCalibration`, `setCalFactors(..., {provenance})`, `provenanceFromSet`.
- Produces:
  - `type CarriedChannelCal = {sensitivity: number; unit: string; provenance: ChannelCalibration}`
  - `carriedCal`: a Svelte store of `Record<string /* deviceKey */, Record<number /* ch */, CarriedChannelCal>>`. It is persisted to `localStorage['pydvma.carriedCal.v1']`, every access in try/catch, and works with storage unavailable. Methods:
    - `set(deviceKey, ch, entry)`
    - `clear(deviceKey?)`
    - `forDevice(deviceKey): Record<number, CarriedChannelCal>`
  - `deviceKeyFor(settings): string`: `settings.device_name` when stored; else the caps name of `device_driver:device_index` at capture time, recorded on the item by `recordingToItem`; else `device_driver`.
  - `carryWarnings(entry: CarriedChannelCal, now: Pick<ChannelCalibration, 'gain_db' | 'input_mode' | 'pad'>): string[]`. Returns a message for each of gain, mode or pad that differs, e.g. `"channel 1: calibrated at gain 60 dB, this recording states 50 dB"`. If the gain is unstated at either end: `"channel 1: gain not stated, so pydvma cannot tell whether it moved"`. `[]` when equal.

**Behaviour:**
- The dialog tick `cal-carry` ("use for new recordings too") is unticked by default. When ticked, Apply stores each applied channel's entry under the set's device key.
- In `addRecordedSet`, for a non-hidden capture whose device key has entries:
  1. `setCalFactors` with those sensitivities/units and provenance `{...entry.provenance, carried: true}`;
  2. raise ONE info toast (12 s) joining `carryWarnings` per carried channel when any is non-empty;
  3. carried channels beyond the capture's channel count are ignored.
- Setup shows `setup-carried-cal-note`: "calibration carried for channels 1, 2 (Pa)", plus `setup-carried-cal-clear`, when the selected device has entries.

- [ ] **Step 1: Write the failing vitest.**
  - The store round-trips through a fake localStorage and survives a throwing one.
  - `carryWarnings` for equal/different/unstated gains returns the exact strings above.
  - `addRecordedSet` with a carried entry for ch 0 → the new set's `channel_cal_factors[0] === 1/0.0335`, `units[0] === 'Pa'`, `channel_calibration[0].carried === true`; a different stated gain → a toast containing "calibrated at gain"; a hidden capture → untouched.
- [ ] **Step 2: Run** `npx vitest run tests/stores/carriedCal.test.ts tests/analysis/addRecordedSet.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same, `npm run check`, `npx vitest run`, and `npx playwright test e2e/calibrate.spec.ts`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(webui): opt-in calibration carry-forward to new recordings, with gain/pad change warnings`

### Task 11: long recordings

**Files:**
- Create: `dev/long_capture_check.py` (headless harness)
- Modify (as the measurements require):
  - `pydvma/serve.py`: the `max_size` at ~1888. Give `/engine` its own larger cap or none, keep `/ws` capped, enforce per path.
  - `pydvma/journal.py`: `PENDING_CAPTURES_MAX_BYTES` and eviction 272–314.
  - `pydvma/streams.py`: the full-length `stored_time_data_windowed` / rfft copies at 1395–1403, 2324–2331 and 3286–3293. Drop them or compute lazily, after confirming their consumers with grep.
  - `pydvma/container.py`: `save_bytes`, compression for large members.
  - `webui/src/lib/audio/bridge.ts`: 482–489 and 915–916, parse the container once.
  - `webui/src/lib/codec/dvma.ts`: `writeDvma` level for large members.
  - `webui/src/App.svelte`: `bootFileRestore` 684–775.
  - `webui/src/lib/files/autosave.ts`.
- Test: `tests/test_journal.py`, `tests/test_container.py`, `webui/tests/codec/dvma.test.ts`, `webui/tests/files/autosave.test.ts` (or the existing restore test file), plus the harness run recorded in `dev/2026-11-06-id44-bench.md`.

**Harness (`dev/long_capture_check.py`):**
- Spawns `python -m pydvma.serve --driver mock --port 8771 --session-dir <tmp> --save-dir <tmp>`. Port 8771 is new: list it beside the other claimants in the e2e port comment.
- Requests `channels=8, fs=48000, duration=150` (the same bytes as 4 ch × 300 s, in half the wall time) over `/ws` with `max_size=None`.
- Then over `/engine` (Origin `http://127.0.0.1:8771`): `calc_psd`, `calc_sono` (one channel), `journal_set` with the document, `journal_get`, `files_save`, `files_read`.
- Prints per step: OK/FAIL, seconds, bytes, peak RSS of the serve process.
- Exit 0 only if every step is OK.

**Fix rules (from the spec):** no silent loss; nothing that worked before may break.
- `/engine` accepts whole-document and whole-capture frames at the target size.
- The journal never evicts the newest capture, and logs any eviction at WARNING with the byte counts.
- A capture over the budget is still journaled when it is the only pending one.
- `bootFileRestore` offers the IndexedDB autosave when it is newer than the server journal's document.
- Members over 16 MiB are written `ZIP_STORED` (Python) / level 0 (TS). Smaller members keep deflate. Both readers already handle both.

- [ ] **Step 1: Write the harness; run it against unmodified code.** Record the baseline table in the bench doc. Expected: FAIL at the `/engine` cap and the journal.
- [ ] **Step 2: Write the failing unit tests.**
  - journal: a single capture of 300 MB (synthetic bytes) stays pending, and an eviction logs a warning;
  - container: a 20 MiB member round-trips and is stored uncompressed; a small member is still deflated;
  - TS codec: the same;
  - restore: when the IDB autosave timestamp is newer than the journal doc, `bootFileRestore` offers the IDB one (test the decision helper extracted from App.svelte into `webui/src/lib/files/restoreChoice.ts` as `chooseRestore(journal: {doc?: {savedAt: number}} | null, idb: {savedAt: number} | null): 'journal' | 'idb' | 'none'`).
- [ ] **Step 3: Implement the fixes.** Re-run the unit tests until they PASS.
- [ ] **Step 4: Re-run the harness.** Expected: exit 0. Record the after table and the 20-channel ceiling statement (from measured bytes per channel-second) in the bench doc.
- [ ] **Step 5: Run** `python -m pytest -q`, `npx vitest run`, `npm run check`, and with `BRIDGE_E2E=1` the existing bridge/session-journal/derived-save specs. Expected: PASS.
- [ ] **Step 6: Commit** in two or three commits: harness and baseline; server-side fixes; client-side fixes.

### Task 12: hardware verification, docs and wrap-up (coordinator)

**Files:**
- Create: `dev/id44_hw_check.py`, `dev/2026-11-06-id44-bench.md`, `docs/web-logger/acoustics.md` (add to `mkdocs.yml` nav)
- Modify: `dev/hardware-lessons-learnt.md`, `docs/web-logger/calibration.md`, `TODO.md`, `CHANGELOG.md` (`## Unreleased`), `CLAUDE.md` (current focus)

**Harness (`dev/id44_hw_check.py`):**
- PASS/FAIL checks:
  - device found by name;
  - native rates;
  - nominal pinned to 48000;
  - 24-bit;
  - loopback exactness (DAW 1+2 at −70 dBFS ↔ inputs 21/22, ±0.01 dB);
  - optional `--daw-thru-channel N`: the DAW 3 tone at −70 dBFS into input N and the gain in dB, printed with level linearity at −80/−70/−60.
- One duplex stream only. Never changes the rate unless `--rate` is given.

**Steps:**
- [ ] **Step 1:** Run `dev/id44_hw_check.py --daw-thru-channel 2`. Expected: PASS, gain +50.46 ± 0.05 dB.
- [ ] **Step 2:** Rebuild the engine wheel, `python scripts/stage_webui.py`, start `pydvma-serve` (soundcard driver). In the Browser pane:
  - select the iD44: per-channel rows, top-stop buttons, optical note, 48 kHz;
  - capture 30 s on 4 channels at ch1 gain 60 mic;
  - check the input-health warnings for channels 3–4 if their gain is stated;
  - calibrate ch1 by sensitivity 0.0335 V/Pa with carry ticked;
  - capture again: it arrives in Pa;
  - Calc PSD with A-weighting and third-octave bands: the y-label reads `PSD (dB(A) re (20 µPa)²/Hz)`;
  - Save to the working folder, reload, check it all restores.
  - Capture 5 s at fs 8000 with the iD44 still at 48 kHz: the set reports fs 8000, a 1 kHz DAW tone (−60 dBFS) is at 1 kHz, and the nominal rate never left 48000 (spec goal 8).
  - Screenshot for Tore.
- [ ] **Step 3:** Write the bench doc:
  - the facts in the design's "What the bench established";
  - the Task 11 tables;
  - the gain measurement;
  - the 96 kHz input count and the line-pad/other-channel stop checks are still to do with Tore.
- [ ] **Step 4:** Write the docs page and the calibration doc updates:
  - cabling, phantom, stops/pad, spec-sheet vs calibrator, carry-forward, dB SPL, weighting, bands, long recordings and the measured ceiling;
  - link audient.com for the manual.
- [ ] **Step 5:** TODO.md entries:
  - statistics;
  - mic response correction (normalise the chart to 0 dB at the calibrator frequency);
  - live-scope SPL;
  - iD44 on Windows;
  - channels 1/3/4 stops and the line-path pad check (Tore at the panel);
  - the 96 kHz input count;
  - verify the `no_signal` threshold with phantom off;
  - band-level table export;
  - the Yeti.
- [ ] **Step 6:** Full gate:
  - `python -m pytest -q`;
  - `npx vitest run`;
  - `npm run check`;
  - Playwright full (incl. `@engine`) plus `BRIDGE_E2E=1`;
  - `python -m mkdocs build --strict`.
  Expected: all green, apart from known environment skips, which are listed.
- [ ] **Step 7:** CHANGELOG Unreleased entry and CLAUDE.md current-focus paragraph. Commit.
- [ ] **Step 8:** Ask Tore before deleting `id44/`. The facts are captured; the PDFs are Audient's and stay out of the public repo.
