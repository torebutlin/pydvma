# Wave C — Windows NI hardware-session checklist

Runnable verification for the Wave-C NI work (`pydvma serve` bridge NI
depth + `_ni_backend.device_capabilities`). **Everything in Wave C was
written and tested on macOS with a MOCKED `nidaqmx`** — no NI code has
touched real hardware yet. This checklist is what to run on Tore's
Windows machine (the three NI devices + `ao0 → ai0` BNC loopbacks per
`CLAUDE.md`) to confirm it works for real.

Lab kit (from `CLAUDE.md`):

| Enumerated device | Product | AI | AO | Sampling | Notes |
|---|---|---|---|---|---|
| USB-6003 (Dev3) | USB-6003 | 8 | 2 | **multiplexed** (skew) | low-cost; SW-timed AO; **label-swap caveat** (see §5) |
| USB-6212 | USB-6212 | 16 | 2 | multiplexed | M-series; **HW-timed AO / shared-clock sync** |
| cDAQ-9174 chassis | — | 4 | 2 | **simultaneous** (DSA) | `cDAQ1Mod1`=NI 9234 (AI, IEPE), `cDAQ1Mod2`=NI 9260 BNC (AO) |

`ao0 → ai0` loopback is wired on each device (self-contained — no hammer
tap needed). Tick each box as you go; note the device/product beside any
failure.

---

## 0. Environment sanity

```powershell
cd C:\Users\tb267\Documents\GitHub\pydvma
python -c "import nidaqmx, pydvma; print('nidaqmx', nidaqmx.__version__)"
python -c "import pydvma.streams as s; print('ni backend live:', s.ni is not None)"
```

- [ ] `nidaqmx` imports and reports a version.
- [ ] `ni backend live: True`.
- [ ] `pip install -e .[serve,ni,soundcard]` (bridge + NI + soundcard extras present).
- [ ] `pip install websockets` present (the `[serve]` extra).

---

## 1. Existing hardware pytest suite

The mocked Mac suite is green (`pytest -q` → 246 passed / 4 skipped as of
this session). On Windows the hardware suite
(`tests/test_acquisition_hardware.py`) discovers whatever is plugged in
at collection time and parametrizes across every device with ≥1 AI and
≥1 AO channel; stimulus-dependent tests self-skip when no loopback
signal is detected.

```powershell
python -m pytest -m hardware -v
```

Expect one parametrization per connected loopback device
(`[USB-6003]`, `[USB-6212]`, `[cDAQ1]`). Key tests to watch pass:

- [ ] `test_basic_acquisition` — plain capture, shape + dtype.
- [ ] `test_multichannel_acquisition[2]` / `[4]`.
- [ ] `test_multimodule_acquisition_spans_ai_modules` (chassis only).
- [ ] `test_pretrigger_with_stimulus` — **AO loopback fires a real
      trigger**; captured peak matches the driven amplitude.
- [ ] `test_pretrigger_positioning` — crossing lands at exactly
      `pretrig_samples`.
- [ ] `test_pretrigger_timeout_no_crash` — timeout fallback returns the
      buffer tail (no `IndexError`).
- [ ] `test_iepe_excitation_applies` / `test_iepe_warmup_settles_bias_transient`
      (9234 only).
- [ ] `test_iepe_rejected_on_unsupported_device` (6003/6212).
- [ ] `test_stream_reuses_when_signature_matches` /
      `test_stream_rebuilds_when_signature_changes`.
- [ ] `test_suggest_ni_settings_end_to_end`.

**Also verify the `AutoRegN` fix (TODO Phase C item 6 tail)** — capture
with a `chunk_size` outside {10, 100, 1000} on each device; the callback
cadence now equals the read size (`_ni_callback_interval`), so this must
not backlog or hang:

```powershell
python -c "import pydvma as d; s=d.MySettings(device_driver='nidaq',device_index=0,channels=1,fs=5000,chunk_size=2048,stored_time=0.5); ds=d.log_data(s); print(ds.time_data_list[0].time_data.shape)"
```

- [ ] Non-{10,100,1000} `chunk_size` (e.g. 2048) captures cleanly per device.

---

## 2. `device_capabilities` against real hardware

New this wave: `_ni_backend.device_capabilities(name)` /
`entry_capabilities(entry)` read the real nidaqmx Device/PhysicalChannel
properties (`ai_max_multi_chan_rate`, `ai_max_single_chan_rate`,
`ai_min_rate`, `ao_max_rate`, `ao_min_rate`,
`ai_simultaneous_sampling_supported`,
`ai_current_int_excit_discrete_vals`, and per-channel `ai_term_cfgs`).
Confirm the mocked values match reality:

```powershell
python -c "from pydvma import _ni_backend as n; import json; [print(e['name'], '->', json.dumps(n.entry_capabilities(e))) for e in n.enumerate_devices()]"
```

- [ ] **USB-6003**: `simultaneous=false`, `iepe_supported=false`,
      `terminal_configs` includes `DAQmx_Val_RSE`.
- [ ] **USB-6212**: `simultaneous=false`, `iepe_supported=false`,
      `ao_max_rate` reported (HW-timed AO).
- [ ] **cDAQ1** (chassis): AI fields come from the 9234 —
      `simultaneous=true`, `iepe_supported=true`,
      `iepe_currents=[0.002]`, `terminal_configs=['DAQmx_Val_PseudoDiff']`;
      AO fields come from the 9260 — `ao_max_rate` ≈ 51200,
      `ao_min_rate` ≈ 1613, `ao_supported=true`.
- [ ] Rate bounds are sane (9234 `ai_min_rate` ≈ 1613, `ai_max_rate`
      ≈ 51200). **DSA ladder caveat**: the driver reports only min/max
      and snaps a requested `fs` to the nearest `fs_base/(256·n)` step —
      these are bounds, not a promise every rate between is legal.

---

## 3. Bridge + webui, per device

Build the UI once (or run the Vite dev server against the bridge), then
start the bridge with the NI driver:

```powershell
cd webui; npm install; npm run build; cd ..
pydvma-serve --driver nidaq --ui-dir webui\dist --open
```

(Or during dev: `cd webui; npm run dev`, then open
`http://localhost:5173/?bridge=ws://127.0.0.1:8760/ws`.)

The bridge prints `pydvma serve listening on http://127.0.0.1:8760/`.
For each device (select it in the Setup device dropdown — bridge devices
appear as `NI: <name> (<ai> ch)`):

### 3a. Enumeration + capabilities handshake
- [ ] On `hello`, `capabilities.backends` includes `nidaq`.
- [ ] `devices.nidaq` lists the three devices (chassis collapsed to one
      `cDAQ1` entry) and each carries an inline `caps` object.
- [ ] `device_caps["nidaq:<i>"]` and `fs_ladders`/`max_channels` maps
      carry the device's rates + AI/AO channel counts.
- [ ] Setup grows its NI group (IEPE / terminal config / pretrigger)
      when `nidaq` is present.

### 3b. Live monitor (oscilloscope)
- [ ] `start_monitor` streams the live time trace; `stop_monitor` /
      leaving the tab halts it.
- [ ] Multi-channel monitor shows the right channel count.

### 3c. Log WITHOUT pretrigger
- [ ] "Log Data" (no pretrigger) round-trips a `.dvma` set into the
      tray; time trace looks right.
- [ ] Data reads in **volts** (see §4), not ±1 normalised.

### 3d. Log WITH pretrigger (AO loopback = trigger source)
Arm a pretrigger (e.g. `pretrig_samples=50`, threshold ~0.2 V) AND
configure an output sweep so the `ao0 → ai0` loopback drives the
trigger:
- [ ] Status sequence over the ws is `armed` → `triggered` →
      `log_result` (+ container). The `triggered` event is best-effort
      (polled ~10 Hz); if the trigger is very fast it may be missed and
      you'll see `armed` → `timeout` instead — the captured set is still
      correct either way.
- [ ] With NO stimulus and a short `pretrig_timeout`: `armed` →
      `timeout` → `log_result`, no crash (buffer-tail fallback).
- [ ] Captured window places the threshold crossing at ~`pretrig_samples`.

### 3e. IEPE on the 9234 (chassis only)
- [ ] Enable `iepe_excit_current_A=0.002` on an AI channel; bridge log
      shows the ~2 s IEPE settling pause, then captures.
- [ ] Attempting IEPE on the 6003/6212 returns a clear error (not a
      silent no-op).
- [ ] **Do NOT enable IEPE on a channel wired to the AO loopback** — the
      excitation current drives back into the AO terminal.

### 3f. Output sweep through the 9260 (chassis AO)
Configure `output_device_driver='nidaq'`, output on `cDAQ1Mod2`, and a
`log` with `output={type:'sweep', amp:…, f1:…, f2:…}`:
- [ ] Sweep plays on the 9260; the loopback captures it on the 9234 AI.
- [ ] `amp` is interpreted in **volts** and clamped to the 9260 rail
      (±4.24 V). Requesting `output_VmaxNI` above the 9260 max should
      raise a clear pre-flight error (not opaque DAQmx -200077).
- [ ] `use_output_as_ch0=true` prepends the drive signal as channel 0.
- [ ] Nyquist guard: `max(f1,f2) > min(fs,output_fs)/2` is rejected with
      a clear error before capture.

---

## 4. VmaxNI scaling expectations (TODO Phase C item 14)

**The scaling change itself is DEFERRED to this hardware session** — do
NOT alter scaling code from Mac. The NI capture path already returns
volts (`acquisition.log_data`, item 134), so the bridge inherits that;
this section is a hardware CHECK of that behaviour, not a code change.

Drive a known AO amplitude through the loopback and verify:
- [ ] Captured AI data reads in **volts** matching the driven amplitude
      (within loopback attenuation) — e.g. a 1.0 V sweep reads ~±1.0 V,
      NOT ±1.0 "normalised full-scale".
- [ ] `VmaxNI` sets the **AI input range** (`min_val/max_val` on
      `add_ai_voltage_chan`), and picking a smaller `VmaxNI` covering the
      signal improves resolution but does NOT rescale the stored numbers.
- [ ] Clipping warning fires when `|data| > 0.95 · VmaxNI` (drive the
      loopback near the rail to confirm).
- [ ] The 9234 ignores `VmaxNI` ≠ ±5 V (fixed range) — data still reads
      in volts.

If any residual ±1 assumption surfaces on the NI path during these
checks, note it here — the four known survivors are in **`gui.py`**
(the frozen Qt logger), NOT in the bridge/acquisition path, so they
should not affect `pydvma serve`.

---

## 5. Known caveats to watch

- **USB-6003 (this unit) AO label swap** — the `ao0`/`ao1` screw-terminal
  labels on this specific 6003's breakout box may not match the silicon
  channels reported to nidaqmx. If §3d/§3f AO→AI tests fail on the 6003,
  **physically swap the wire between the two AO terminals** as the first
  sanity check before suspecting a fault. Not believed to affect other
  6003 units.
- **Multiplexed AI skew (6003, 6212)** — a single ADC scans the channel
  list, so multi-channel samples are skewed by the inter-channel convert
  time (not simultaneous). Expect a small inter-channel phase offset on
  multi-channel captures; this is hardware, not a bug. The 9234/9260 are
  DSA (per-channel ADC/DAC) → truly simultaneous.
- **USB-600x software-timed AO** — AI/AO cannot share a hardware sample
  clock; the AO task runs unsynchronised. Only the 6212 (M-series) and
  the cDAQ chassis support shared-clock AI/AO sync.
- **Stale DAQmx reservation (-50103)** — if a prior Python process
  crashed, a device may report "resource reserved". The recorder
  auto-resets the device once and retries; if it persists, unplug/replug
  or `nidaqmx` device reset.
- **IEPE warmup cost** — first capture with IEPE on costs ~2 s extra
  (bias settling through the 9234 AC-coupling HPF); subsequent captures
  reuse the warmed task and are fast.

---

## Sign-off

- [ ] §1 hardware pytest suite green on all three devices.
- [ ] §2 `device_capabilities` matches real hardware.
- [ ] §3 bridge + webui drives each device (enumerate / monitor / log ±
      pretrigger / IEPE / output).
- [ ] §4 VmaxNI scaling behaves as described.
- [ ] Caveats in §5 understood; any deviations recorded above.

File any surprises back into `CLAUDE.md` (hardware section) and the
Wave-C notes so the next session inherits them.
