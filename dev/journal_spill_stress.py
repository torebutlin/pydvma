# -*- coding: utf-8 -*-
"""Stress harness for SessionJournal._spill's Windows failure mode.

Background (2026-08-20): tests/test_journal.py::TestSpill::
test_concurrent_spill_matches_final_doc flaked once in a loaded
full-suite run on the Windows PC. The cause is environmental, not a
journal race: ``os.replace`` fails with a sharing violation when an
external scanner (Defender real-time protection, the search indexer)
transiently holds the freshly written temp file or the spill target
open without ``FILE_SHARE_DELETE``; ``_spill`` swallows the OSError by
design (best-effort), and the disk keeps the PREVIOUS doc.

Measured on the office Windows PC (22 CPU hogs saturating the box):

* pre-fix, mode A (CPU load only, NO artificial file-holder):
  6/100 iterations left disk != final doc; 368/1000 replaces raised
  ``PermissionError(13)`` — that interference is the REAL machine's
  own scanners. 0 torn writes.
* pre-fix, mode B (plus a thread re-opening the spill target every
  ~2 ms, an adversarial scanner proxy): 77/100 mismatches. 0 torn.
* post-fix (``_replace_with_retry``), mode A: 0/100 mismatches with
  446 transient errors absorbed. Mode B's pathological holder still
  wins sometimes (22/100) — that is the documented best-effort edge,
  now visible via ``SessionJournal.spill_failures``.

Usage (from the repo root)::

    python dev/journal_spill_stress.py A 100   # CPU load only
    python dev/journal_spill_stress.py B 100   # + file-holder thread

Expect 0 mismatches in mode A and 0 torn writes in both modes.
"""
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import pydvma.journal as journal_module          # noqa: E402
from pydvma.journal import SessionJournal        # noqa: E402

_real_replace = os.replace
replace_errors = []


def counting_replace(src, dst):
    """os.replace stand-in that records every raised OSError."""
    try:
        _real_replace(src, dst)
    except OSError as e:
        replace_errors.append(repr(e))
        raise


def cpu_hog(stop_evt):
    """Spin until told to stop (one per spare core, own process)."""
    x = 0
    while not stop_evt.is_set():
        x += 1


def run_once(tmpdir, interfere):
    """One iteration of the concurrent-spill test body.

    Returns ``(disk_matches_final_doc, torn)`` where ``torn`` means the
    on-disk bytes interleave the two writers' payloads — which the
    atomic tempfile-then-rename must make impossible no matter what.
    """
    spill = os.path.join(tmpdir, 'session.dvma')
    j = SessionJournal(spill_path=spill)
    payload_a = b'A' * 1_000_000
    payload_b = b'B' * 900_000
    rounds = 5

    stop = threading.Event()

    def scanner():
        # Adversarial AV/indexer proxy: plain open() on Windows takes
        # no FILE_SHARE_DELETE, so holding the target open makes
        # os.replace onto it raise PermissionError.
        while not stop.is_set():
            try:
                with open(spill, 'rb') as fh:
                    fh.read(64)
                    time.sleep(0.002)
            except OSError:
                pass

    scan_t = None
    if interfere:
        scan_t = threading.Thread(target=scanner, daemon=True)
        scan_t.start()

    def writer(payload):
        for _ in range(rounds):
            j.set_doc(payload)

    threads = [threading.Thread(target=writer, args=(payload_a,)),
               threading.Thread(target=writer, args=(payload_b,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    if scan_t is not None:
        scan_t.join()

    with open(spill, 'rb') as fh:
        on_disk = fh.read()
    final_doc = j.state()[0]
    torn = not (set(on_disk) <= {ord('A')} or set(on_disk) <= {ord('B')})
    return on_disk == final_doc, torn


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'B'
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    interfere = (mode.upper() == 'B')

    os.replace = counting_replace

    n_hogs = max(1, multiprocessing.cpu_count() - 2)
    stop_evt = multiprocessing.Event()
    hogs = [multiprocessing.Process(target=cpu_hog, args=(stop_evt,))
            for _ in range(n_hogs)]
    for h in hogs:
        h.start()

    mismatches = 0
    torn_count = 0
    try:
        for _ in range(iters):
            tmpdir = tempfile.mkdtemp(prefix='spillstress-')
            try:
                ok, torn = run_once(tmpdir, interfere)
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
            if not ok:
                mismatches += 1
            if torn:
                torn_count += 1
    finally:
        stop_evt.set()
        for h in hogs:
            h.join()
        os.replace = _real_replace

    print('mode=%s iters=%d cpu_hogs=%d' % (mode, iters, n_hogs))
    print('disk-vs-memory mismatches: %d' % mismatches)
    print('torn (interleaved) writes: %d' % torn_count)
    print('raised os.replace errors:  %d (incl. retried attempts)'
          % len(replace_errors))
    if replace_errors:
        print('first error: %s' % replace_errors[0])


if __name__ == '__main__':
    main()
