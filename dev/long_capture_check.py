"""Headless long-recording check: one long capture through ``pydvma-serve``.

Task 11 of the iD44 acoustics round (dev/plans/2026-11-06-id44-acoustics-
plan.md). Tore's first use of the iD44 is 1-5 minute ambient recordings of
four microphones at 48 kHz: about 460 MB of float64 per capture. The spec
says such a recording must capture, compute PSD and spectrogram (STFT),
save, reload and survive a tab-close restore through the native engine,
with no data loss and no silent fallback. This script drives the same
path the web app does, hop by hop, against a MOCK serve (no audio device
is ever opened), and prints one row per step:

    step, OK/FAIL, seconds, bytes moved, peak RSS of the serve process and
    of its children (the /engine worker subprocess), what the serve process
    still holds once the step is over (macOS ``footprint``, else USS: RSS
    on macOS also counts freed pages not yet handed back), plus a note.

Steps:

  capture       /ws ``configure`` + ``log`` (default 8 ch x 150 s at
                48 kHz: the same time-data bytes as 4 ch x 300 s in half
                the wall time; the mock runs in real time). The container
                arrives as one binary frame and is loaded back here.
  pending       ``journal_get`` over /engine BEFORE any document is
                posted: the capture must be pending in the journal, byte
                for byte (the tab-close-inside-the-debounce case).
  calc_psd      the app's default PSD request (Hann, 10 frames) with the
                whole capture, as `actions.calcPsd` sends it.
  calc_sono     the app's default STFT request (nFFT 512, channel 0) with
                the whole capture, as `actions.calcSono` sends it.
  journal_set   the capture posted as the session document (the app's
                autosave).
  journal_get   the document comes back byte for byte and the pending
                capture is cleared (what a reopened tab restores).
  files_save    the document saved to the working folder (Save).
  files_read    and read back byte for byte (Load Data).

Also, in THIS process, ``save_bytes(noise)``: `pydvma.container.save_bytes`
of a noise DataSet of the same shape, quantised as a sound card delivers
it, because the mock's deterministic sines compress better than real
microphone noise; and ``deflated(noise)``, the same members all deflated as
every writer did before Task 11, for the size and time trade-off.

Exit status 0 only if every step is OK.

Run from the repo root (takes ~3-4 minutes at the default size)::

    /opt/anaconda3/bin/python dev/long_capture_check.py
    /opt/anaconda3/bin/python dev/long_capture_check.py --channels 4 --seconds 300

Port 8771 is this script's (listed with the e2e port claimants in
webui/e2e/engine-native.spec.ts). The spawned serve, and any /engine
worker it started, are killed on exit by PID.
"""
import argparse
import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
import psutil
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from pydvma import container, datastructure, engine_host, options
from pydvma import serve as serve_mod

MB = 1e6


class RssSampler(threading.Thread):
    """Samples the serve process's RSS (and its children's) at ~20 Hz.

    `reset` starts a new step's peak; `peak` reads it. Every child PID
    ever seen is remembered so the harness can kill an orphaned /engine
    worker by PID at the end.
    """

    def __init__(self, pid):
        super().__init__(daemon=True)
        self.proc = psutil.Process(pid)
        self.children_seen = set()
        self._lock = threading.Lock()
        self._peak_main = 0
        self._peak_children = 0
        self._stop = threading.Event()

    def sample(self):
        """Take one sample now; False once the process is gone."""
        try:
            main = self.proc.memory_info().rss
            kids = 0
            for c in self.proc.children(recursive=True):
                self.children_seen.add(c.pid)
                try:
                    kids += c.memory_info().rss
                except psutil.Error:
                    pass
        except psutil.Error:
            return False
        with self._lock:
            self._peak_main = max(self._peak_main, main)
            self._peak_children = max(self._peak_children, kids)
        return True

    def run(self):
        while not self._stop.is_set() and self.sample():
            time.sleep(0.05)

    def reset(self):
        with self._lock:
            self._peak_main = 0
            self._peak_children = 0
        self.sample()

    def peak(self):
        self.sample()
        with self._lock:
            return self._peak_main, self._peak_children

    def stop(self):
        self._stop.set()


ROWS = []
SERVE_PID = None


def held_bytes(pid):
    """What the serve process holds right now, or None.

    macOS's ``footprint`` (the memory the system charges the process, as
    Activity Monitor shows it): RSS there also counts pages malloc has
    freed but not yet handed back, so it overstates what is held. Falls
    back to psutil's USS elsewhere.
    """
    if pid is None:
        return None
    if sys.platform == 'darwin' and shutil.which('footprint'):
        out = subprocess.run(['footprint', str(pid)], capture_output=True,
                             text=True).stdout
        for line in out.splitlines():
            if 'Footprint:' in line:
                num, unit = line.split('Footprint:', 1)[1].split()[:2]
                scale = {'KB': 1e3, 'MB': 1e6, 'GB': 1e9}.get(unit, 1.0)
                return float(num) * scale
    try:
        return psutil.Process(pid).memory_full_info().uss
    except (psutil.Error, AttributeError):
        return None


def record(step, ok, seconds, nbytes, rss, note=''):
    """One table row, printed as it lands."""
    main, kids = rss
    held = held_bytes(SERVE_PID) if (main or kids) else None
    ROWS.append((step, ok, seconds, nbytes, main, kids, held, note))
    print('%-18s %-4s %8.1f s %10.1f MB  serve %7.0f MB  worker %7.0f MB  '
          'held %s  %s'
          % (step, 'OK' if ok else 'FAIL', seconds, nbytes / MB, main / MB,
             kids / MB, '-' if held is None else '%.0f MB' % (held / MB),
             note), flush=True)


def wait_for_port(port, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
        time.sleep(0.2)
    return False


async def recv_json(ws, want, timeout):
    """Next text frame of type ``want``; warnings are printed, binary skipped."""
    deadline = time.monotonic() + timeout
    while True:
        raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
        if isinstance(raw, (bytes, bytearray)):
            continue
        msg = json.loads(raw)
        if msg.get('type') == 'warning':
            print('    [warning] %s' % msg.get('message'), flush=True)
            continue
        if msg.get('type') == 'error':
            raise RuntimeError('server error: %s' % msg.get('message'))
        if msg.get('type') == want:
            return msg


async def recv_binary(ws, timeout):
    deadline = time.monotonic() + timeout
    while True:
        raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
        if isinstance(raw, (bytes, bytearray)):
            return raw
        msg = json.loads(raw)
        if msg.get('type') == 'error':
            raise RuntimeError('server error: %s' % msg.get('message'))


class Engine:
    """One /engine connection, reopened after the server closes it."""

    def __init__(self, port):
        self.url = 'ws://127.0.0.1:%d/engine' % port
        self.origin = 'http://127.0.0.1:%d' % port
        self.ws = None
        self.rid = 0
        self.greeting = None

    async def open(self):
        if self.ws is not None:
            return
        self.ws = await connect(self.url, max_size=None, origin=self.origin,
                                ping_interval=None, open_timeout=30)
        self.greeting = json.loads(await asyncio.wait_for(self.ws.recv(), 30))

    async def call(self, op, payload, timeout=900.0):
        """Send one op; returns ``(ok, result_or_error, sent, received)``.

        A server-side close (e.g. 1009 message too big) is reported as a
        failed call naming the close code, and the next call reconnects.
        """
        await self.open()
        self.rid += 1
        frame = engine_host.encode_frame({'id': self.rid, 'op': op,
                                          'payload': payload})
        sent = len(frame)
        try:
            await self.ws.send(frame)
            deadline = time.monotonic() + timeout
            while True:
                raw = await asyncio.wait_for(self.ws.recv(),
                                             deadline - time.monotonic())
                if not isinstance(raw, (bytes, bytearray)):
                    continue                # progress / journal notices
                reply = await asyncio.to_thread(engine_host.decode_frame, raw)
                if reply.get('id') != self.rid:
                    continue
                if reply.get('ok'):
                    return True, reply.get('result'), sent, len(raw)
                return False, reply.get('error'), sent, len(raw)
        except ConnectionClosed as e:
            self.ws = None
            rcvd = e.rcvd
            code = rcvd.code if rcvd is not None else None
            reason = rcvd.reason if rcvd is not None else ''
            return False, 'connection closed (code %s %s)' % (code, reason), sent, 0

    async def close(self):
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None


def noise_container_rows(n_samples, n_channels, fs):
    """`container.save_bytes` on microphone-like noise of the capture's shape.

    The noise is Gaussian quantised the way a sound card delivers it
    (float32 samples widened to float64, so the low mantissa bits are
    zero), which compresses better than full-precision noise and worse
    than the mock's sines. Returns two rows: the writer as it is, and the
    same members all deflated (what every writer did before Task 11), for
    the size and time trade-off.
    """
    import zipfile
    rng = np.random.default_rng(0)
    data = (0.01 * rng.standard_normal((n_samples, n_channels))
            ).astype(np.float32).astype(np.float64)
    axis = np.arange(n_samples) / fs
    settings = options.MySettings(channels=n_channels, fs=fs,
                                  device_driver='mock')
    td = datastructure.TimeData(axis, data, settings)
    ds = datastructure.DataSet()
    ds.add_to_dataset(td)
    raw = data.nbytes + axis.nbytes
    rows = []
    t0 = time.monotonic()
    blob = container.save_bytes(ds)
    t_save = time.monotonic() - t0
    t0 = time.monotonic()
    back = container.load_bytes(blob)
    t_load = time.monotonic() - t0
    ok = np.array_equal(back.time_data_list[0].time_data, data)
    rows.append(('save_bytes(noise)', ok, t_save, len(blob),
                 'load %.1f s; %.0f %% of the raw %.0f MB (harness process)'
                 % (t_load, 100 * len(blob) / raw, raw / MB)))
    del blob, back
    manifest, arrays = container.dataset_manifest(ds)
    t0 = time.monotonic()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for member, arr in arrays.items():
            one = io.BytesIO()
            np.save(one, arr, allow_pickle=False)
            zf.writestr(member, one.getvalue())
        zf.writestr('manifest.json', json.dumps(manifest))
    deflated = len(buf.getvalue())
    rows.append(('deflated(noise)', True, time.monotonic() - t0, deflated,
                 'all members deflated, as before Task 11; %.0f %% of raw '
                 '(harness process, for comparison)' % (100 * deflated / raw)))
    return rows


async def run(args, sampler, port, tmp):
    n_ch, fs, secs = args.channels, args.fs, args.seconds
    n_expect = int(round(secs * fs))

    # ---- capture over /ws --------------------------------------------------
    sampler.reset()
    t0 = time.monotonic()
    dvma = None
    note = ''
    try:
        async with connect('ws://127.0.0.1:%d/ws' % port, max_size=None,
                           ping_interval=None, open_timeout=30) as ws:
            # No `hello`: the capabilities reply enumerates the real
            # sound cards, and this harness touches none of them.
            await ws.send(json.dumps({'type': 'configure', 'settings': {
                'device_driver': 'mock', 'channels': n_ch, 'fs': fs,
                'stored_time': secs, 'chunk_size': 1000, 'num_chunks': 4,
                'viewed_time': None}}))
            await recv_json(ws, 'status', 60)
            await ws.send(json.dumps({'type': 'log', 'duration': secs,
                                      'pretrigger': None,
                                      'test_name': 'long-capture'}))
            meta = await recv_json(ws, 'log_result', secs + 900)
            frame = await recv_binary(ws, 900)
            hdr = serve_mod.decode_header(frame)
            dvma = bytes(frame[serve_mod.HEADER_SIZE:])
            ok = (hdr['msgType'] == serve_mod.MSG_CONTAINER
                  and meta['nSamples'] == n_expect
                  and meta['nChannels'] == n_ch)
            note = '%d x %d samples' % (meta['nSamples'], meta['nChannels'])
    except Exception as e:
        ok, note = False, '%s: %s' % (type(e).__name__, e)
    elapsed = time.monotonic() - t0
    record('capture', ok, elapsed, len(dvma) if dvma else 0, sampler.peak(),
           note)
    if dvma is None:
        return

    # The container loads back here, with the expected shape.
    t0 = time.monotonic()
    ds = await asyncio.to_thread(container.load_bytes, dvma)
    td = ds.time_data_list[0]
    shape_ok = td.time_data.shape == (n_expect, n_ch)
    record('load (harness)', shape_ok, time.monotonic() - t0, len(dvma),
           (0, 0), 'container loads, shape %s' % (td.time_data.shape,))
    axis = np.ascontiguousarray(td.time_axis, dtype='<f8')
    flat = np.ascontiguousarray(td.time_data, dtype='<f8').ravel()
    del ds, td

    eng = Engine(port)

    # ---- the capture is pending in the journal -----------------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('journal_get', {})
    if ok:
        caps = res.get('captures') or []
        good = len(caps) == 1 and bytes(caps[0]) == dvma
        note = '%d pending capture(s)%s' % (
            len(caps), '' if good else ' -- the capture is NOT pending')
        ok = good
    else:
        note = str(res)
    record('pending', ok, time.monotonic() - t0, rcvd, sampler.peak(), note)

    # ---- calc_psd (the app's defaults) -------------------------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('calc_psd', {
        'time_axis': axis, 'time_data': flat, 'n_channels': n_ch, 'fs': fs,
        'window': 'hann', 'n_frames': 10})
    note = ('psd shape %s' % (res['psd']['shape'],)) if ok else str(res)
    record('calc_psd', ok, time.monotonic() - t0, sent + rcvd, sampler.peak(),
           note + '; sent %.0f MB, got %.0f MB' % (sent / MB, rcvd / MB))

    # ---- calc_sono (STFT, one channel) -------------------------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('calc_sono', {
        'time_axis': axis, 'time_data': flat, 'n_channels': n_ch, 'fs': fs,
        'ch': 0, 'nperseg': 512, 'noverlap': 256, 'method': 'stft',
        'voices_per_octave': 16, 'w0': 6})
    note = ('image %s' % (res['sono_data']['shape'],)) if ok else str(res)
    record('calc_sono', ok, time.monotonic() - t0, sent + rcvd,
           sampler.peak(),
           note + '; sent %.0f MB, got %.0f MB' % (sent / MB, rcvd / MB))
    del axis, flat

    # ---- journal_set: the capture as the session document ------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('journal_set', {'doc': dvma})
    record('journal_set', ok, time.monotonic() - t0, sent, sampler.peak(),
           '' if ok else str(res))

    # ---- journal_get: what a reopened tab restores -------------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('journal_get', {})
    if ok:
        doc = res.get('doc')
        caps = res.get('captures') or []
        same = doc is not None and bytes(doc) == dvma
        ok = same and not caps
        note = ('document %s, %d pending' % ('identical' if same else 'DIFFERS',
                                             len(caps)))
    else:
        note = str(res)
    record('journal_get', ok, time.monotonic() - t0, rcvd, sampler.peak(), note)

    # ---- files_save + files_read (Save, Load Data) -------------------------
    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('files_save', {
        'name': 'long-capture.dvma', 'data': dvma, 'overwrite': True})
    on_disk = os.path.join(tmp, 'long-capture.dvma')
    if ok:
        ok = bool(res.get('saved')) and os.path.getsize(on_disk) == len(dvma)
        note = 'saved, %d bytes on disk' % os.path.getsize(on_disk)
    else:
        note = str(res)
    record('files_save', ok, time.monotonic() - t0, sent, sampler.peak(), note)

    sampler.reset()
    t0 = time.monotonic()
    ok, res, sent, rcvd = await eng.call('files_read',
                                         {'path': 'long-capture.dvma'})
    if ok:
        ok = bytes(res.get('data') or b'') == dvma
        note = 'identical' if ok else 'bytes DIFFER'
    else:
        note = str(res)
    record('files_read', ok, time.monotonic() - t0, rcvd, sampler.peak(), note)

    await eng.close()

    # ---- in this process: how real noise compresses ------------------------
    if not args.skip_noise:
        rows = await asyncio.to_thread(noise_container_rows, n_expect, n_ch, fs)
        for step, ok, secs_save, nbytes, note in rows:
            record(step, ok, secs_save, nbytes, (0, 0), note)


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--port', type=int, default=8771)
    p.add_argument('--channels', type=int, default=8)
    p.add_argument('--seconds', type=float, default=150.0)
    p.add_argument('--fs', type=float, default=48000.0)
    p.add_argument('--skip-noise', action='store_true',
                   help='skip the in-process noise save_bytes row')
    args = p.parse_args()

    tmp = tempfile.mkdtemp(prefix='pydvma-long-')
    log_path = os.path.join(tmp, 'serve.log')
    print('long capture: %d ch x %g s at %g Hz (%.0f MB of float64 time data)'
          % (args.channels, args.seconds, args.fs,
             args.channels * args.seconds * args.fs * 8 / MB), flush=True)
    print('serve log: %s' % log_path, flush=True)
    with open(log_path, 'w') as log:
        proc = subprocess.Popen(
            [sys.executable, '-m', 'pydvma.serve', '--driver', 'mock',
             '--port', str(args.port), '--session-dir', tmp,
             '--save-dir', tmp],
            stdout=log, stderr=subprocess.STDOUT)
    sampler = None
    try:
        if not wait_for_port(args.port):
            print('serve did not start on port %d' % args.port)
            return 1
        global SERVE_PID
        SERVE_PID = proc.pid
        sampler = RssSampler(proc.pid)
        sampler.start()
        asyncio.run(run(args, sampler, args.port, tmp))
    finally:
        children = set(sampler.children_seen) if sampler else set()
        if sampler is not None:
            sampler.stop()
        try:
            for c in psutil.Process(proc.pid).children(recursive=True):
                children.add(c.pid)
        except psutil.Error:
            pass
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)
        for pid in children:                  # an orphaned /engine worker
            try:
                psutil.Process(pid).kill()
            except psutil.Error:
                pass
        with open(log_path) as f:
            tail = f.read()[-3000:]
        if tail.strip():
            print('--- serve log tail ---\n' + tail)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('| step | result | s | MB | serve peak RSS MB | worker peak RSS MB '
          '| serve held after MB | note |')
    print('|---|---|---:|---:|---:|---:|---:|---|')
    for step, ok, s, nb, main, kids, held, note in ROWS:
        print('| %s | %s | %.1f | %.0f | %.0f | %.0f | %s | %s |'
              % (step, 'OK' if ok else 'FAIL', s, nb / MB, main / MB,
                 kids / MB, '' if held is None else '%.0f' % (held / MB),
                 note))
    failed = [r[0] for r in ROWS if not r[1]]
    expected = 9 + (0 if args.skip_noise else 2)
    if failed or len(ROWS) < expected:
        print('\nFAIL: %s' % (', '.join(failed) or 'steps missing'))
        return 1
    print('\nall %d steps OK' % len(ROWS))
    return 0


if __name__ == '__main__':
    sys.exit(main())
