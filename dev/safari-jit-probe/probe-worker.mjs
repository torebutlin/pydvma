// Probe: how does this browser's pyodide read a JS Float64Array into numpy?
import { loadPyodide } from '/app/pyodide/pyodide.mjs';

const send = (stage, data) => {
  postMessage({ stage, data });
  fetch('/log', { method: 'POST', body: JSON.stringify({ stage, data }) }).catch(() => {});
};
const VALUES = [246.82, 0.0011, 5.0, -0.25, 1370.36, 3.0e-7];

self.onmessage = async (e) => {
  const cloned = e.data.cloned; // a Float64Array structured-cloned from the page, as the app sends
  try {
    const py = await loadPyodide({
      indexURL: '/app/pyodide/',
      packageBaseUrl: 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/',
    });
    const mod = py._module;
    const info = (arr) => {
      const [ptr, size, checked] = mod.get_buffer_datatype(arr);
      const fmt = ptr ? String.fromCharCode(mod.HEAPU8[ptr]) : null;
      return { ctor: arr.constructor.name, ptr, size, checked, fmt };
    };
    const fmtTable = () => {
      // The whole "b\0B\0h\0H\0i\0I\0q\0Q\0f\0d" string pyodide points into.
      const [ptr] = mod.get_buffer_datatype(new Int8Array(1));
      return Array.from(mod.HEAPU8.slice(ptr, ptr + 20)).map((c) => (c ? String.fromCharCode(c) : '0')).join('');
    };
    send('ua', { ua: navigator.userAgent });
    send('after-boot', { local: info(new Float64Array(2)), cloned: info(cloned), table: fmtTable() });

    await py.loadPackage(['numpy']);
    const conv = py.runPython(
      'import numpy as np\n' +
      'def conv(x):\n' +
      '    return np.asarray(x, dtype=np.float64).tolist()\n' +
      'conv');
    const test = (stage) => {
      const local = new Float64Array(VALUES);
      const a = conv(local); const b = conv(cloned);
      send(stage, {
        local_info: info(local), cloned_info: info(cloned), table: fmtTable(),
        local_np: a.toJs(), cloned_np: b.toJs(), expected: VALUES,
        heap_mb: Math.round(mod.HEAPU8.length / 1048576),
      });
      a.destroy(); b.destroy();
    };
    test('after-numpy');

    await py.loadPackage(['scipy', 'micropip']);
    test('after-scipy');

    const micropip = py.pyimport('micropip');
    await micropip.install.callKwargs(
      ['/app/pypi/pydvma-' + (new URLSearchParams(self.location.search).get('v') ?? '2.8.4') + '-py3-none-any.whl', '/app/pypi/PeakUtils-1.3.5-py3-none-any.whl'],
      { deps: false });
    const glue = py.pyimport('pydvma.engine');
    test('after-pydvma');

    // The app's own path: a nested {shape, data, complex} payload through callKwargs.
    const rebuild = py.runPython(
      'import numpy as np\n' +
      'from pydvma import engine\n' +
      'def rebuild(M=None):\n' +
      '    return np.asarray(engine._get(M, "data"), dtype=np.float64).tolist()\n' +
      'rebuild');
    const viaKwargs = rebuild.callKwargs({ M: { shape: [1, VALUES.length], data: cloned, complex: false } });
    send('app-path-kwargs', { got: viaKwargs.toJs(), expected: VALUES });
    viaKwargs.destroy();

    // The app's volume: one restore sends 23 sets' interleaved TF (25001 x 2
    // values each) through np.asarray element by element. Do that, checking
    // every converted value against the JS source, and report the first
    // array (and element) where they part company.
    const check = py.runPython(
      'import numpy as np\n' +
      'def check(x, n):\n' +
      '    a = np.asarray(x, dtype=np.float64)\n' +
      '    b = np.frombuffer(x.to_bytes(), dtype=np.float64)\n' +
      '    bad = np.flatnonzero(a != b)\n' +
      '    if bad.size == 0:\n' +
      '        return None\n' +
      '    i = int(bad[0])\n' +
      '    lo = int(b[i:i+1].view(np.int32)[0])\n' +
      '    return [n, int(bad.size), i, float(b[i]), float(a[i]), lo]\n' +
      'check');
    let firstBad = null;
    const t0 = performance.now();
    for (let n = 0; n < 60 && !firstBad; n++) {
      const arr = new Float64Array(50002);
      for (let i = 0; i < arr.length; i++) arr[i] = Math.sin(i * 0.37 + n) * (1 + i * 1e-3) + 1e-9 * i;
      const r = check(arr, n);
      if (r) { firstBad = r.toJs(); r.destroy(); }
    }
    send('stress', { firstBad, seconds: Math.round(performance.now() - t0) / 1000,
      note: 'firstBad = [array #, n bad, first bad index, true value, converted value, low int32 word]' });
    test('after-stress');

    // With the conversion now poisoned, the packed path (JSON text + bytes)
    // must still deliver a fit's arrays and scalars intact.
    const n = 4000; const f = new Float64Array(n); const g = new Float64Array(2 * n);
    for (let i = 0; i < n; i++) {
      f[i] = i * 0.25; const w = 2 * Math.PI * f[i];
      let re = 0, im = 0;
      for (const [fn, zn, an] of [[250, 0.002, 1e3], [400, 0.002, -1e3]]) {
        const wn = 2 * Math.PI * fn; const dr = wn * wn - w * w, di = 2 * zn * wn * w; const d2 = dr * dr + di * di;
        re += an * dr / d2; im += -an * di / d2;
      }
      g[2 * i] = -w * w * re; g[2 * i + 1] = -w * w * im;   // times (iw)^2
    }
    const json = JSON.stringify({
      freq_axis: { __pydvma_buf__: 0, dtype: '<f8', length: n },
      tf_data: { __pydvma_buf__: 1, dtype: '<f8', length: 2 * n },
      n_tf: 1, n_channels: 2, fs: 2000, freq_range: [230, 270], measurement_type: 'acc',
      action: 'fit', n_modes: 1 });
    const res = glue._call_packed('calc_fit', json, [new Uint8Array(f.buffer), new Uint8Array(g.buffer)]);
    const out = res.toJs({ dict_converter: Object.fromEntries });
    res.destroy();
    send('packed-after-poison', { fn: Array.from(out.fn.data), zn: Array.from(out.zn.data), expected: [250, 0.002] });

    // Grow the heap the way a big compute does, then test again.
    py.runPython('import numpy as np\n_big = [np.ones(25_000_000) for _ in range(6)]\n');
    test('after-heap-growth');
    py.runPython('del _big');
    test('after-free');
    send('done', {});
  } catch (err) {
    send('error', { message: String(err && err.message || err), stack: String(err && err.stack || '') });
  }
};
