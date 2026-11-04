# Safari JIT probe (2026-11-04)

Safari 27.2's JavaScript engine miscompiles pyodide's JS-number-to-Python
conversion (`js2python_convertImmutable`) once it is hot: after about 11-13 k
calls a double crosses as the low 32 bits of its bit pattern (246.82 ->
1889785610, 10000.0 -> 0). The web app's in-browser engine used to convert
every array element through it, which corrupted the 4C6 modal-fit restore
and every later call. Since then the worker sends payloads as JSON text plus
raw bytes (`webui/src/lib/worker/pack.ts`, `pydvma.engine._call_packed`).

This page boots pyodide from a built app, converts arrays element by element
until the bug shows (stage `stress` reports the first wrong element), and then
checks that a packed `calc_fit` still comes back right (`packed-after-poison`).
Use it to see whether a new Safari still has the bug.

    mkdir -p /tmp/probe-site && ln -sfn "$PWD/webui/dist" /tmp/probe-site/app
    cp dev/safari-jit-probe/probe*.* /tmp/probe-site/
    python3 dev/safari-jit-probe/probeserve.py /tmp/probe-site /tmp/probe_log.jsonl 8797
    open -a Safari "http://localhost:8797/probe.html?v=2.8.4"   # v = the engine wheel version in webui/dist/pypi

Results show on the page and are appended to `/tmp/probe_log.jsonl`. Chrome,
Edge, Firefox and Playwright's WebKit build (26.5) do not show the bug.
