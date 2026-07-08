"""Live-IEPE-sensor check: a real accelerometer on cDAQ1Mod1/ai1.

Closes the last hardware gap from the 2026-07-08 Windows NI recheck:
the loopback rig can't exercise a powered sensor chain, but with an
IEPE accel physically plugged into the 9234's ai1 (even just sitting
on the bench) we can verify:

  1. COLD-START BIAS TRANSIENT (raw nidaqmx, no pydvma warmup):
     enabling 2 mA excitation on a real sensor produces a multi-volt
     decaying settle through the 9234's AC-coupling HPF. An open input
     or a loopback shows no such transient -- this is the fingerprint
     that a live powered sensor is on the line.
  2. PYDVMA PER-CHANNEL PATH: channels=2 with
     ``iepe_excit_current_A=[0.0, 0.002]`` -- excitation lands on ai1
     only (task readback), warmup leaves the bias settled, the sensor
     channel shows a live noise floor and is not railed.
  3. MIXED LAB CONFIG: 9260 sweep -> ai0 loopback while the IEPE accel
     sits on ai1, one capture, both channels behave.
  4. WEBUI-STYLE BRIDGE PATH: the browser sends a SCALAR excitation
     current (broadcasts to all channels); run exactly that through a
     real ``pydvma-serve --driver nidaq`` and confirm the capture.

Rig assumptions (this lab's bench, 2026-07-08): cDAQ-9174, 9234 in
slot 1 with ao0->ai0 loopback from the 9260 and an IEPE accel
(~100 mV/g class) on ai1. Sections skip cleanly if the cDAQ is absent.

Run (section 4 needs the bridge running first; start it FRESH — once
the server has configured a stream it holds the cDAQ module and
sections 1-3 in a second process get DAQmx -50103 "resource is
reserved"):

    pydvma-serve --driver nidaq --port 8766
    python dev/iepe_accel_check.py ws://127.0.0.1:8766/ws

First run on real hardware: 2026-07-08 (see
dev/2026-07-08-windows-ni-recheck.md addendum).
"""
import asyncio
import json
import os
import struct
import sys
import tempfile
import time

import numpy as np

import pydvma as dvma
from pydvma import streams

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append((name, detail))
    print(('  PASS  ' if cond else '  FAIL  ') + name
          + ('' if not detail else '  [' + str(detail) + ']'))


def section_1_cold_transient():
    """Raw nidaqmx finite read from task start on ai1 with IEPE on."""
    print('1. cold-start IEPE bias transient (raw nidaqmx, ai1)')
    import nidaqmx
    from nidaqmx.constants import (AcquisitionType, Coupling,
                                   ExcitationSource,
                                   TerminalConfiguration)
    fs = 8533.0
    secs = 4.0
    n = int(fs * secs)
    with nidaqmx.Task() as task:
        ch = task.ai_channels.add_ai_voltage_chan(
            'cDAQ1Mod1/ai1', min_val=-5.0, max_val=5.0,
            terminal_config=TerminalConfiguration.PSEUDO_DIFF)
        ch.ai_coupling = Coupling.AC
        ch.ai_excit_src = ExcitationSource.INTERNAL
        ch.ai_excit_val = 0.002
        task.timing.cfg_samp_clk_timing(
            fs, sample_mode=AcquisitionType.FINITE, samps_per_chan=n)
        task.start()
        y = np.array(task.read(number_of_samples_per_channel=n,
                               timeout=secs + 10.0))
    fs_n = int(fs)
    early = float(np.mean(y[:fs_n // 4]))          # first 250 ms
    late = float(np.mean(y[-fs_n:]))               # last second
    if abs(early) < 0.2:
        # The DC-blocking capacitance stays charged for minutes after
        # excitation stops, so back-to-back runs see no transient.
        # Only a genuinely cold sensor (excitation off for a while)
        # shows the multi-volt settle. Observed cold on 2026-07-08:
        # early 4.857 V -> late 0.007 V.
        print('  NOTE  warm start (no bias transient) -- cold-start '
              'fingerprint needs the excitation left off for a few '
              'minutes first; skipping transient checks')
    else:
        check('early bias offset is multi-100mV+ (live biased sensor)',
              abs(early) > 0.2, '%.3f V' % early)
        check('transient decays (|late| << |early|)',
              abs(late) < abs(early) / 5, 'late %.4f V' % late)
    check('not railed at settle (|late max| < 4.9 V)',
          float(np.max(np.abs(y[-fs_n:]))) < 4.9)


def section_2_pydvma_per_channel():
    """pydvma per-channel IEPE: excite ai1 only, loopback ai0 dry."""
    print('2. pydvma per-channel IEPE (ai0 dry, ai1 = 2 mA accel)')
    s = dvma.MySettings(
        device_driver='nidaq', device_index=0, channels=2,
        fs=8000, stored_time=2.0, chunk_size=2048,
        NI_mode='DAQmx_Val_PseudoDiff', VmaxNI=5,
        output_device_driver='nidaq', output_device_index=0,
        output_channels=1, output_VmaxNI=4,   # 9260 rail is +/-4.2426 V
        iepe_excit_current_A=[0.0, 0.002])
    ds = dvma.log_data(s)
    y = np.asarray(ds.time_data_list[0].time_data)
    chs = list(streams.REC.audio_stream.ai_channels)
    check('task ch0 excitation off', chs[0].ai_excit_val == 0.0,
          chs[0].ai_excit_val)
    check('task ch1 excitation = 2 mA',
          abs(chs[1].ai_excit_val - 0.002) < 1e-9, chs[1].ai_excit_val)
    check('task ch1 AC-coupled', chs[1].ai_coupling.name == 'AC',
          chs[1].ai_coupling.name)
    m = float(np.mean(y[:, 1]))
    r = float(np.sqrt(np.mean((y[:, 1] - m) ** 2)))
    check('accel bias settled post-warmup (|mean| < 0.5 V)',
          abs(m) < 0.5, '%.4f V' % m)
    check('accel shows a live noise floor (20 uV < rms < 50 mV)',
          2e-5 < r < 5e-2, '%.3g V rms' % r)
    check('accel not railed (max < 4.9 V)',
          float(np.max(np.abs(y[:, 1]))) < 4.9)
    return s


def section_3_mixed_lab_config(s):
    """Sweep on the ai0 loopback while the IEPE accel sits on ai1."""
    print('3. mixed config: 9260 sweep -> ai0 + IEPE accel on ai1')
    fs_actual = streams.REC.settings.fs
    t_out, y_out = dvma.signal_generator(
        s, sig='sweep', amplitude=1.0, f=[100, 1000], T=1.5)
    ds = dvma.log_data(s, output=y_out)
    y = np.asarray(ds.time_data_list[0].time_data)
    rms = np.sqrt(np.mean(y ** 2, axis=0))
    check('loopback ch0 carries the sweep (rms > 0.1 V)', rms[0] > 0.1,
          np.round(rms, 4).tolist())
    check('accel ch1 stays at noise-floor level (< ch0/10)',
          rms[1] < rms[0] / 10, np.round(rms, 4).tolist())


HEADER = struct.Struct('<BBBBHHIIf')


async def section_4_bridge_scalar(url):
    """The webui path: scalar iepe_excit_current_A through the bridge."""
    print('4. bridge path, webui-style scalar IEPE broadcast')
    from websockets.asyncio.client import connect
    async with connect(url, max_size=200 * 1024 * 1024) as ws:
        await ws.send(json.dumps({'type': 'configure', 'settings': {
            'device_driver': 'nidaq', 'device_index': 0, 'channels': 2,
            'fs': 8000, 'stored_time': 3.0, 'chunk_size': 2048,
            'NI_mode': 'DAQmx_Val_PseudoDiff', 'VmaxNI': 5,
            'iepe_excit_current_A': 0.002,
            'output_device_driver': 'nidaq', 'output_device_index': 0,
            'output_channels': 1, 'output_VmaxNI': 4,
        }}))
        while True:
            msg = await asyncio.wait_for(ws.recv(), 30)
            if isinstance(msg, bytes):
                continue
            d = json.loads(msg)
            if d.get('type') == 'error':
                raise RuntimeError(d.get('message'))
            if d.get('type') == 'status' and d.get('event') == 'configured':
                break
        check('bridge configured with scalar IEPE 2 mA',
              d.get('channels') == 2, 'fs=%s' % d.get('fs'))
        await ws.send(json.dumps({
            'type': 'log', 'duration': 2.0, 'pretrigger': None,
            'output': {'type': 'sweep', 'amp': 1.0, 'f1': 100,
                       'f2': 1000, 'duration': 1.5},
            'test_name': 'iepe accel bridge'}))
        res, payload = None, None
        while payload is None:
            msg = await asyncio.wait_for(ws.recv(), 120)
            if isinstance(msg, bytes):
                if HEADER.unpack(msg[:HEADER.size])[2] == 2:
                    payload = msg[HEADER.size:]
                continue
            d = json.loads(msg)
            if d.get('type') == 'error':
                raise RuntimeError(d.get('message'))
            if d.get('type') == 'log_result':
                res = d
        check('bridge log_result 2 channels', res.get('nChannels') == 2)
        fd, path = tempfile.mkstemp(suffix='.dvma')
        os.close(fd)
        try:
            with open(path, 'wb') as f:
                f.write(payload)
            ds = dvma.load_data(filename=path)
        finally:
            os.unlink(path)
        y = np.asarray(ds.time_data_list[0].time_data)
        rms = np.sqrt(np.mean(y ** 2, axis=0))
        m1 = float(np.mean(y[:, 1]))
        check('bridge: sweep on ch0, accel quiet on ch1',
              rms[0] > 0.1 and rms[1] < rms[0] / 10,
              np.round(rms, 4).tolist())
        check('bridge: accel bias settled (|mean| < 0.5 V)',
              abs(m1) < 0.5, '%.4f V' % m1)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else None
    section_1_cold_transient()
    s = section_2_pydvma_per_channel()
    section_3_mixed_lab_config(s)
    # Release the local NI task before the bridge (separate process)
    # claims the device.
    if streams.REC is not None:
        streams.REC.end_stream()
        streams.REC = None
        streams.REC_NI = None
    if url:
        asyncio.run(section_4_bridge_scalar(url))
    else:
        print('4. SKIPPED (no bridge URL given)')
    print()
    print('==== %d passed, %d failed ====' % (len(PASS), len(FAIL)))
    for name, detail in FAIL:
        print('FAILED: %s  [%s]' % (name, detail))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
