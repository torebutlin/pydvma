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
  built UI (``--ui-dir``, default ``<repo>/webui/dist``) and the
  ``/config`` launch document.
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
``log``          ``{duration, pretrigger|null, test_name?}`` — runs
                 ``acquisition.log_data`` in a worker thread; replies
                 ``log_result`` then a binary ``.dvma`` container frame
``cancel``       best-effort stop of the monitor / in-flight log
===============  ==================================================

Server → client:

* ``capabilities`` — ``{v, backends, devices:{soundcard, nidaq},
  fs_ladders, max_channels, pretrigger, ao}``.
* ``status`` — acknowledgement of ``configure`` / monitor lifecycle,
  carries the resolved stream geometry.
* ``log_result`` — capture metadata (``nChannels``, ``nSamples``,
  ``fs``, ``testName``, ``byteLength``) immediately followed by the
  ``.dvma`` binary frame.
* ``error`` — ``{message}`` for any rejected request.

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

#: MySettings constructor kwargs the ``configure`` message accepts.
#: Derived from the signature so it stays in sync automatically; any key
#: outside this set is rejected with a clear error.
_SETTINGS_WHITELIST = frozenset(
    name
    for name, p in inspect.signature(options.MySettings.__init__).parameters.items()
    if name != 'self' and p.kind != inspect.Parameter.VAR_KEYWORD
)


def _repo_default_ui_dir() -> Path:
    """Return the default ``--ui-dir`` (``<repo>/webui/dist``).

    Resolved relative to this file so an editable checkout serves the
    freshly built UI.  Installed wheels don't ship the built UI yet
    (see the packaging TODO in ``pyproject.toml``); when this path does
    not exist the server returns a helpful 404 page instead.
    """
    return Path(__file__).resolve().parents[1] / 'webui' / 'dist'


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

def build_capabilities() -> dict[str, Any]:
    """Build the ``capabilities`` payload advertised on ``hello``.

    Reports which backends this process can drive (``mock`` always;
    ``soundcard`` when ``sounddevice`` imported; ``nidaq`` when
    ``nidaqmx`` imported), the enumerated devices for each, and the
    pretrigger / analog-output feature flags.  All lookups are guarded
    so a half-installed driver never breaks the handshake.
    """
    backends = ['mock']
    devices: dict[str, list] = {'soundcard': [], 'nidaq': []}

    if streams.sd is not None:
        backends.append('soundcard')
        try:
            names = streams.get_devices_soundcard()
            if names:
                devices['soundcard'] = list(names)
        except Exception:
            pass

    if streams.ni is not None:
        backends.append('nidaq')
        try:
            devices['nidaq'] = _ni_backend.enumerate_devices()
        except Exception:
            devices['nidaq'] = []

    return {
        'v': PROTOCOL_VERSION,
        'backends': backends,
        'devices': devices,
        # DSA modules coerce fs onto a discrete divider ladder; the base
        # soundcard path accepts arbitrary rates. We do not enumerate a
        # per-device ladder here (best-effort — left for a follow-up).
        'fs_ladders': {},
        'max_channels': None,
        'pretrigger': True,
        'ao': True,
    }


# ---- capture helper (runs in a worker thread) ----

def _capture_to_dvma(settings, test_name):
    """Run a blocking capture and serialise it to ``.dvma`` bytes.

    Executed in a thread-pool worker because ``acquisition.log_data``
    sleeps for ``stored_time`` seconds (or blocks waiting for a
    trigger).  Returns ``(dvma_bytes, n_samples, n_channels)`` where the
    counts come from the captured ``TimeData``.  The container is
    written through :func:`pydvma.container.save` (the one save story)
    to a temp file and read back as bytes — the browser owns the "save
    to disk" step (decision #4).
    """
    dataset = acquisition.log_data(settings, test_name=test_name)
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

        test_name = msg.get('test_name') or msg.get('testName')

        loop = asyncio.get_running_loop()
        self._log_task = asyncio.ensure_future(
            loop.run_in_executor(None, _capture_to_dvma, settings, test_name)
        )
        try:
            dvma_bytes, n_samples, n_channels = await self._log_task
        except asyncio.CancelledError:
            await self._send_error('log cancelled')
            return
        finally:
            self._log_task = None

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
                        help='directory of the built UI to serve '
                             '(default: <repo>/webui/dist when it exists)')
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

    if args.ui_dir is not None:
        ui_dir = Path(args.ui_dir).expanduser().resolve()
    else:
        default = _repo_default_ui_dir()
        ui_dir = default if default.exists() else None

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
