"""Headless bridge-level NI hardware recheck (round-7 handoff item).

Drives a real ``pydvma-serve --driver nidaq`` process over its WebSocket
protocol and verifies, against the physically connected devices:

  A. capabilities handshake — 3 NI devices, cDAQ merged module caps
     (9260 ao_vmax rail 4.2426 -> the UI's "clamped to +/-4.24 V" note,
     9234 IEPE / simultaneous / PseudoDiff).
  B. DSA coerced-fs — configure the cDAQ at 8000 Hz, expect the
     `configured` status to report 8533.33 Hz (the round-D note text).
  C. MULTI-CHANNEL capture through the bridge — 4-ch 9234 log with a
     sweep on the 9260 (ao0->ai0 loopback): container has 4 channels,
     the loopback channel carries the sweep, open channels are quiet.
  D. pretrigger + output sweep via the bridge on EVERY device —
     armed -> triggered -> log_result, 2-channel, container sane.

Run (two shells, on the machine with the NI devices + loopbacks):

    pydvma-serve --driver nidaq --port 8766
    python dev/bridge_hw_check.py ws://127.0.0.1:8766/ws

First run on real hardware: 2026-07-08, 38/38 pass (cDAQ-9174 with
9234+9260, USB-6212, USB-6003; ao0->ai0 loopback on each device).
"""
import asyncio
import io
import json
import struct
import sys
import tempfile
import os

import numpy as np
from websockets.asyncio.client import connect

import pydvma

HEADER = struct.Struct('<BBBBHHIIf')

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append((name, detail))
    print(('  PASS  ' if cond else '  FAIL  ') + name + ('' if not detail else '  [' + str(detail) + ']'))


async def recv_json(ws, want_type=None, timeout=30):
    """Next text frame (as dict), skipping binary frames."""
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout)
        if isinstance(msg, bytes):
            continue
        d = json.loads(msg)
        if want_type is None or d.get('type') == want_type:
            return d
        if d.get('type') == 'error':
            raise RuntimeError('bridge error: %s' % d.get('message'))


async def recv_container(ws, timeout=60):
    """Next binary container frame -> (header fields, payload bytes)."""
    while True:
        msg = await asyncio.wait_for(ws.recv(), timeout)
        if not isinstance(msg, bytes):
            d = json.loads(msg)
            if d.get('type') == 'error':
                raise RuntimeError('bridge error: %s' % d.get('message'))
            continue
        magic, ver, msg_type, dtype, stream_id, n_ch, seq, n_samp, fs = \
            HEADER.unpack(msg[:HEADER.size])
        if msg_type == 2:
            return dict(nChannels=n_ch, nSamples=n_samp, fs=fs), msg[HEADER.size:]


def parse_dvma(payload):
    """Parse .dvma zip bytes -> pydvma DataSet."""
    fd, path = tempfile.mkstemp(suffix='.dvma')
    os.close(fd)
    try:
        with open(path, 'wb') as f:
            f.write(payload)
        return pydvma.load_data(filename=path)
    finally:
        os.unlink(path)


async def do_log(ws, duration, pretrigger=None, output=None, test_name='hw check'):
    """Send log, collect status events until log_result, then the container.

    Returns (events, log_result, header, dataset).
    """
    req = {'type': 'log', 'duration': duration, 'pretrigger': pretrigger,
           'test_name': test_name}
    if output is not None:
        req['output'] = output
    await ws.send(json.dumps(req))
    events = []
    result = None
    while result is None:
        msg = await asyncio.wait_for(ws.recv(), 120)
        if isinstance(msg, bytes):
            continue
        d = json.loads(msg)
        if d.get('type') == 'error':
            raise RuntimeError('bridge error: %s' % d.get('message'))
        if d.get('type') == 'status' and d.get('event'):
            events.append(d['event'])
        if d.get('type') == 'log_result':
            result = d
    hdr, payload = await recv_container(ws)
    return events, result, hdr, parse_dvma(payload)


async def main(url):
    async with connect(url, max_size=200 * 1024 * 1024) as ws:
        # ---- A. capabilities ----
        print('A. capabilities handshake')
        await ws.send(json.dumps({'type': 'hello'}))
        caps = await recv_json(ws, 'capabilities')
        check('nidaq backend advertised', 'nidaq' in caps['backends'])
        ndev = len(caps['devices']['nidaq'])
        check('3 NI devices enumerated', ndev == 3, ndev)
        c0 = caps['device_caps'].get('nidaq:0', {})
        check('cDAQ ao_vmax = 9260 rail 4.2426 (drives the +/-4.24 V clamp note)',
              c0.get('ao_vmax') is not None and abs(c0['ao_vmax'] - 4.24264068712) < 1e-6,
              c0.get('ao_vmax'))
        check('cDAQ ai_vmax = 9234 rail 5.0', c0.get('ai_vmax') == 5.0, c0.get('ai_vmax'))
        check('cDAQ IEPE supported, 2 mA',
              c0.get('iepe_supported') is True and c0.get('iepe_currents') == [0.002],
              c0.get('iepe_currents'))
        check('cDAQ simultaneous (DSA)', c0.get('simultaneous') is True)
        check('cDAQ terminal = PseudoDiff',
              c0.get('terminal_configs') == ['DAQmx_Val_PseudoDiff'],
              c0.get('terminal_configs'))
        mc0 = caps['max_channels'].get('nidaq:0', {})
        check('cDAQ max_channels 4 in / 2 out',
              mc0 == {'input': 4, 'output': 2}, mc0)

        # ---- B. DSA coerced-fs on the real 9234 ----
        print('B. DSA coerced-fs (request 8000 -> expect 8533.33)')
        await ws.send(json.dumps({'type': 'configure', 'settings': {
            'device_driver': 'nidaq', 'device_index': 0, 'channels': 4,
            'fs': 8000, 'stored_time': 3.0,
            'NI_mode': 'DAQmx_Val_PseudoDiff', 'VmaxNI': 5,
            'output_device_driver': 'nidaq', 'output_device_index': 0,
            'output_channels': 1, 'output_VmaxNI': 4,
        }}))
        st = await recv_json(ws, 'status')
        check('configured event received', st.get('event') == 'configured', st.get('event'))
        check('fs coerced to 8533.33 on real 9234',
              abs(st.get('fs', 0) - 25600.0 / 3.0) < 0.1, st.get('fs'))
        check('4 channels configured', st.get('channels') == 4, st.get('channels'))

        # ---- C. multi-channel capture w/ sweep (cDAQ, loopback ao0->ai0) ----
        print('C. 4-channel bridge capture, 9260 sweep -> 9234 ai0')
        events, res, hdr, data = await do_log(
            ws, 2.0, pretrigger=None,
            output={'type': 'sweep', 'amp': 1.0, 'f1': 100, 'f2': 1000,
                    'duration': 1.5},
            test_name='multi-ch sweep cDAQ')
        check('log_result nChannels = 4', res.get('nChannels') == 4, res.get('nChannels'))
        check('log_result fs = coerced 8533.33',
              abs(res.get('fs', 0) - 25600.0 / 3.0) < 0.1, res.get('fs'))
        td = data.time_data_list[0]
        y = np.asarray(td.time_data)
        check('container TimeData shape (N, 4)', y.ndim == 2 and y.shape[1] == 4, y.shape)
        rms = np.sqrt(np.mean(y ** 2, axis=0))
        check('loopback ch0 carries the sweep (rms > 0.1 V)', rms[0] > 0.1,
              np.round(rms, 4).tolist())
        check('open 9234 channels quiet (< ch0/5)',
              all(r < rms[0] / 5 for r in rms[1:]), np.round(rms, 4).tolist())
        peak = float(np.max(np.abs(y[:, 0])))
        check('ch0 peak ~ commanded 1.0 V (0.8..1.2)', 0.8 < peak < 1.2, round(peak, 3))

        # ---- D. pretrigger + sweep on every device via the bridge ----
        dev_cfgs = [
            (0, 'cDAQ-9174 (9234/9260)', dict(NI_mode='DAQmx_Val_PseudoDiff',
                                              VmaxNI=5, output_VmaxNI=4), 8000),
            (1, 'USB-6212', dict(NI_mode='DAQmx_Val_RSE',
                                 VmaxNI=10, output_VmaxNI=5), 10000),
            # 6003 AO caps at 5000 S/s (software-timed): output_fs must
            # be set explicitly since MySettings defaults it to fs.
            # NB the webui now does this too (acquire store
            # reclampOutputFs stages output_fs = device_caps
            # ao_max_rate when the input fs exceeds it).
            (2, 'USB-6003', dict(NI_mode='DAQmx_Val_RSE',
                                 VmaxNI=10, output_VmaxNI=5,
                                 output_fs=5000), 8000),
        ]
        for idx, label, cfg, fs in dev_cfgs:
            print('D. pretrigger + sweep via bridge: ' + label)
            await ws.send(json.dumps({'type': 'configure', 'settings': dict(
                device_driver='nidaq', device_index=idx, channels=2,
                fs=fs, stored_time=3.0, chunk_size=2048,
                output_device_driver='nidaq', output_device_index=idx,
                output_channels=1, **cfg)}))
            st = await recv_json(ws, 'status')
            check(label + ': configured', st.get('event') == 'configured',
                  'fs=%s' % st.get('fs'))
            fs_actual = float(st.get('fs'))
            # pydvma constraint: pretrig_samples <= chunk_size (the
            # pretrigger buffer keeps one chunk of pre-trigger context).
            pre = 1024
            events, res, hdr, data = await do_log(
                ws, 2.0, pretrigger={'samples': pre},
                output={'type': 'sweep', 'amp': 1.0, 'f1': 100, 'f2': 1000,
                        'duration': 1.5},
                test_name='pretrig sweep ' + label)
            check(label + ': armed event', 'armed' in events, events)
            check(label + ': 2 channels captured', res.get('nChannels') == 2,
                  res.get('nChannels'))
            y = np.asarray(data.time_data_list[0].time_data)
            n = y.shape[0]
            check(label + ': duration ~2 s of samples',
                  abs(n - 2.0 * fs_actual) < 0.05 * fs_actual,
                  '%d samples @ %.1f Hz' % (n, fs_actual))
            # Signal onset should sit near the pretrigger point: the
            # stretch well before it is quiet, the stretch after is live.
            # This is the AUTHORITATIVE trigger evidence.  The
            # `triggered` status event is best-effort by design (a
            # ~10 Hz poll of the recorder's trigger_detected flag; a
            # fast trigger can be reset by log_data before a poll sees
            # it, in which case the connection reports `timeout` even
            # though the capture triggered — see the serve.py protocol
            # docstring).  So the event is advisory: note a miss, but
            # only the data-onset check decides pass/fail.
            k = np.argmax(np.abs(y[:, 0]) > 0.2)
            check(label + ': onset near pretrigger point (%d)' % pre,
                  abs(int(k) - pre) < 0.1 * fs_actual, 'onset@%d' % int(k))
            if 'triggered' not in events:
                print('  NOTE  %s: triggered status event missed by the '
                      'best-effort poll (events %s) -- capture itself '
                      'triggered, see onset check' % (label, events))

    print()
    print('==== %d passed, %d failed ====' % (len(PASS), len(FAIL)))
    for name, detail in FAIL:
        print('FAILED: %s  [%s]' % (name, detail))
    return 1 if FAIL else 0


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'ws://127.0.0.1:8766/ws'
    sys.exit(asyncio.run(main(url)))
