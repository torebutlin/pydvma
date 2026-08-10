# Windows / NI verification checklist — soundcard capture-rate work

Written 2026-08-10 on the Mac, for the next session on the Windows PC.
Background and measurements: `dev/plans/2026-08-10-focusrite-scarlett-design.md`.

Everything below landed on `master` and is green on macOS. **Nothing in
it has ever run against NI hardware or on Windows.** Two of the changes
alter behaviour that was previously hardware-verified, so this is a
regression check first and a new-feature check second.

---

## 0. Before you start

```bash
git pull
pip install -e .
```

The engine wheel does **not** need rebuilding — no pyodide-side code
changed. `webui/dist` does need a rebuild if you want to eyeball the UI
(`npm --prefix webui run build`).

---

## 1. Regression check — did the refactor disturb NI? (do this first)

The capture-rate decision moved into `streams.select_capture_fs`, and
`acquisition.log_data` was restructured around it. NI devices publish no
rate ladder, so they take the `'unknown'` path and **should behave
exactly as before**. Prove it:

```bash
python dev/bridge_hw_check.py            # vs `pydvma-serve --driver nidaq`
pytest tests/ -q                          # full suite, hardware live
```

Expected: **44/44** on `bridge_hw_check` (as of 2026-07-10) and the
pytest count from the last PC session (407 passed / 19
capability-skipped) plus the ~60 new soundcard tests, which are
mock/fake-backed and should pass anywhere.

Pay particular attention to **check E** (`lpf_on` on all three devices)
— see §2, because its expected numbers have CHANGED for the 9234.

## 2. Behaviour change — the 9234 now oversamples LESS

`streams.oversample_strategy` is new and decides how far above `fs` an
`lpf_on` capture runs. `'auto'` follows
`streams.hardware_antialiases`:

| device | `simultaneous` | anti-aliases? | strategy | changed? |
|---|---|---|---|---|
| USB-6003 | False | no | `'highest'` | no |
| USB-6212 | False | no | `'highest'` | no |
| cDAQ 9234 | True | yes (delta-sigma) | **`'lowest'`** | **YES** |

Previously every NI device captured at `max_input_fs`. The 9234 now
captures at the lowest rate with 2.56x headroom over `fs` instead,
because a delta-sigma converter is already anti-aliased at its own rate
— exactly like the Scarlett. This was Tore's explicit call.

What to check on the 9234:

- An `lpf_on` log at, say, `fs = 2000` now captures around 5120 Hz
  rather than 51200 Hz. Confirm `lpf_capture_fs` on the returned
  settings reflects that, and that the delivered `fs` is still 2000.
- **The anti-alias proof must still hold.** Re-run the existing
  alias-rejection test (`tests/test_acquisition_hardware.py`, the 6212
  anti-alias proof pattern) against the 9234: an out-of-band tone must
  still be rejected. If it is not, `'lowest'` is wrong for this module
  and we revert it to `'highest'` — say so rather than working around it.
- **Noise floor is the expected regression.** Oversampling buys
  ~10*log10(M) dB of broadband-noise process gain, so capturing at
  5120 instead of 51200 Hz gives up ~10 dB of it. Measure the noise
  floor both ways on a quiet channel (`oversample='highest'` vs
  `'auto'`). If that 10 dB matters more than the data volume for lab
  use, the default for DSA should go back to `'highest'` — this is a
  judgement call for Tore, and the setting exists precisely so it can be
  made per-measurement.

Force either behaviour explicitly:

```python
dvma.MySettings(..., lpf_on=True, oversample='highest')   # old behaviour
dvma.MySettings(..., lpf_on=True, oversample='lowest')    # new default on DSA
```

## 3. The open question — does WASAPI lie like CoreAudio?

On macOS, `sd.check_input_settings()` accepts **every** sample rate
because CoreAudio will resample to reach any of them, and PortAudio
never retunes the hardware clock. Measured on a Scarlett 2i2: a
requested 8 kHz from a 192 kHz clock gave **-4.3 dB passband droop at
3 kHz and only -11.7 dB alias rejection**, versus -1.0 dB / -64.7 dB
from a 44.1 kHz clock. Same request, quality decided by whatever rate
the last application left the device at.

Windows shared-mode WASAPI also resamples, so the same class of bug
probably exists. **It has not been measured.** Until it is, non-macOS
behaviour is deliberately unchanged: `native_input_rates` returns `[]`
off macOS, so `select_capture_fs` reports `'unknown'` and everything
takes the legacy path.

To find out, with a USB audio interface on the PC:

1. Ask PortAudio what it claims:
   ```python
   import sounddevice as sd
   for r in (3000, 8000, 22050, 44100, 48000, 96000, 176400, 192000):
       try:
           sd.check_input_settings(device=IDX, samplerate=r, channels=1)
           print(r, 'accepted')
       except Exception as e:
           print(r, 'rejected', e)
   ```
   If it accepts rates the device cannot run, WASAPI lies too.
2. Measure whether it matters, using the method from
   `dev/scarlett_hw_check.py`: play a tone **generated at the hardware
   rate** and capture at a lower requested rate, then look for it folded
   back in band. Generating the tone inside the low-rate stream aliases
   it before it reaches the device and makes the test meaningless — that
   mistake produced two wrong results during the original investigation,
   so do not repeat it.
3. If confirmed, the fix is the WASAPI equivalent of
   `pydvma/_coreaudio.py`: `IAudioClient.IsFormatSupported` for the real
   ladder, and exclusive mode (or a `PaWasapiStreamInfo` exclusive flag
   through `sounddevice`'s `extra_settings`) to stop the resampler.
   ASIO would side-step it entirely but adds a dependency and a driver
   install.

Note the 2i2's own loopback trick is not available on an arbitrary
interface — check whether whatever is plugged in has one, or wire a
physical output-to-input loopback.

## 4. Output stimulus on a shared clock

New: on a sound card, playback and capture share one clock, so
`acquisition.log_data` resamples the stimulus onto the capture rate when
input and output resolve to the same device
(`streams.output_shares_input_clock`). NI is unaffected — it returns
False for the `nidaq` driver, and the AO rate stays independently
configurable under its own `ao_max_rate` cap.

Worth confirming on the PC only that the NI stimulus path is untouched:
`bridge_hw_check.py` already covers pretrigger + output sweep on all
three devices.

## 5. New soundcard features to sanity-check on Windows

These are macOS-verified but should at least not CRASH on Windows:

- `pydvma/_coreaudio.py` must import cleanly and report
  `available() == False`. `tests/test_coreaudio.py` covers this with a
  fake, and 4 tests skip off macOS.
- `MySettings(capture_fs=..., oversample=..., input_gain_db=...,
  input_mode=...)` must construct without error on any driver.
- `serve.build_capabilities()` must still produce a valid payload —
  `native_rates` and `channel_roles` will simply be `[]` for
  uncharacterised devices and off macOS.

## 6. If a Scarlett (or any characterised interface) is on the PC

`pydvma/_soundcard_specs.py` holds per-model facts the audio APIs do not
expose. Two apply to the 2i2 4th Gen and are worth re-confirming:

- **Inputs 3/4 are a digital loopback** of outputs 1/2, not analogue
  inputs. Setup shows "channels 3+ are the device's digital loopback,
  not inputs" once the channel count reaches 3.
- **Calibrated volts.** `input_gain_db` + `input_mode` derive `VmaxSC`
  from the published maximum input level. Confirmed on the Mac to
  0.10 dB (a 5.000 Vpp sine at 9 dB Line gain read 0.505072 FS →
  4.9498 V pk measured vs 4.8932 V predicted). If the PC has a
  different interface, add a profile rather than assuming the 2i2's
  numbers transfer.

---

## Reporting back

Record the outcome in `TODO.md` under "Soundcard / Focusrite Scarlett
follow-ups" and, if the WASAPI question is answered either way, in
`dev/plans/2026-08-10-focusrite-scarlett-design.md` §6 (which currently
says only that it is unmeasured).
