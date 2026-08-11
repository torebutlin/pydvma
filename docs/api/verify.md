# Input-Scaling Verification

Verify the whole input chain — physical gain knobs included — by
measuring a source of known level and comparing against the volts
pydvma predicts. Unlike a relative level meter or coherence check, this
validates *absolute* scaling.

## Known-Source Verification

::: pydvma.verify.verify_input_scaling
    options:
      show_source: false
      heading_level: 3

## Rigol DG1022Z SCPI Wrapper

`RigolDG1022Z` is a minimal SCPI wrapper (via `pyvisa`) used as the
known-level source for `verify_input_scaling` on hardware whose
loopback cannot verify absolute scaling (e.g. a sound card's digital
loopback, which copies the output stream pre-preamp).

::: pydvma.verify.RigolDG1022Z
    options:
      show_source: false
      heading_level: 3
      members: true
