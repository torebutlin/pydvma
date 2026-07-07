"""``pydvma serve`` — the local acquisition bridge server.

This module hosts a tiny, dependency-light server that lets the
no-install browser UI (``webui/``) drive **real** acquisition hardware
on the user's machine.  The browser normally captures audio through the
Web Audio API; when it is opened *through* ``pydvma serve`` it instead
talks a small WebSocket protocol to this process, which wraps pydvma's
existing acquisition surface (`pydvma.streams`, `pydvma.acquisition`)
verbatim.  Everything a soundcard/NI recorder can do — configure a
stream, watch a live oscilloscope feed, log a triggered capture — is
exposed over one port.

Design constraints (locked by the Wave-B brief,
``dev/plans/2026-07-07-waveB-serve-bridge-brief.md``):

* **One port, one origin.**  A single :func:`websockets.asyncio.server.serve`
  listener on ``127.0.0.1`` (loopback only — no auth, lab-local stance).
  ``GET /ws`` upgrades to the control WebSocket; every other ``GET`` is
  handled by :meth:`BridgeServer._process_request`, which serves the
  built UI (``--ui-dir``, defaulting to the dev checkout's
  ``<repo>/webui/dist`` or, in an installed wheel, the packaged
  ``pydvma/_webui`` — see :func:`_resolve_ui_dir`) and the ``/config``
  launch document.
* **Pure-Python dependency.**  Only ``websockets`` is required (the
  ``[serve]`` extra); it has zero transitive deps and works under the
  base install everywhere pydvma runs.
* **``streams.py`` / ``acquisition.py`` are used unchanged.**  This
  module is purely additive; it never edits the recorder classes.

Protocol v1
===========

The WebSocket carries two frame kinds:

* **Text frames = JSON control messages** (client⇄server RPC).
* **Binary frames = sample/​container payloads** (server→client), each
  prefixed with a fixed 20-byte little-endian header (see below).

Client → server (``{"type": ...}``):

===============  ==================================================
``hello``        → server replies ``capabilities``
``configure``    ``{settings: {...}}`` — whitelisted MySettings kwargs
                 (see :data:`_SETTINGS_WHITELIST`); builds a MySettings
                 and calls ``streams.start_stream``; replies ``status``
``start_monitor``  begin the ~30 Hz incremental oscilloscope feed
``stop_monitor``   stop the feed
``log``          ``{duration, pretrigger|null, output?, test_name?}`` —
                 runs ``acquisition.log_data`` in a worker thread;
                 replies ``log_result`` then a binary ``.dvma``
                 container frame. See "Output / stimulus" and
                 "Pretrigger status events" below.
``cancel``       best-effort stop of the monitor / in-flight log
===============  ==================================================

Server → client:

* ``capabilities`` — ``{v, backends, devices:{soundcard, nidaq},
  fs_ladders, max_channels, device_caps, pretrigger, ao}``.  All keys
  are stable across the additive Wave-C growth; ``v`` stays ``1``.
  ``fs_ladders`` and ``max_channels`` are now **per-device maps** keyed
  by ``"<driver>:<index>"`` (e.g. ``"soundcard:0"``, ``"nidaq:0"``):
  ``fs_ladders[id]`` is a list of candidate sample rates and
  ``max_channels[id]`` is ``{input, output}``.  ``device_caps[id]`` is
  a richer per-device object (soundcard: max in/out channels, default
  samplerate, candidate rates, ``ao``; NI: ``ai_max_rate``,
  ``ai_min_rate``, ``simultaneous``, ``ao_max_rate``, ``iepe_supported``
  / ``iepe_currents``, ``terminal_configs``, ``ao``).  Each ``nidaq``
  device entry also carries its cap object inline under ``caps`` (an
  additive key — the pre-existing enumerate fields are unchanged).
  ``ao`` (top-level) is ``True`` when any backend can output.
* ``status`` — acknowledgement of ``configure`` / monitor lifecycle,
  carries the resolved stream geometry; also the pretrigger arming
  events ``armed`` / ``triggered`` / ``timeout`` (see below).
* ``log_result`` — capture metadata (``nChannels``, ``nSamples``,
  ``fs``, ``testName``, ``byteLength``) immediately followed by the
  ``.dvma`` binary frame.
* ``error`` — ``{message}`` for any rejected request.

Output / stimulus (Wave C)
==========================

The MySettings ``output_*`` fields (``output_device_driver``,
``output_device_index``, ``output_channels``, ``output_channels_spec``,
``output_fs``, ``output_VmaxNI``, ``output_VmaxSC``,
``use_output_as_ch0``) are ordinary constructor kwargs, so they flow in
through the normal ``configure.settings`` whitelist — no protocol change
needed.  The stimulus *waveform* is described separately, in an optional
``output`` object on the ``log`` message::

    {"type": "log", "duration": 2.0, "pretrigger": null,
     "output": {"type": "sweep", "amp": 0.1, "f1": 20, "f2": 2000,
                "duration": 1.0}}

``type`` is one of ``sweep`` / ``gaussian`` / ``uniform`` (``white`` is
accepted as an alias for ``uniform``; ``none`` / ``null`` = no output);
``amp`` is in volts; ``f1`` / ``f2`` are the sweep endpoints or the
noise band-pass corners in Hz; ``duration`` defaults to the log
duration.  Keys outside ``{type, amp, f1, f2, duration}`` are rejected.
When present, the server builds the waveform with
``acquisition.signal_generator`` (rejecting ``max(f1,f2) > fs/2`` with a
clear Nyquist error, mirroring the Qt logger's ``create_output_signal``)
and hands it to ``acquisition.log_data(..., output=y)`` exactly the way
``gui.LogDataThread`` does — including the ``use_output_as_ch0`` prepend.

Pretrigger status events (Wave C)
=================================

When a ``log`` arms a pretrigger (``pretrigger`` carries a non-null
``samples``), the connection pushes lifecycle ``status`` frames so the
UI can show an "armed / waiting for trigger" state:

* ``{event: "armed"}`` — emitted immediately, before the blocking
  capture starts.
* ``{event: "triggered"}`` — emitted (once) if the recorder's
  ``trigger_detected`` flag is observed to flip ``True`` while the
  capture runs.  A companion asyncio task polls that flag at
  :data:`PRETRIG_POLL_HZ` (~10 Hz) from the event loop while the capture
  blocks in the executor thread.  Best-effort: on a fast trigger the
  flag may be reset by ``log_data`` before a poll sees it — the
  authoritative outcome is always the ``log_result`` that follows.
* ``{event: "timeout"}`` — emitted if the arming window closed without
  ``trigger_detected`` ever being seen (the ``pretrig_timeout`` fallback
  in ``log_data``).  ``MockRecorder`` never triggers, so the mock
  backend always exercises this path — armed → timeout → log_result.

Binary frame header (little-endian, 20 bytes)::

    offset  type  field        notes
    0       u8    magic        MAGIC (0xDB)
    1       u8    ver          PROTOCOL_VERSION (1)
    2       u8    msgType      1=sample chunk, 2=.dvma container
    3       u8    dtype        0=float32, 255=opaque bytes (container)
    4       u16   streamId     per-connection stream id
    6       u16   nChannels
    8       u32   seq          monotonic per connection
    12      u32   nSamples     samples/channel in this frame
    16      f32   fs           sample rate (Hz)

For ``msgType=1`` the payload is ``nSamples × nChannels`` interleaved
row-major (sample-major, channel-minor) ``float32`` — byte-identical to
the Web-Audio ``MonitorChunk`` the webui monitor store consumes, so a
``BridgeSource`` can hand the store a chunk without reshaping.  For
``msgType=2`` the payload is the raw ``.dvma`` zip bytes (the client
strips the 20-byte header and parses the container natively); the
header's ``nChannels`` / ``nSamples`` / ``fs`` describe the contained
``TimeData`` for convenience.

Incremental monitor scheme
==========================

The webui monitor store (``webui/src/lib/stores/monitor.ts``) owns its
own ring buffer and *appends* every chunk it receives.  If the bridge
re-sent the whole oscilloscope window each tick it would duplicate
samples in that ring.  So the bridge sends only the samples that are
**new since the last tick**.

pydvma's recorders (`streams.Recorder`, `streams.Recorder_NI_nidaqmx`,
`streams.MockRecorder`) expose a fixed-size sliding window
``osc_time_data`` of shape ``(num_chunks*chunk_size, channels)``: each
hardware callback shifts it left by ``chunk_size`` and appends the new
chunk at the tail, so the *newest* samples are always at the end and old
samples scroll off the front.  There is no monotonic sample counter to
read, and we must not edit the recorder.  So the bridge derives the
new-sample count from elapsed wall-clock time (:class:`_MonitorCursor`):
``n_new = round(fs · Δt)``, and ships ``osc_time_data[-n_new:]`` — the
freshly-scrolled tail.  Because the buffer physically scrolled by ≈
``fs·Δt`` samples between ticks, that tail does not overlap the previous
tick's tail.  This matches decision #3 (lossy latest-state, ~30 Hz):
tiny clock/scheduling jitter can drop or duplicate a sample at the
boundary, which is invisible on an oscilloscope.

**Overrun / drop-oldest.**  If a tick is delayed so long that
``fs·Δt`` exceeds the whole window (``buffer_len``), the older samples
have already scrolled off and are unrecoverable — the cursor caps
``n_new`` at ``buffer_len`` and ships only the newest window's worth,
silently dropping the oldest missed samples (the same drop-oldest
semantics as the ring buffer itself).

CLI
===

Console script ``pydvma-serve`` and ``python -m pydvma.serve`` both call
:func:`main`.  Flags: ``--port`` (default :data:`DEFAULT_PORT`),
``--ui-dir``, ``--settings`` (a JSON file pre-loaded for ``/config``),
``--driver`` (default ``mock``; ``soundcard``/``nidaq`` require their
extras), ``--open`` (open a browser at the served UI).
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import importlib.resources
import inspect
import io
import json
import mimetypes
import os
import struct
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Any

import numpy as np

from . import acquisition
from . import container
from . import options
from . import streams
from . import _ni_backend

# ---- protocol constants ----

#: Magic byte at offset 0 of every binary frame (a sanity check the
#: client verifies before trusting the header).  The Wave-B brief wrote
#: it mnemonically as ``0xDV``; ``DV`` is not a valid hex byte, so the
#: concrete on-wire value is 0xDB and both sides use this constant.
MAGIC = 0xDB
#: Protocol version stamped into the header and reported in ``capabilities``.
PROTOCOL_VERSION = 1

MSG_CHUNK = 1       #: binary msgType — a sample chunk (float32 payload)
MSG_CONTAINER = 2   #: binary msgType — a ``.dvma`` container (zip payload)

DTYPE_F32 = 0       #: header dtype — interleaved little-endian float32
DTYPE_BYTES = 255   #: header dtype — opaque bytes (container payload)

#: ``struct`` format for the 20-byte little-endian header.
_HEADER_STRUCT = struct.Struct('<BBBBHHIIf')
HEADER_SIZE = _HEADER_STRUCT.size  # 20

# ---- server config defaults ----

DEFAULT_PORT = 8760
DEFAULT_HOST = '127.0.0.1'
#: Monitor feed cadence (frames/second).  Decision #3: ~30 Hz.
MONITOR_HZ = 30.0
#: Poll cadence (Hz) for the pretrigger ``trigger_detected`` flag while a
#: pretriggered ``log`` capture blocks in the executor thread.
PRETRIG_POLL_HZ = 10.0

#: Standard capture sample rates advertised as fs-ladder candidates.  The
#: soundcard backend filters these with ``sd.check_input_settings``; the
#: NI backend bounds them by the device's reported ``ai_min_rate`` /
#: ``ai_max_rate`` (a DSA module snaps a requested rate to its discrete
#: ladder at task-create time — see ``_ni_backend.device_capabilities``).
_STANDARD_RATES = (8000, 11025, 16000, 22050, 32000, 44100, 48000,
                   88200, 96000, 176400, 192000)

#: MySettings constructor kwargs the ``configure`` message accepts.
#: Derived from the signature so it stays in sync automatically; any key
#: outside this set is rejected with a clear error.
_SETTINGS_WHITELIST = frozenset(
    name
    for name, p in inspect.signature(options.MySettings.__init__).parameters.items()
    if name != 'self' and p.kind != inspect.Parameter.VAR_KEYWORD
)


#: Kept-open context stack for any UI directory materialised out of a
#: non-filesystem loader (a zip-imported wheel).  Closed at process exit
#: so an extracted temp copy lives exactly as long as the server.
_UI_RESOURCE_STACK = contextlib.ExitStack()
atexit.register(_UI_RESOURCE_STACK.close)


def _repo_default_ui_dir() -> Path:
    """Return the dev-checkout UI dir (``<repo>/webui/dist``).

    Resolved relative to this file so an editable checkout serves the
    freshly built UI.  In an installed wheel this path
    (``site-packages/webui/dist``) does not exist, so resolution falls
    through to the packaged copy — see :func:`_resolve_ui_dir`.
    """
    return Path(__file__).resolve().parents[1] / 'webui' / 'dist'


def _packaged_ui_dir() -> Path | None:
    """Return the UI bundled inside the installed package, or ``None``.

    The built browser UI is staged into ``pydvma/_webui`` (by
    ``scripts/stage_webui.py``) and shipped in the wheel via the
    ``_webui/**/*`` package-data glob.  Located through
    :mod:`importlib.resources` rather than a ``__file__``-relative path so
    it resolves correctly however the package is installed — including a
    zip-imported wheel, where the directory is extracted to a temporary
    location kept alive for the process lifetime.  Returns ``None`` when
    no UI was packaged (e.g. the lean engine wheel), so the caller can
    fall back to the no-UI help page.
    """
    try:
        root = importlib.resources.files('pydvma') / '_webui'
    except (ModuleNotFoundError, TypeError, FileNotFoundError):
        return None
    # Common case: the package is unpacked on disk (regular pip install
    # and editable checkouts alike), so the resource is already a real
    # directory we can serve straight from.
    try:
        on_disk = Path(os.fspath(root))
    except TypeError:
        on_disk = None
    if on_disk is not None:
        return on_disk if on_disk.is_dir() else None
    # Non-filesystem loader (zip-imported wheel): materialise once.
    try:
        if not root.is_dir():
            return None
    except (FileNotFoundError, OSError):
        return None
    extracted = _UI_RESOURCE_STACK.enter_context(importlib.resources.as_file(root))
    return Path(extracted)


def _resolve_ui_dir(explicit: str | None) -> Path | None:
    """Resolve which built UI directory ``pydvma serve`` should serve.

    Priority (decision #3 of the wheel-packaging brief):

    1. an explicit ``--ui-dir`` (returned as given, even if missing — the
       server then shows the no-UI page, surfacing the bad path);
    2. the dev checkout's ``<repo>/webui/dist`` when it exists;
    3. the UI packaged inside the installed wheel (``pydvma/_webui``);
    4. ``None`` — nothing to serve, so the bridge shows its help page.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    repo = _repo_default_ui_dir()
    if repo.exists():
        return repo
    return _packaged_ui_dir()


# ---- binary frame encoding ----

def _encode_header(msg_type: int, dtype: int, stream_id: int, n_channels: int,
                   seq: int, n_samples: int, fs: float) -> bytes:
    """Pack the fixed 20-byte little-endian binary frame header.

    See the module docstring for the field layout.  All integer fields
    are masked to their on-wire width so a caller passing a Python int
    never overflows ``struct.pack``.
    """
    return _HEADER_STRUCT.pack(
        MAGIC, PROTOCOL_VERSION, msg_type & 0xFF, dtype & 0xFF,
        stream_id & 0xFFFF, n_channels & 0xFFFF,
        seq & 0xFFFFFFFF, n_samples & 0xFFFFFFFF, float(fs),
    )


def encode_chunk(stream_id: int, seq: int, data: np.ndarray, fs: float) -> bytes:
    """Encode a sample chunk (``msgType=1``) as a binary frame.

    Args:
        stream_id: per-connection stream identifier.
        seq: monotonic sequence number for this connection.
        data: ``(n_samples, n_channels)`` array; written row-major
            (interleaved, sample-major) as little-endian float32.
        fs: sample rate in Hz.

    Returns:
        The 20-byte header followed by the interleaved float32 payload.
    """
    data = np.ascontiguousarray(data, dtype='<f4')
    if data.ndim != 2:
        raise ValueError('chunk data must be 2-D (n_samples, n_channels)')
    n_samples, n_channels = data.shape
    header = _encode_header(MSG_CHUNK, DTYPE_F32, stream_id, n_channels,
                            seq, n_samples, fs)
    return header + data.tobytes()


def encode_container(stream_id: int, seq: int, dvma_bytes: bytes,
                     n_channels: int, n_samples: int, fs: float) -> bytes:
    """Encode a ``.dvma`` container (``msgType=2``) as a binary frame.

    The payload is the raw ``.dvma`` zip; the header carries the
    contained ``TimeData``'s channel/sample/rate metadata purely for the
    client's convenience (it can size buffers before parsing).
    """
    header = _encode_header(MSG_CONTAINER, DTYPE_BYTES, stream_id, n_channels,
                            seq, n_samples, fs)
    return header + bytes(dvma_bytes)


def decode_header(frame: bytes) -> dict[str, Any]:
    """Decode the 20-byte binary frame header into a dict.

    Mirrors :func:`_encode_header` for tests and (potential) Python
    clients.  Raises ``ValueError`` if the frame is too short or the
    magic byte is wrong.
    """
    if len(frame) < HEADER_SIZE:
        raise ValueError('frame shorter than the %d-byte header' % HEADER_SIZE)
    (magic, ver, msg_type, dtype, stream_id, n_channels,
     seq, n_samples, fs) = _HEADER_STRUCT.unpack(frame[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError('bad magic byte 0x%02X (expected 0x%02X)' % (magic, MAGIC))
    return {
        'magic': magic, 'ver': ver, 'msgType': msg_type, 'dtype': dtype,
        'streamId': stream_id, 'nChannels': n_channels, 'seq': seq,
        'nSamples': n_samples, 'fs': fs,
    }


# ---- incremental monitor cursor ----

class _MonitorCursor:
    """Tracks the oscilloscope feed so only *new* samples are shipped.

    The recorder's ``osc_time_data`` is a sliding window with no sample
    counter, so we estimate how many samples scrolled in since the last
    tick from elapsed wall-clock time: ``n_new = round(fs · Δt)``.  See
    the module docstring's "Incremental monitor scheme" for the full
    rationale and the drop-oldest overrun rule.

    Bind one cursor to a given ``(fs, buffer_len)``; recreate it if
    either changes (e.g. after a reconfigure mid-monitor).
    """

    def __init__(self, fs: float, buffer_len: int):
        self.fs = float(fs)
        self.buffer_len = int(buffer_len)
        self._t_last: float | None = None

    def start(self, now: float) -> None:
        """Establish the ``t=0`` reference; call once before ``take``."""
        self._t_last = now

    def take(self, now: float) -> tuple[int, bool]:
        """Return ``(n_new, overrun)`` for the interval ending at ``now``.

        ``n_new`` is clamped to ``[0, buffer_len]``; ``overrun`` is True
        when the raw estimate exceeded ``buffer_len`` (older samples had
        already scrolled off and were dropped).  Advances the internal
        clock, so successive calls tile the timeline without overlap.
        """
        if self._t_last is None:
            raise RuntimeError('call start() before take()')
        dt = now - self._t_last
        if dt < 0:
            dt = 0.0
        self._t_last = now
        n = int(round(self.fs * dt))
        overrun = n > self.buffer_len
        if overrun:
            n = self.buffer_len
        if n < 0:
            n = 0
        return n, overrun


# ---- capabilities ----

def _bounded_standard_rates(fs_min, fs_max) -> list[int]:
    """The :data:`_STANDARD_RATES` that fall within ``[fs_min, fs_max]``.

    Either bound may be ``None`` (unbounded on that side).  Best-effort
    fs-ladder candidates for an NI device — see the DSA discrete-ladder
    caveat on ``_ni_backend.device_capabilities``: these are candidates
    inside the reported bounds, not a guarantee that every one is legal
    on a DSA module.
    """
    lo = float(fs_min) if fs_min else 0.0
    hi = float(fs_max) if fs_max else float('inf')
    return [int(r) for r in _STANDARD_RATES if lo <= r <= hi]


def _soundcard_candidate_rates(sd, index: int, max_in: int,
                               default_sr: float) -> list[int]:
    """Standard rates the soundcard input device accepts (best-effort).

    Probes each standard rate with ``sd.check_input_settings`` (cheap —
    PortAudio answers whether the format is supported without opening a
    stream).  The device's ``default_samplerate`` is always included.
    Output-only devices (``max_in <= 0``) just get their default rate.
    If the probe API is missing or misbehaves, the full standard list is
    returned unfiltered rather than an empty one.
    """
    rates: set[int] = set()
    if default_sr and default_sr > 0:
        rates.add(int(round(default_sr)))
    if max_in <= 0:
        return sorted(rates)
    checker = getattr(sd, 'check_input_settings', None)
    if checker is None:
        return sorted(rates | {int(r) for r in _STANDARD_RATES})
    try:
        for r in _STANDARD_RATES:
            try:
                checker(device=index, channels=1, samplerate=float(r))
                rates.add(int(r))
            except Exception:
                pass  # unsupported at this rate on this device — skip it
    except Exception:
        # The probe API itself is unusable (signature mismatch, etc.):
        # advertise the full standard list rather than trust it.
        return sorted(rates | {int(r) for r in _STANDARD_RATES})
    return sorted(rates)


def _soundcard_device_caps() -> tuple[list[str], dict[int, dict]]:
    """Per-device soundcard capabilities from ``sounddevice.query_devices``.

    Returns ``(names, caps_by_index)`` where ``names`` is the
    list-of-name shape ``devices.soundcard`` has always carried (kept
    backward-compatible) and ``caps_by_index[i]`` holds
    ``max_input_channels`` / ``max_output_channels`` /
    ``default_samplerate`` / ``candidate_rates`` / ``ao``.  Fully guarded
    — any PortAudio hiccup yields ``([], {})`` so the handshake never
    breaks.
    """
    sd = streams.sd
    if sd is None:
        return [], {}
    try:
        devices = sd.query_devices()
    except Exception:
        return [], {}
    names: list[str] = []
    caps: dict[int, dict] = {}
    for i, d in enumerate(devices):
        try:
            name = d['name']
            max_in = int(d.get('max_input_channels', 0))
            max_out = int(d.get('max_output_channels', 0))
            default_sr = float(d.get('default_samplerate', 0.0) or 0.0)
        except Exception:
            names.append(str(d))
            continue
        names.append(name)
        caps[i] = {
            'driver': 'soundcard', 'index': i, 'name': name,
            'max_input_channels': max_in,
            'max_output_channels': max_out,
            'default_samplerate': default_sr,
            'candidate_rates': _soundcard_candidate_rates(
                sd, i, max_in, default_sr),
            'ao': max_out > 0,
        }
    return names, caps


def _nidaq_device_caps() -> tuple[list[dict], dict[int, dict]]:
    """Per-device NI capabilities, and the enumerated entries with caps
    attached inline.

    Returns ``(entries, caps_by_index)``.  ``entries`` is
    ``_ni_backend.enumerate_devices()`` output with an additive ``caps``
    key merged onto each entry (so the webui can read a device's caps
    straight off the enumerate list); ``caps_by_index[i]`` is the same
    cap object.  Guarded end-to-end — a device that fails to answer a
    capability query yields ``{}`` for that device rather than aborting
    the handshake.  Only called when ``nidaqmx`` is importable.
    """
    try:
        entries = list(_ni_backend.enumerate_devices())
    except Exception:
        return [], {}
    caps_by_index: dict[int, dict] = {}
    for i, e in enumerate(entries):
        try:
            c = _ni_backend.entry_capabilities(e)
        except Exception:
            c = {}
        entry = dict(e)
        entry['caps'] = c
        entries[i] = entry
        caps_by_index[i] = c
    return entries, caps_by_index


def build_capabilities() -> dict[str, Any]:
    """Build the ``capabilities`` payload advertised on ``hello``.

    Reports which backends this process can drive (``mock`` always;
    ``soundcard`` when ``sounddevice`` imported; ``nidaq`` when
    ``nidaqmx`` imported), the enumerated devices for each, and **real
    per-device capabilities** — sample-rate ladders, channel counts, and
    a rich ``device_caps`` map (see the module docstring for the exact
    shape).  All lookups are guarded so a half-installed or flaky driver
    never breaks the handshake.
    """
    backends = ['mock']
    devices: dict[str, list] = {'soundcard': [], 'nidaq': []}

    fs_ladders: dict[str, list[int]] = {}
    max_channels: dict[str, dict[str, int]] = {}
    device_caps: dict[str, dict] = {
        # The mock backend has no real device to probe; a stable stub
        # keeps the map uniform (and its AO is always available via
        # `streams.setup_output_mock`).
        'mock:0': {'driver': 'mock', 'index': 0,
                   'name': 'Mock signal generator', 'ao': True},
    }

    if streams.sd is not None:
        backends.append('soundcard')
        sc_names, sc_caps = _soundcard_device_caps()
        if sc_names:
            devices['soundcard'] = sc_names
        for i, c in sc_caps.items():
            did = 'soundcard:%d' % i
            device_caps[did] = c
            fs_ladders[did] = c['candidate_rates']
            max_channels[did] = {'input': c['max_input_channels'],
                                 'output': c['max_output_channels']}

    if streams.ni is not None:
        backends.append('nidaq')
        entries, ni_caps = _nidaq_device_caps()
        devices['nidaq'] = entries
        for i, c in ni_caps.items():
            did = 'nidaq:%d' % i
            e = entries[i]
            device_caps[did] = {
                'driver': 'nidaq', 'index': i, 'name': e.get('name'),
                'product_type': e.get('product_type'),
                'is_chassis': e.get('is_chassis'),
                'ai_channel_count': e.get('ai_channel_count'),
                'ao_channel_count': e.get('ao_channel_count'),
                **c,
                'ao': bool(c.get('ao_supported'))
                or (e.get('ao_channel_count') or 0) > 0,
            }
            fs_ladders[did] = _bounded_standard_rates(
                c.get('ai_min_rate'), c.get('ai_max_rate'))
            max_channels[did] = {'input': int(e.get('ai_channel_count') or 0),
                                 'output': int(e.get('ao_channel_count') or 0)}

    ao = any(bool(c.get('ao')) for c in device_caps.values())

    return {
        'v': PROTOCOL_VERSION,
        'backends': backends,
        'devices': devices,
        # Per-device maps keyed by "<driver>:<index>" (Wave C); were an
        # empty {} / None placeholder in v1's first cut.
        'fs_ladders': fs_ladders,
        'max_channels': max_channels,
        'device_caps': device_caps,
        'pretrigger': True,
        'ao': ao,
    }


# ---- capture helper (runs in a worker thread) ----

def _capture_to_dvma(settings, test_name, output=None):
    """Run a blocking capture and serialise it to ``.dvma`` bytes.

    Executed in a thread-pool worker because ``acquisition.log_data``
    sleeps for ``stored_time`` seconds (or blocks waiting for a
    trigger).  Returns ``(dvma_bytes, n_samples, n_channels)`` where the
    counts come from the captured ``TimeData``.  The container is
    written through :func:`pydvma.container.save` (the one save story)
    to a temp file and read back as bytes — the browser owns the "save
    to disk" step (decision #4).

    ``output`` is an optional ``(N, output_channels)`` stimulus waveform
    in volts (built by :func:`acquisition.signal_generator`); it is
    forwarded verbatim to ``log_data(..., output=...)`` so the AO path
    (and ``settings.use_output_as_ch0``) behaves exactly as it does for
    the Qt logger.
    """
    dataset = acquisition.log_data(settings, test_name=test_name, output=output)
    td = dataset.time_data_list[0]
    n_samples, n_channels = td.time_data.shape

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.dvma')
    tmp.close()
    try:
        container.save(dataset, tmp.name)
        with open(tmp.name, 'rb') as fh:
            dvma_bytes = fh.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return dvma_bytes, int(n_samples), int(n_channels)


# ---- output / stimulus ----

#: Waveform types accepted in a ``log`` ``output`` spec, mapped to
#: ``acquisition.signal_generator``'s ``sig`` argument.  ``white`` is an
#: alias for band-limited uniform noise.
_OUTPUT_TYPE_ALIASES = {
    'sweep': 'sweep', 'gaussian': 'gaussian',
    'uniform': 'uniform', 'white': 'uniform',
}
#: Keys accepted inside a ``log`` ``output`` object; anything else is
#: rejected with a clear error.
_OUTPUT_SPEC_KEYS = frozenset({'type', 'amp', 'f1', 'f2', 'duration'})


def _build_output_signal(settings, output_spec):
    """Turn a ``log`` message ``output`` object into a stimulus waveform.

    Returns ``(y, generated)`` where ``y`` is an
    ``(N, output_channels)`` volts array from
    :func:`acquisition.signal_generator` (or ``None`` when the spec asks
    for no output) and ``generated`` is True only when a waveform was
    built.  Mirrors the Qt logger's ``create_output_signal``: the
    Nyquist guard rejects ``max(f1, f2) > min(fs, output_fs) / 2`` with a
    clear error, and the type/amp/f1/f2/duration fields map onto
    ``signal_generator``'s ``sig`` / ``amplitude`` / ``f`` / ``T``.

    Raises ``ValueError`` on a non-object spec, an unknown key, an
    unknown ``type``, or a Nyquist violation.
    """
    if output_spec is None:
        return None, False
    if not isinstance(output_spec, dict):
        raise ValueError('log.output must be an object or null')
    unknown = set(output_spec) - _OUTPUT_SPEC_KEYS
    if unknown:
        raise ValueError(
            'unknown output key(s): %s. Allowed: %s'
            % (', '.join(sorted(map(str, unknown))),
               ', '.join(sorted(_OUTPUT_SPEC_KEYS))))
    raw_type = output_spec.get('type')
    if raw_type is None or str(raw_type).lower() in ('none', ''):
        return None, False
    sig = _OUTPUT_TYPE_ALIASES.get(str(raw_type).lower())
    if sig is None:
        raise ValueError(
            'unknown output type %r; expected one of %s (or none)'
            % (raw_type, ', '.join(sorted(_OUTPUT_TYPE_ALIASES))))

    amp = float(output_spec.get('amp', 0.0))
    f1 = float(output_spec.get('f1', 0.0))
    f2 = float(output_spec.get('f2', 0.0))
    duration = output_spec.get('duration')
    T = float(settings.stored_time) if duration is None else float(duration)

    f_max = max(f1, f2)
    fs_min = min(float(settings.fs), float(settings.output_fs))
    if f_max > fs_min / 2:
        raise ValueError(
            'highest output frequency %g Hz exceeds Nyquist '
            '(min input/output fs %g Hz / 2 = %g Hz)'
            % (f_max, fs_min, fs_min / 2))

    _t, y = acquisition.signal_generator(
        settings, sig=sig, T=T, amplitude=amp, f=[f1, f2],
        selected_channels='all')
    return y, True


# ---- the no-UI fallback page ----

_NO_UI_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>pydvma serve</title></head>
<body style="font-family:system-ui;max-width:40rem;margin:3rem auto;padding:0 1rem">
<h1>pydvma serve is running</h1>
<p>The WebSocket bridge is live at <code>/ws</code>, but no built UI was
found to serve.</p>
<p>To serve the browser app from this process, build it and point
<code>--ui-dir</code> at the output:</p>
<pre>cd webui &amp;&amp; npm install &amp;&amp; npm run build
pydvma-serve --ui-dir webui/dist</pre>
<p>During development you can instead run the Vite dev server
(<code>npm run dev</code>) and connect it to this bridge with
<code>?bridge=ws://{host}:{port}/ws</code>.</p>
</body></html>
"""


# ---- the server ----

class BridgeServer:
    """The ``pydvma serve`` WebSocket + static-file server.

    One instance owns the whole process: the loopback listener, the
    ``/config`` document, static UI serving, and one control WebSocket
    per connected browser tab.  Construct it, then ``await run()``.

    Args:
        host: bind address (loopback only in normal use).
        port: TCP port.
        ui_dir: directory of the built UI to serve, or ``None`` to serve
            only the WebSocket + a helpful 404 page.
        settings_json: dict returned verbatim from ``GET /config`` (the
            UI's launch document); ``{}`` when no ``--settings`` given.
        default_driver: ``device_driver`` injected into ``configure``
            messages that omit one (from ``--driver``).
    """

    def __init__(self, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 ui_dir: Path | None = None, settings_json: dict | None = None,
                 default_driver: str = 'mock'):
        self.host = host
        self.port = port
        self.ui_dir = ui_dir
        self.settings_json = settings_json or {}
        self.default_driver = default_driver
        self._server = None

    # -- HTTP (static + /config) --

    def _http_response(self, status: int, content_type: str, body: bytes,
                       reason: str = 'OK'):
        from websockets.http11 import Response
        from websockets.datastructures import Headers
        headers = Headers()
        headers['Content-Type'] = content_type
        headers['Content-Length'] = str(len(body))
        return Response(status, reason, headers, body)

    def _serve_static(self, path: str):
        """Serve a file from ``ui_dir`` for a plain GET request.

        Maps ``/`` to ``index.html``, guards against path traversal
        outside ``ui_dir``, and falls back to ``index.html`` for
        extension-less unknown routes (SPA behaviour).  Returns the
        no-UI 404 page when ``ui_dir`` is unset or missing.
        """
        if self.ui_dir is None or not self.ui_dir.exists():
            body = _NO_UI_HTML.format(host=self.host, port=self.port).encode('utf-8')
            return self._http_response(404, 'text/html; charset=utf-8', body,
                                       reason='Not Found')
        root = self.ui_dir.resolve()
        rel = path.lstrip('/') or 'index.html'
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return self._http_response(403, 'text/plain; charset=utf-8',
                                       b'Forbidden', reason='Forbidden')
        if not target.is_file():
            # SPA fallback: extension-less routes → index.html.
            last = rel.rsplit('/', 1)[-1]
            index = root / 'index.html'
            if '.' not in last and index.is_file():
                target = index
            else:
                return self._http_response(404, 'text/plain; charset=utf-8',
                                           b'Not Found', reason='Not Found')
        ctype, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        return self._http_response(200, ctype or 'application/octet-stream', body)

    def _process_request(self, connection, request):
        """``websockets`` process_request hook.

        Returns ``None`` for ``/ws`` (let the WebSocket handshake
        proceed), a JSON ``Response`` for ``/config``, or a static-file
        ``Response`` for anything else.
        """
        path = request.path.split('?', 1)[0]
        if path == '/ws':
            return None  # proceed with the WebSocket upgrade
        if path == '/config':
            body = json.dumps(self.settings_json).encode('utf-8')
            return self._http_response(200, 'application/json; charset=utf-8', body)
        return self._serve_static(path)

    # -- WebSocket control channel --

    async def _handler(self, websocket):
        """Per-connection entry point: dispatch control messages.

        Creates a fresh :class:`_Connection` (its own stream id, seq,
        and monitor task) and drives it until the socket closes, then
        tears the monitor down.
        """
        conn = _Connection(websocket)
        try:
            async for raw in websocket:
                if isinstance(raw, (bytes, bytearray)):
                    # v1 clients never send binary control frames.
                    continue
                await conn.dispatch(raw, self)
        finally:
            await conn.close()

    async def run(self):
        """Start listening and serve forever (until cancelled).

        Binds ``host:port`` (use port 0 for an ephemeral port; read it
        back from :attr:`sockets`) and blocks in the server's
        ``serve_forever`` loop.
        """
        from websockets.asyncio.server import serve
        async with serve(
            self._handler, self.host, self.port,
            process_request=self._process_request,
        ) as server:
            self._server = server
            await server.serve_forever()

    @property
    def sockets(self):
        """The listening sockets (available after :meth:`run` binds)."""
        return getattr(self._server, 'sockets', None)


class _Connection:
    """State for one browser tab: stream id, seq, and monitor task.

    Kept per-connection (not on :class:`BridgeServer`) so two tabs get
    independent sequence numbers and monitor loops.  The underlying
    ``streams.REC`` recorder is process-global, so concurrent tabs share
    one hardware stream — acceptable for the single-user lab stance.
    """

    _next_stream_id = 0

    def __init__(self, websocket):
        self.ws = websocket
        _Connection._next_stream_id = (_Connection._next_stream_id + 1) & 0xFFFF
        self.stream_id = _Connection._next_stream_id or 1
        self.seq = 0
        self.settings = None  # last configured MySettings
        self._monitor_task: asyncio.Task | None = None
        self._monitor_stop = asyncio.Event()
        self._log_task: asyncio.Task | None = None

    # -- helpers --

    async def _send_json(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj))

    async def _send_error(self, message: str) -> None:
        await self._send_json({'type': 'error', 'message': message})

    def _next_seq(self) -> int:
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFFFFFFFF
        return seq

    # -- dispatch --

    async def dispatch(self, raw: str, server: BridgeServer) -> None:
        """Parse and route one JSON control message."""
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            await self._send_error('invalid JSON control frame')
            return
        if not isinstance(msg, dict):
            await self._send_error('control frame must be a JSON object')
            return
        mtype = msg.get('type')
        try:
            if mtype == 'hello':
                await self._on_hello()
            elif mtype == 'configure':
                await self._on_configure(msg, server)
            elif mtype == 'start_monitor':
                await self._on_start_monitor()
            elif mtype == 'stop_monitor':
                await self._on_stop_monitor()
            elif mtype == 'log':
                await self._on_log(msg)
            elif mtype == 'cancel':
                await self._on_cancel()
            else:
                await self._send_error('unknown message type %r' % (mtype,))
        except Exception as exc:  # never let one bad request kill the socket
            await self._send_error('%s: %s' % (type(exc).__name__, exc))

    async def _on_hello(self) -> None:
        cap = build_capabilities()
        cap['type'] = 'capabilities'
        await self._send_json(cap)

    async def _on_configure(self, msg: dict, server: BridgeServer) -> None:
        raw_settings = msg.get('settings') or {}
        if not isinstance(raw_settings, dict):
            await self._send_error('configure.settings must be an object')
            return
        unknown = set(raw_settings) - _SETTINGS_WHITELIST
        if unknown:
            await self._send_error(
                'unknown setting(s): %s. Allowed keys: %s'
                % (', '.join(sorted(unknown)), ', '.join(sorted(_SETTINGS_WHITELIST)))
            )
            return

        kwargs = dict(raw_settings)
        kwargs.setdefault('device_driver', server.default_driver)
        driver = kwargs['device_driver']
        # Guard driver availability with a clear message before MySettings
        # (which would otherwise probe hardware / raise late).
        if driver == 'soundcard' and streams.sd is None:
            await self._send_error(
                "device_driver='soundcard' needs the [soundcard] extra "
                "(pip install pydvma[soundcard]); sounddevice is not available.")
            return
        if driver == 'nidaq' and streams.ni is None:
            await self._send_error(
                "device_driver='nidaq' needs the [ni] extra "
                "(pip install pydvma[ni]); nidaqmx is not available.")
            return

        settings = options.MySettings(**kwargs)
        streams.start_stream(settings)
        self.settings = streams.REC.settings if streams.REC is not None else settings

        rec = streams.REC
        osc_samples = int(rec.osc_time_data.shape[0]) if rec is not None else 0
        await self._send_json({
            'type': 'status',
            'event': 'configured',
            'streamId': self.stream_id,
            'driver': self.settings.device_driver,
            'fs': float(self.settings.fs),
            'channels': int(self.settings.channels),
            'chunkSize': int(self.settings.chunk_size),
            'oscSamples': osc_samples,
        })

    async def _on_start_monitor(self) -> None:
        if streams.REC is None:
            await self._send_error('start_monitor requires configure first')
            return
        if self._monitor_task is not None and not self._monitor_task.done():
            await self._send_json({'type': 'status', 'event': 'monitoring',
                                   'streamId': self.stream_id})
            return
        self._monitor_stop = asyncio.Event()
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        await self._send_json({'type': 'status', 'event': 'monitoring',
                               'streamId': self.stream_id})

    async def _on_stop_monitor(self) -> None:
        await self._stop_monitor()
        await self._send_json({'type': 'status', 'event': 'monitor_stopped',
                               'streamId': self.stream_id})

    async def _stop_monitor(self) -> None:
        self._monitor_stop.set()
        task, self._monitor_task = self._monitor_task, None
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self) -> None:
        """Ship incremental oscilloscope chunks at ~:data:`MONITOR_HZ`.

        Each tick reads the recorder's current ``osc_time_data`` window,
        asks the :class:`_MonitorCursor` how many samples are new, and
        sends that many from the tail as a ``msgType=1`` frame.  See the
        module docstring for the incremental scheme.
        """
        loop = asyncio.get_running_loop()
        tick = 1.0 / MONITOR_HZ
        cursor: _MonitorCursor | None = None
        try:
            while not self._monitor_stop.is_set():
                rec = streams.REC
                if rec is None:
                    await asyncio.sleep(tick)
                    continue
                osc = np.ascontiguousarray(rec.osc_time_data, dtype='<f4')
                buffer_len = osc.shape[0]
                n_channels = osc.shape[1] if osc.ndim == 2 else 1
                fs = float(rec.settings.fs)
                now = loop.time()

                if (cursor is None or cursor.fs != fs
                        or cursor.buffer_len != buffer_len):
                    cursor = _MonitorCursor(fs, buffer_len)
                    cursor.start(now)
                    await asyncio.sleep(tick)
                    continue

                n_new, _overrun = cursor.take(now)
                if n_new > 0:
                    payload = osc[buffer_len - n_new:, :]
                    frame = encode_chunk(self.stream_id, self._next_seq(), payload, fs)
                    await self.ws.send(frame)
                await asyncio.sleep(tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A send failure (socket closing) or transient recorder error
            # should end the loop quietly, not crash the connection.
            try:
                await self._send_error('monitor stopped: %s' % (exc,))
            except Exception:
                pass

    async def _on_log(self, msg: dict) -> None:
        if streams.REC is None or self.settings is None:
            await self._send_error('log requires configure first')
            return

        settings = self.settings
        duration = msg.get('duration')
        if duration is not None:
            settings.stored_time = float(duration)

        pretrigger = msg.get('pretrigger')
        if pretrigger is None:
            settings.pretrig_samples = None
        elif isinstance(pretrigger, dict):
            samples = pretrigger.get('samples')
            settings.pretrig_samples = None if samples is None else int(samples)
            if 'threshold' in pretrigger:
                settings.pretrig_threshold = float(pretrigger['threshold'])
            if 'channel' in pretrigger:
                settings.pretrig_channel = int(pretrigger['channel'])
            if 'timeout' in pretrigger:
                settings.pretrig_timeout = float(pretrigger['timeout'])
        else:
            await self._send_error('log.pretrigger must be an object or null')
            return

        # Optional stimulus: build the AO waveform here (validation errors
        # surface as a clean `error` before the capture starts).
        try:
            output_array, _generated = _build_output_signal(
                settings, msg.get('output'))
        except ValueError as exc:
            await self._send_error(str(exc))
            return

        test_name = msg.get('test_name') or msg.get('testName')

        armed = settings.pretrig_samples is not None
        if armed:
            await self._send_json({'type': 'status', 'event': 'armed',
                                   'streamId': self.stream_id})

        loop = asyncio.get_running_loop()
        self._log_task = asyncio.ensure_future(
            loop.run_in_executor(
                None, _capture_to_dvma, settings, test_name, output_array)
        )
        triggered = {'seen': False}
        poll_task = (asyncio.create_task(self._poll_trigger(triggered))
                     if armed else None)
        try:
            dvma_bytes, n_samples, n_channels = await self._log_task
        except asyncio.CancelledError:
            await self._send_error('log cancelled')
            return
        finally:
            self._log_task = None
            if poll_task is not None:
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass

        if armed and not triggered['seen']:
            await self._send_json({'type': 'status', 'event': 'timeout',
                                   'streamId': self.stream_id})

        await self._send_json({
            'type': 'log_result',
            'streamId': self.stream_id,
            'nChannels': n_channels,
            'nSamples': n_samples,
            'fs': float(settings.fs),
            'testName': test_name,
            'byteLength': len(dvma_bytes),
        })
        frame = encode_container(self.stream_id, self._next_seq(), dvma_bytes,
                                 n_channels, n_samples, float(settings.fs))
        await self.ws.send(frame)

    async def _poll_trigger(self, triggered: dict) -> None:
        """Emit a one-shot ``triggered`` status when the recorder arms.

        Polls ``streams.REC.trigger_detected`` at :data:`PRETRIG_POLL_HZ`
        from the event loop while a pretriggered capture blocks in the
        executor thread.  Sets ``triggered['seen']`` and sends the status
        frame the first time the flag is observed True, then returns; the
        caller cancels this task once the capture completes.  Best-effort:
        ``MockRecorder`` never triggers (so this only ever times out under
        the mock), and on a very fast real trigger ``log_data`` may reset
        the flag before a poll catches it — the authoritative outcome is
        the following ``log_result``.
        """
        tick = 1.0 / PRETRIG_POLL_HZ
        while True:
            rec = streams.REC
            if rec is not None and getattr(rec, 'trigger_detected', False):
                triggered['seen'] = True
                try:
                    await self._send_json({'type': 'status',
                                           'event': 'triggered',
                                           'streamId': self.stream_id})
                except Exception:
                    pass
                return
            await asyncio.sleep(tick)

    async def _on_cancel(self) -> None:
        """Best-effort cancel: stop the monitor and any in-flight log.

        The log runs a blocking capture in a worker thread that cannot be
        force-killed; cancelling only stops us awaiting its result (the
        thread finishes on its own).  Documented as best-effort.
        """
        await self._stop_monitor()
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        await self._send_json({'type': 'status', 'event': 'cancelled',
                               'streamId': self.stream_id})

    async def close(self) -> None:
        """Tear down on disconnect: stop the monitor loop."""
        await self._stop_monitor()


# ---- CLI ----

def _load_settings_file(path: str) -> dict:
    """Load and parse the ``--settings`` JSON file into a dict.

    Raises ``SystemExit`` with a clear message if the file is missing or
    not a JSON object, so a bad launch fails fast rather than serving a
    broken ``/config``.
    """
    p = Path(path)
    if not p.is_file():
        raise SystemExit('--settings file not found: %s' % path)
    try:
        data = json.loads(p.read_text())
    except ValueError as exc:
        raise SystemExit('--settings is not valid JSON: %s' % exc)
    if not isinstance(data, dict):
        raise SystemExit('--settings must be a JSON object, got %s'
                         % type(data).__name__)
    return data


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the ``pydvma-serve`` argument parser."""
    parser = argparse.ArgumentParser(
        prog='pydvma-serve',
        description='Local acquisition bridge for the pydvma browser UI.',
    )
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                        help='TCP port to listen on (default: %d)' % DEFAULT_PORT)
    parser.add_argument('--host', default=DEFAULT_HOST,
                        help='bind address (default: %s, loopback only)' % DEFAULT_HOST)
    parser.add_argument('--ui-dir', default=None,
                        help='directory of the built UI to serve (default: '
                             '<repo>/webui/dist in a checkout, else the UI '
                             'packaged in the installed wheel)')
    parser.add_argument('--settings', default=None,
                        help='JSON file pre-loaded and served at /config')
    parser.add_argument('--driver', default='mock',
                        choices=['mock', 'soundcard', 'nidaq'],
                        help="default device_driver for configure messages "
                             "that omit one (default: mock)")
    parser.add_argument('--open', action='store_true',
                        help='open the served UI in a web browser on start')
    return parser


def main(argv=None) -> int:
    """CLI entry point for ``pydvma-serve`` / ``python -m pydvma.serve``.

    Parses arguments, builds a :class:`BridgeServer`, optionally opens a
    browser, and runs until interrupted (Ctrl-C exits cleanly).
    """
    args = build_arg_parser().parse_args(argv)

    ui_dir = _resolve_ui_dir(args.ui_dir)

    settings_json = _load_settings_file(args.settings) if args.settings else {}

    server = BridgeServer(
        host=args.host, port=args.port, ui_dir=ui_dir,
        settings_json=settings_json, default_driver=args.driver,
    )

    url = 'http://%s:%d/' % (args.host, args.port)
    print('pydvma serve listening on %s (ws at %s/ws, driver=%s)'
          % (url, url.rstrip('/'), args.driver), file=sys.stderr)
    if ui_dir is None:
        print('  no built UI found; serving the bridge + a help page. '
              'Build webui/dist or pass --ui-dir.', file=sys.stderr)
    else:
        print('  serving UI from %s' % ui_dir, file=sys.stderr)
    if args.open:
        webbrowser.open(url)

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print('\npydvma serve stopped.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
