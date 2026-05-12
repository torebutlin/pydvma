# Python BLAS-threading on small matrices — reference note

## TL;DR

Multi-threaded BLAS can be **slower than single-threaded** when you do many
linear-algebra calls on small-to-medium matrices, because the thread-spawn /
synchronisation overhead dominates the actual FLOPs. The fix is one of:

- set `OPENBLAS_NUM_THREADS=1` (and friends) **before** `numpy` is imported, or
- use `threadpoolctl` to limit threads inside a `with` block after import.

It is a **per-process** fix, not a one-time machine-wide fix. Every fresh
Python interpreter gets the multi-threaded default again unless you re-apply
it (or bake it into your shell / venv).

## The symptom

You hit this when *all* of the following are true:

- You're doing repeated linear-algebra calls (`solve`, `lstsq`, `qr`, `svd`,
  `cholesky`, `inv`, `det`, `matmul`, eigendecompositions, …).
- The matrices are small-to-medium: roughly **under ~1000×1000** for dense
  doubles; under a few hundred for `complex128`. The exact crossover depends
  on the BLAS and the CPU.
- You make many calls (inside a loop, an iterative solver, a fitting routine).
- You're on a multi-core machine with a multi-threaded BLAS.

Tell-tale signs:

1. The linalg call takes far longer than you'd guess from the FLOP count
   (tens to hundreds of ms for a 200–500×500 solve that should be ~1 ms).
2. **Wild run-to-run jitter** (±20–30 %). Pure compute is usually steady;
   thread-startup latency is not.
3. Different timings depending on **how you launched Python** — from the
   shell vs. from an IDE Run button vs. from a notebook — because each one
   inherits different environment variables.
4. **`scipy.linalg.cho_factor` / `lu_factor` are much slower than
   `np.linalg.solve`** on the same matrix. (Common observation: factor
   wrappers in the tens-to-hundreds of ms range while the equivalent
   `np.linalg.solve` takes a few ms.) That gap is not all BLAS — see below.
5. Running with `OPENBLAS_NUM_THREADS=1 python …` makes the problem
   disappear and the run becomes much steadier.

## Why it happens

Two effects, and they compound:

**1. Thread-spawn overhead per BLAS call.** OpenBLAS (and to a lesser extent
other multi-threaded BLAS backends) spins up / synchronises its thread pool
on each call. For a big matrix that cost is amortised across millions of
FLOPs; for a small matrix it isn't, and the wall-clock time ends up
dominated by threading machinery rather than arithmetic. OpenBLAS shipped
with Anaconda on Apple Silicon is a particularly bad case in the wild;
**Intel MKL** is much better at avoiding this on small problems;
**macOS Accelerate** sits in between (and has its own quirks). The point is
*not* "OpenBLAS is bad" — it's "any multi-threaded BLAS can lose to
single-threaded on small enough problems."

**2. Python-level wrapper overhead on top.** `scipy.linalg.cho_factor` and
`scipy.linalg.lu_factor` return Python objects, handle pivot arrays,
default-validate inputs, etc. That overhead is independent of which BLAS is
linked, but it shows up *in the same place* as the BLAS issue, so it's easy
to conflate the two. `np.linalg.solve` calls straight through to LAPACK
with much less Python-side fuss, so on small matrices it is often
*dramatically* faster than the scipy "factor then solve" route — even with
single-threaded BLAS.

## How to verify it is this issue

1. **Check which BLAS you're linked against.**
   ```python
   import numpy as np
   np.show_config()
   ```
   Look for `openblas`, `mkl`, `blis`, or `accelerate`.

2. **A/B test the env-var fix.** From a shell:
   ```bash
   python your_script.py                          # baseline
   OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
   OMP_NUM_THREADS=1 python your_script.py        # pinned
   ```
   If the pinned version is meaningfully faster and lower-variance, the
   diagnosis is correct.

3. **Time with jitter visible.** Use `timeit` with `number=1, repeat=20`
   (not `number=large, repeat=small`) — you want to *see* the per-call
   variance, not average it out.

## The fix — option A: pin BLAS threads via env vars (most common)

Put this **at the very top** of your entry-point script, before any
`import numpy` or `import scipy`:

```python
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")   # macOS Accelerate
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")      # numexpr
```

**The ordering is load-bearing.** BLAS libraries read these env vars on
*library load*, which happens when numpy / scipy is first imported. If
you set them after that, nothing happens — it is a silent no-op.

Why `setdefault` and not `=`? So a caller can override from the shell with
e.g. `OPENBLAS_NUM_THREADS=4 python …` for a one-off run on a big problem.

## The fix — option B: `threadpoolctl` (most precise)

If you want to keep multi-threaded BLAS as the default but pin to one thread
for a specific hot loop — or you're writing library code and don't want to
touch the whole interpreter — use `threadpoolctl`:

```python
from threadpoolctl import threadpool_limits

with threadpool_limits(limits=1):
    for i in range(n_iters):
        x = np.linalg.solve(A, b)
```

This works *after* import, scopes the change to the `with` block, and
handles whichever BLAS is actually linked (OpenBLAS, MKL, BLIS, …) without
you needing to know which env vars to set. Cost: a small per-block setup.
It is the right tool when you have a fast path *and* a slow path in the
same process.

## Which linear-algebra functions does this affect?

Anything that ultimately calls into BLAS or LAPACK. That is most of the
numerical-linear-algebra surface area in scientific Python:

- **numpy:** `np.linalg.solve`, `inv`, `lstsq`, `qr`, `svd`, `eig`, `eigh`,
  `eigvals`, `eigvalsh`, `cholesky`, `det`, `slogdet`, `matrix_power`,
  `pinv`, `tensorsolve`; also `np.dot`, `np.matmul`, `np.einsum`, and the
  `@` operator for sufficiently large operands.
- **scipy.linalg:** all of the above, plus `cho_factor` / `cho_solve`,
  `lu_factor` / `lu_solve`, `solve_triangular`, `solve_banded`,
  `solve_toeplitz`, `expm`, `funm`, `sqrtm`. The factorisation wrappers
  here are also subject to the second-order Python-level overhead (see
  "Why" above) on top of the BLAS effect.
- **scipy.signal / scipy.optimize / scipy.stats**: anything that calls
  linalg under the hood — least-squares solvers, Kalman filters,
  curve_fit, multivariate normals, etc.
- **sklearn**: fit / transform routines that solve normal equations or do
  PCA / LDA — basically anything with a `.fit()` that doesn't say
  "stochastic" in the name.
- **CPU-side deep-learning frameworks** (PyTorch, JAX, TensorFlow) when
  doing matrix work on CPU also call BLAS and are subject to the same
  effect — but they have their own thread-pool controls that take
  precedence, so it's less common to fix this via the env vars there.

The **magnitude** of the slowdown scales with:

| Factor             | Worse when …                          |
| ------------------ | -------------------------------------- |
| Matrix size        | smaller (especially below a few-hundred dimension) |
| Call count         | many small calls in a loop             |
| Dtype              | complex tends to be worse than real    |
| BLAS backend       | OpenBLAS > Accelerate > MKL (worst to best) |
| Wrapper choice     | scipy factor wrappers > numpy direct   |
| Core count         | more cores = more spawn cost per call  |

If your matrices are 5000×5000 dense doubles and you call `solve` once,
this whole issue is irrelevant and you *want* multi-threaded BLAS.

## Does the fix persist?

**No — it is per-process.** Concretely:

- Setting env vars in a Python script affects only **that Python process**.
- The next interpreter you launch starts fresh with the multi-threaded
  default.
- Setting env vars **after numpy is imported** does nothing — too late.
  (`threadpoolctl` is the way to change thread count after import.)
- Restarting the kernel in a Jupyter notebook is a fresh process, so the
  fix needs to be in the first cell that imports numpy (or in the kernel
  launcher env).

If you want it to persist, choose one:

| Scope          | How                                                      | When to choose                                             |
| -------------- | -------------------------------------------------------- | ---------------------------------------------------------- |
| Single script  | `os.environ.setdefault(...)` at the top, before numpy    | Default. Explicit, version-controlled with the code.        |
| Whole shell    | `export OPENBLAS_NUM_THREADS=1` in `~/.zshrc` / `~/.bashrc` | You only ever do small-matrix work in this shell. Risky if you also do big-matrix runs — you'll silently lose threading. |
| Conda env      | `conda env config vars set OPENBLAS_NUM_THREADS=1`        | You want the setting to follow the environment, not the shell. |
| venv           | Append `export …` to the activation script               | Same as conda but for a plain venv.                        |
| IDE Run button | Add to the launch config / `.env` file                   | You launch from VS Code / PyCharm and want the same behaviour as the shell. |
| One call site  | `with threadpool_limits(limits=1):`                       | Library code, or fast-path + slow-path in the same process. |

For most scientific projects the recommended pattern is **explicit
`os.environ.setdefault` at the top of every entry-point script**, with a
short comment saying *why*. That is what travels with the code; the next
person who clones the repo gets the same behaviour without having to fix
their shell.

## When *not* to apply this

- Large dense problems (thousands × thousands) where you're FLOP-bound.
- Long-running training / fitting where the linalg cost amortises.
- HPC / cluster jobs where you've already pinned CPU affinity at the job
  level — adding a script-level override can fight with the scheduler.
- Inside library code that doesn't own the interpreter — use
  `threadpoolctl` instead so callers aren't surprised.

## Common pitfalls

- **Setting env vars after `import numpy`.** No effect. Either move them
  to the very top of the file, or switch to `threadpoolctl`.
- **IDE "Run" buttons.** VS Code / PyCharm "Run Python File" may not
  inherit your shell's exports unless you've also set them in the IDE's
  launch config. Either set them in code (option A) or in the IDE config.
- **Subprocesses with explicit `env=` passed to `subprocess.run`.**
  Explicit `env=` *replaces* the environment rather than extending it;
  the child won't inherit your `OPENBLAS_NUM_THREADS=1` unless you put it
  in the dict you pass. Prefer `env={**os.environ, "FOO": "BAR"}`.
- **Notebook kernels.** A long-lived kernel that imported numpy before
  your settings cell ran is stuck multi-threaded for the rest of its
  life. Restart the kernel.
- **Multiple BLAS in one process.** Some installs end up with numpy
  linked against one BLAS and scipy linked against another. `threadpoolctl`
  will show you both; env vars need to cover both.

## Quick diagnostic snippet

Drop into a notebook or REPL when you suspect this is happening:

```python
import numpy as np
from threadpoolctl import threadpool_info
import pprint, timeit

pprint.pprint(threadpool_info())              # what BLAS, how many threads
rng = np.random.default_rng(0)
A = rng.standard_normal((300, 300)) + 1j * rng.standard_normal((300, 300))
A = A @ A.conj().T + 300 * np.eye(300)        # well-conditioned Hermitian
b = rng.standard_normal(300) + 1j * rng.standard_normal(300)

times = timeit.repeat(lambda: np.linalg.solve(A, b),
                      number=1, repeat=20)
print(f"min={min(times)*1e3:.2f} ms  max={max(times)*1e3:.2f} ms  "
      f"ratio={max(times)/min(times):.1f}×")
```

A `max / min` ratio above ~3× on a steady machine is a strong hint that
thread-spawn jitter is dominating. Rerun under `threadpool_limits(limits=1)`
to confirm.

## Further reading

- `threadpoolctl` docs: <https://github.com/joblib/threadpoolctl>
- scikit-learn user guide on parallelism (good general explanation of
  nested BLAS / OpenMP threading):
  <https://scikit-learn.org/stable/computing/parallelism.html>
- numpy build / BLAS docs: `numpy.show_config()` and the numpy install
  guide.
