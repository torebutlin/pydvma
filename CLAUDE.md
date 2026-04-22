# Working with Claude on pydvma

Auto-loaded by Claude Code at the start of every session. Contributors
and collaborators: the concrete filesystem paths below are for the
**maintainer's Windows development machine** (``C:\Users\tb267\...``)
and don't apply on Mac/Linux — translate them to your own paths or
put personal overrides in ``CLAUDE.local.md`` (which stays
gitignored). The rules themselves (edit master directly, verify
hardware-touching code before handing back, docstring discipline,
etc.) are repo-wide conventions worth following regardless of OS.

## Workflow (solo developer)

- **Edit directly on `master`** in the main repo folder
  (`C:\Users\tb267\Documents\GitHub\pydvma`). Don't create feature
  branches for isolation — the sole developer uses `git revert` or
  `git reset` as the undo button.
- Exception: genuinely risky or multi-file refactors can still use a
  branch; ask before creating one.
- Commit small, coherent changes to `master` as you go. Don't batch a
  session's worth of edits into one commit. Push only when the user
  explicitly asks.
- Worktrees under `.claude/worktrees/` are for Claude's isolated
  exploration only; prefer not to use them for iterative development
  against real hardware.

## Iteration mechanics

- The main repo is installed editably (`pip install -e .`), so saved
  file changes are immediately live in the notebook kernel.
- Recommend `%load_ext autoreload` + `%autoreload 2` in the first
  notebook cell so no kernel restart is needed.

## Environment

- Windows 11, Python via `C:\Users\tb267\anaconda3\python.exe` (base
  conda env). No per-project env.
- `pytest` available from base; tests live in `tests/`.

## Hardware (for NI acquisition work)

Three NI devices are connected on this Windows machine:

- **USB-6003** — low-cost; AO is software-timed (no hardware AI/AO
  sync possible).
- **USB-6212** — M-series; hardware-timed AO, supports shared-clock
  AI/AO sync.
- **cDAQ-9174 chassis** with module `cDAQ1Mod1` = NI 9234 (4-ch AI)
  and `cDAQ1Mod2` = NI 9260 BNC (2-ch AO). Shared-clock sync via
  chassis timebase.

**BNC loopback is wired ao0 → ai0 on each device** — that's the
standard test stimulus. Self-contained: the user does not need to be
physically present to tap a hammer or similar.

## Verify, don't assume

Before writing code against an external library (esp. `nidaqmx`,
`PyDAQmx`, `sounddevice`), verify the real API up front:

- `python -c "import nidaqmx.constants as c; print([x.name for x in c.ProductCategory])"`
- Inspect `dir(obj)` on a live object, or check the upstream source.

A unit test with a fake object only proves the code matches the fake —
it does not prove the fake matches reality. The 2025 `C_DAQ_CHASSIS`
vs `COMPACT_DAQ_CHASSIS` bug came from exactly this gap.

## Tests — build them as you go

Every behaviour-changing edit should either have a test (new or
updated) or a reason not to. Split by where they can run:

- **Mac-runnable (no hardware):** pure-Python logic — `_ni_backend`
  enumeration + channel-string construction, signal generation, FFT /
  TF maths, datastructure round-trips. Use mocks for nidaqmx.
- **PC-only (NI hardware plugged in):** live acquisition, pretrigger
  timing, AO loopback, clock routing. These live in
  `tests/test_acquisition_hardware.py` and auto-skip on Mac via a
  module-level `nidaqmx` detection check.
- **Parametrize over whatever is plugged in.** Don't hard-code
  `device_index=0` in tests — discover devices at collection time and
  iterate. Hardware varies (USB-6003, USB-6212, cDAQ chassis with
  different modules) and tests should keep working as devices are
  swapped in and out.
- **Cover with AND without pretrigger.** Pretrigger changes the call
  path significantly (buffer re-init, callback interaction, timeout
  fallback). Both must be exercised. The "with" variant should drive
  the AO → BNC loopback to produce a real trigger event.

## Run hardware checks yourself before handing code back

Since this Windows machine has all three NI devices connected and
Python + nidaqmx work from the shell, verify NI-touching code by
running it headlessly from the terminal (`python -c` or a small
inline script) before asking the user to try it in the notebook.
GUI is not required for driver / callback / trigger logic. Catch
hardware-surfaced bugs at write time, not at notebook time.

## Docstrings

- Write a docstring for every new public function, method, or class.
- When reading or editing an existing function, check its docstring
  against current behaviour and update any inaccuracy you notice —
  even if the edit itself was unrelated. The published MkDocs site
  (`docs/`) is generated from these, so drift becomes user-visible.
- Include hardware constraints and conventions you discover
  (voltage ranges, terminal-config requirements, clock routing
  limits, sample-rate ladders on DSA modules) in the docstring of
  the function that enforces or depends on them. Don't bury them in
  `# comments` — the rendered docs won't pick those up.

## Scope discipline

See `TODO.md` for the roadmap; it's organised by phase. Don't
freelance Phase D items when doing Phase A work.
