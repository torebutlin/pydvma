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
  E. digital low-pass (lpf_on) log on every device.
  F. BLA (Schoukens multisine) through the bridge — M x P seeded
     multisine captures via `log` with a `multisine` output spec, then
     `analysis.calculate_bla` on the returned containers. Measured-x
     SISO on the ao0->ai0 loopback: G on the x channel itself must be
     EXACTLY 1 (pipeline/order/period-slicing proof), the second
     channel rides along at the noise floor. Run at a native rate per
     device, plus a DSA-coerced rate on the cDAQ (the multisine spec
     is defined in SAMPLES, so coercion must not disturb it).
  G. commanded-x re-solve of the SAME captures (x analytic from seed)
     — a MEASUREMENT, not a pass/fail check. First run (2026-08-11)
     found |G| collapsed by ~1/sqrt(M) with sigma_NL ~ 2.4|G| on BOTH
     the routed-clock 6212 AND the cDAQ: the routed AI sample clock
     locks the RATE but each capture is a window of the free-running
     AI stream, so the AO start offset is random per capture. That
     measurement closed the webui's commanded-x gate everywhere
     (BLA_COMMANDED_X_START_SYNC_PROVEN in stores/bla.ts); these
     NOTEs are the data to re-check when start-trigger work lands.
  H. AO sample-clock coercion pins (direct nidaqmx, no bridge): the
     9260 coerces onto the SAME 51200/n ladder as the 9234 (so a BLA
     run at the AI-coerced rate keeps output_fs == fs exactly), and
     the 6212 is exact at round rates.

Discovery-driven: checks run against whatever NI devices are physically
connected (per-model configs for the cDAQ chassis, USB-6212 and
USB-6003; unknown models are noted and skipped), so pass/fail counts
vary with the bench. ao0->ai0 BNC loopback expected on each device.

Run (two shells, on the machine with the NI devices + loopbacks):

    pydvma-serve --driver nidaq --port 8766
    python dev/bridge_hw_check.py ws://127.0.0.1:8766/ws

First run on real hardware: 2026-07-08, 38/38 pass (cDAQ-9174 with
9234+9260, USB-6212, USB-6003). 2026-07-10: 44/44 (check E added).
2026-08-11: 35/35 with the 6003 unplugged (discovery-driven rewrite);
later that day 58/58 with checks F/G/H added (cDAQ + 6212 live), the
run that produced the commanded-x start-offset finding above.
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
        entries = caps['devices']['nidaq']
        products = [e.get('product_type', '?') for e in entries]
        print('  enumerated: ' + ', '.join(
            '%d=%s' % (i, p) for i, p in enumerate(products)))
        check('at least one NI device enumerated', len(entries) >= 1, products)
        cdaq_idx = next((i for i, e in enumerate(entries)
                         if e.get('is_chassis')), None)
        if cdaq_idx is None:
            print('  SKIP  cDAQ caps checks (no chassis connected)')
        else:
            c0 = caps['device_caps'].get('nidaq:%d' % cdaq_idx, {})
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
            mc0 = caps['max_channels'].get('nidaq:%d' % cdaq_idx, {})
            check('cDAQ max_channels 4 in / 2 out',
                  mc0 == {'input': 4, 'output': 2}, mc0)

        if cdaq_idx is not None:
            # ---- B. DSA coerced-fs on the real 9234 ----
            print('B. DSA coerced-fs (request 8000 -> expect 8533.33)')
            await ws.send(json.dumps({'type': 'configure', 'settings': {
                'device_driver': 'nidaq', 'device_index': cdaq_idx, 'channels': 4,
                'fs': 8000, 'stored_time': 3.0,
                'NI_mode': 'DAQmx_Val_PseudoDiff', 'VmaxNI': 5,
                'output_device_driver': 'nidaq', 'output_device_index': cdaq_idx,
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
        else:
            print('B./C. SKIP (no cDAQ chassis connected)')

        # ---- D. pretrigger + sweep on every connected device ----
        # Per-model config; dev_cfgs is built from the enumerated devices
        # so the harness runs against whatever is physically plugged in.
        KNOWN_CFGS = {
            'cDAQ': (dict(NI_mode='DAQmx_Val_PseudoDiff',
                          VmaxNI=5, output_VmaxNI=4), 8000),
            'USB-6212': (dict(NI_mode='DAQmx_Val_RSE',
                              VmaxNI=10, output_VmaxNI=5), 10000),
            # 6003 AO caps at 5000 S/s (software-timed): output_fs must
            # be set explicitly since MySettings defaults it to fs.
            # NB the webui now does this too (acquire store
            # reclampOutputFs stages output_fs = device_caps
            # ao_max_rate when the input fs exceeds it).
            'USB-6003': (dict(NI_mode='DAQmx_Val_RSE',
                              VmaxNI=10, output_VmaxNI=5,
                              output_fs=5000), 8000),
        }
        dev_cfgs = []
        for i, e in enumerate(entries):
            prod = e.get('product_type', '?')
            key = 'cDAQ' if e.get('is_chassis') else prod
            if key in KNOWN_CFGS:
                cfg, fs = KNOWN_CFGS[key]
                dev_cfgs.append((i, prod, dict(cfg), fs))
            else:
                print('  NOTE  no per-model config for %s (index %d) '
                      '-- skipping D/E on it' % (prod, i))
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

        # ---- E. digital low-pass (round-9): lpf_on log on every device ----
        # The server should oversample at the device's ai_max_rate and
        # resample down to the requested fs (analysis.resample_to_fs). The
        # logged settings must carry fs == target and the capture rate in
        # lpf_capture_fs. Target fs low enough that every device has >= 2x
        # headroom (6003: 100k max / 2k = 50x; 9234 ladder still >= 2x).
        for idx, label, cfg, _fs in dev_cfgs:
            print('E. digital low-pass log: ' + label)
            cfg_lpf = {k: v for k, v in cfg.items() if k != 'output_fs'}
            await ws.send(json.dumps({'type': 'configure', 'settings': dict(
                device_driver='nidaq', device_index=idx, channels=2,
                fs=2000, stored_time=2.0, lpf_on=True, **cfg_lpf)}))
            st = await recv_json(ws, 'status')
            check(label + ' lpf: configured', st.get('event') == 'configured',
                  'fs=%s' % st.get('fs'))
            events, res, hdr, data = await do_log(
                ws, 2.0, pretrigger=None, test_name='lpf log ' + label)
            td = data.time_data_list[0]
            fs_out = float(td.settings.fs)
            check(label + ' lpf: TimeData at ~target fs 2000',
                  abs(fs_out - 2000.0) < 0.05 * 2000.0, fs_out)
            cap = getattr(td.settings, 'lpf_capture_fs', None)
            check(label + ' lpf: capture rate recorded and >= 2x target',
                  cap is not None and cap >= 2 * 2000.0, cap)
            y = np.asarray(td.time_data)
            check(label + ' lpf: ~2 s of samples at the target rate',
                  abs(y.shape[0] - 2.0 * fs_out) < 0.05 * 2.0 * fs_out,
                  y.shape)

        # ---- F./G. BLA through the bridge + commanded-x re-solve ----
        # Multisine spec is in SAMPLES (N, k1, k2), so the same spec is
        # valid at any rate — including a DSA-coerced one. amp maps to
        # amp_rms server-side; equal-A lines, so per-line amplitude is
        # amp * sqrt(2 / n_lines) and the crest guard runs server-side
        # against the configured output rail.
        BLA_N, BLA_K1, BLA_K2 = 4096, 6, 400
        BLA_M, BLA_P, BLA_T = 4, 3, 2
        BLA_AMP = 0.5
        BLA_SEED = 20260811
        # Per-model BLA rates: first entry native/exact, extras exercise
        # coercion. 6003: AO tops out at 5 kS/s, so fs must sit at or
        # under that for output_fs == fs (untested — no 6003 on the
        # bench when this was written).
        BLA_FS = {'cDAQ': [25600, 8000], 'USB-6212': [10000],
                  'USB-6003': [4000]}

        async def bla_captures(fs_actual):
            spec_wire = {'type': 'multisine', 'n_samples': BLA_N,
                         'k1': BLA_K1, 'k2': BLA_K2, 'p_periods': BLA_P,
                         't_periods': BLA_T, 'seed': BLA_SEED,
                         'n_exc': 1, 'amp': BLA_AMP}
            duration = (BLA_T + BLA_P) * BLA_N / fs_actual + 0.3
            caps_list = []
            for m in range(BLA_M):
                _ev, _res, _hdr, data = await do_log(
                    ws, duration, output=dict(spec_wire, m=m, e=0),
                    test_name='bla m%d' % m)
                caps_list.append(data.time_data_list[0])
            return caps_list

        def bla_spec(fs_actual):
            return {'n_samples': BLA_N, 'k1': BLA_K1, 'k2': BLA_K2,
                    'p_periods': BLA_P, 't_periods': BLA_T,
                    'seed': BLA_SEED, 'amp_rms': BLA_AMP,
                    'n_exc': 1, 'M': BLA_M}

        for idx, label, cfg, _fs in dev_cfgs:
            key = 'cDAQ' if 'cDAQ' in label or '9174' in label else label
            for run_i, fs_req in enumerate(BLA_FS.get(key, [])):
                tag = '%s @%g' % (label, fs_req)
                print('F. BLA via bridge: ' + tag)
                cfg_bla = {k: v for k, v in cfg.items() if k != 'output_fs'}
                await ws.send(json.dumps({'type': 'configure', 'settings': dict(
                    device_driver='nidaq', device_index=idx, channels=2,
                    fs=fs_req, stored_time=3.0, chunk_size=2048,
                    output_device_driver='nidaq', output_device_index=idx,
                    output_channels=1, **cfg_bla)}))
                st = await recv_json(ws, 'status')
                fs_actual = float(st.get('fs'))
                coerced = abs(fs_actual - fs_req) > 1e-6
                check(tag + ': configured (fs=%g%s)'
                      % (fs_actual, ', coerced' if coerced else ''),
                      st.get('event') == 'configured', st.get('fs'))
                # BLA precondition: output_fs == fs. Reconfigure with the
                # REQUESTED rate on both sides — a fractional actual rate
                # cannot be sent back over the wire (the settings
                # whitelist int-coerces fs), and it does not need to be:
                # check H proves the 9260 coerces onto the SAME 51200/n
                # ladder as the 9234, so requesting fs_req on both sides
                # lands AI and AO on one physical rate.
                await ws.send(json.dumps({'type': 'configure', 'settings': dict(
                    device_driver='nidaq', device_index=idx, channels=2,
                    fs=fs_req, stored_time=3.0, chunk_size=2048,
                    output_device_driver='nidaq', output_device_index=idx,
                    output_channels=1, output_fs=fs_req, **cfg_bla)}))
                st = await recv_json(ws, 'status')
                check(tag + ': reconfigured with output_fs, same actual rate',
                      st.get('event') == 'configured'
                      and abs(float(st.get('fs')) - fs_actual) < 1e-3,
                      st.get('fs'))

                caps_bla = await bla_captures(fs_actual)
                n_need = (BLA_T + BLA_P) * BLA_N
                check(tag + ': captures long enough (%d needed)' % n_need,
                      all(np.asarray(c.time_data).shape[0] >= n_need
                          for c in caps_bla),
                      [np.asarray(c.time_data).shape[0] for c in caps_bla])

                run_spec = {'multisine': bla_spec(fs_actual),
                            'x_mode': 'measured', 'x_channels': [0],
                            'resp_channels': [0, 1], 'fs': fs_actual}
                tfs = pydvma.analysis.calculate_bla(caps_bla, run_spec)
                g = np.asarray(tfs[0].tf_data)
                s_nl = np.asarray(tfs[0].bla_sigma_nl)
                s_n = np.asarray(tfs[0].bla_sigma_n)
                ident_err = float(np.max(np.abs(g[:, 0] - 1.0)))
                check(tag + ': measured-x G on the x channel == 1 exactly',
                      ident_err < 1e-9, '%.3g' % ident_err)
                check(tag + ': sigma_NL on the x channel ~ 0',
                      float(np.median(s_nl[:, 0])) < 1e-9,
                      '%.3g' % float(np.median(s_nl[:, 0])))
                ch1 = float(np.median(np.abs(g[:, 1])))
                if key == 'cDAQ':
                    # ai1 = the motionless IEPE accel; per-channel DSA
                    # ADCs, so a quiet input reads genuinely quiet.
                    check(tag + ': second channel at the noise floor '
                          '(|G| < 0.05)', ch1 < 0.05, '%.3g' % ch1)
                else:
                    # Multiplexed SAR (6212/6003): one ADC scans the
                    # list, and a FLOATING ai1 ghosts the ai0 sample it
                    # follows (~90% observed) — bench physics, not a
                    # pydvma bug. Wire ai1 to ground (or a source) to
                    # make a noise-floor assertion meaningful here.
                    print('  NOTE  %s: ch1 |G|med=%.3g — floating input '
                          'on a multiplexed ADC ghosts ch0; expected '
                          'unwired' % (tag, ch1))
                check(tag + ': sigma_n on ch1 is a real (nonzero) noise '
                      'estimate', float(np.median(s_n[:, 1])) > 0,
                      '%.3g' % float(np.median(s_n[:, 1])))

                # G. commanded-x re-solve of the same captures — the
                # start-offset MEASUREMENT (see the module docstring).
                # |G|med ~ 1/sqrt(M) = random phase per capture =
                # commanded-x invalid; |G|med ~ 1 with small sigma_NL
                # would mean start sync holds and the webui gate
                # (BLA_COMMANDED_X_START_SYNC_PROVEN) can be revisited.
                run_c = {'multisine': bla_spec(fs_actual),
                         'x_mode': 'commanded', 'x_channels': None,
                         'resp_channels': [0], 'fs': fs_actual}
                tfc = pydvma.analysis.calculate_bla(caps_bla, run_c)
                gc = np.asarray(tfc[0].tf_data)[:, 0]
                sc = np.asarray(tfc[0].bla_sigma_nl)[:, 0]
                g_med = float(np.median(np.abs(gc)))
                rel_nl = float(np.median(sc)) / max(g_med, 1e-12)
                print('  NOTE  %s commanded-x measurement: |G|med=%.4f '
                      '(1/sqrt(M)=%.3f if start offset is random), '
                      'sigma_NL/|G|=%.3g'
                      % (tag, g_med, 1.0 / np.sqrt(BLA_M), rel_nl))

        # ---- H. AO sample-clock coercion pins (direct nidaqmx) ----
        print('H. AO ladder coercion (direct nidaqmx)')
        try:
            import nidaqmx
            from nidaqmx.constants import AcquisitionType

            def ao_actual_rate(dev, rate):
                with nidaqmx.Task() as t:
                    t.ao_channels.add_ao_voltage_chan(
                        dev + '/ao0', min_val=-1, max_val=1)
                    t.timing.cfg_samp_clk_timing(
                        rate=rate, sample_mode=AcquisitionType.FINITE,
                        samps_per_chan=1000)
                    return float(t.timing.samp_clk_rate)

            import nidaqmx.system
            ni_devs = {d.product_type: d.name
                       for d in nidaqmx.system.System.local().devices}
            mod_9260 = next((n for p, n in ni_devs.items() if '9260' in p),
                            None)
            if mod_9260:
                r = ao_actual_rate(mod_9260, 25600.0 / 3.0)
                check('9260 AO exact at the 9234-coerced rate 8533.33 '
                      '(shared 51200/n ladder)',
                      abs(r - 25600.0 / 3.0) < 1e-3, r)
                r = ao_actual_rate(mod_9260, 8000.0)
                check('9260 AO coerces 8000 -> 8533.33 (the silent-path '
                      'warning is real)', abs(r - 25600.0 / 3.0) < 1e-3, r)
            else:
                print('  SKIP  9260 pins (module not connected)')
            dev_6212 = ni_devs.get('USB-6212')
            if dev_6212:
                r = ao_actual_rate(dev_6212, 10000.0)
                check('6212 AO exact at 10000', abs(r - 10000.0) < 1e-6, r)
            else:
                print('  SKIP  6212 pins (device not connected)')
        except ImportError:
            print('  SKIP  H (nidaqmx not importable here)')

    print()
    print('==== %d passed, %d failed ====' % (len(PASS), len(FAIL)))
    for name, detail in FAIL:
        print('FAILED: %s  [%s]' % (name, detail))
    return 1 if FAIL else 0


if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else 'ws://127.0.0.1:8766/ws'
    sys.exit(asyncio.run(main(url)))
