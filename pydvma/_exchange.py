# -*- coding: utf-8 -*-
"""A dataset as CSV or MATLAB data that loads back exactly.

Both formats carry what a ``.dvma`` holds — its manifest (every item's kind,
metadata, settings, calibration, units, names, timestamps, ids and links,
provenance, the web app's per-item state) and every array — laid out for
other tools to read, and both are read back through the ``.dvma`` reader
(`container.dataset_from_manifest`). Nothing is mapped field by field, so a
field the container gains later reaches CSV and MATLAB with no change here.

**CSV, format ``pydvma-csv 1``**: a few ``#`` lines saying what the file is,
the manifest as one ``# manifest: <json>`` line, then one table per item
(plus one per array that cannot share it), each a ``# table`` heading line,
a line of column names and the rows. The rows of an item's table run along
its primary axis (``time_axis`` or ``freq_axis``; ``M`` for a modal fit);
an array whose own axes include that length is laid out with that axis as
the rows and its other axes flattened (C order) into columns, so a TF table
reads ``freq_axis, tf_data[0].re, tf_data[0].im, tf_coherence[0]``. Complex
arrays become ``.re``/``.im`` column pairs. Floats are written as the
shortest text that reads back to the same float64 (Python's ``repr``:
``0.1``, ``nan``, ``-inf``, ``-0.0``), so every array comes back with the
same values, dtype and shape (a NaN's payload bits aside);
the manifest's ``csv_tables`` key records each array's place, shape and
dtype, and the reader needs nothing else.

**MATLAB, format ``pydvma-mat 1``**: see `dataset_to_mat_dict`.
"""
import io
import json
import re

import numpy as np

from . import container, datastructure

CSV_FORMAT = 'pydvma-csv 1'
_CSV_FIRST_LINE = '# pydvma dataset (pydvma-csv 1)'
_CSV_FORMAT_RE = re.compile(r'pydvma-csv ([^\s)]+)')
_MANIFEST_PREFIX = '# manifest: '
_TABLE_PREFIX = '# table '


def is_pydvma_csv_line(first_line):
    """True if `first_line` names the pydvma CSV format (any version, so a
    newer one is refused with a reason rather than as an unknown file)."""
    line = first_line.lstrip('﻿')
    return line.startswith('#') and _CSV_FORMAT_RE.search(line) is not None


# ---------------------------------------------------------------------------
# Laying arrays out as table columns


def _column_names(field, trailing, is_complex):
    """Column names for an array whose non-row axes have shape `trailing`."""
    if trailing == ():
        bases = [field]
    else:
        bases = [field + ''.join('[%d]' % i for i in idx)
                 for idx in np.ndindex(*trailing)]
    if not is_complex:
        return bases
    return [b + part for b in bases for part in ('.re', '.im')]


def _as_columns(arr, row_axis):
    """``arr`` as a 2-D float64 block (rows, columns) and its column count;
    complex values as interleaved re/im columns."""
    if arr.ndim == 0:
        block = arr.reshape(1, 1)
    else:
        rows = arr.shape[row_axis]
        cols = arr.size // rows if rows else int(np.prod(
            [n for k, n in enumerate(arr.shape) if k != row_axis], dtype=int))
        block = np.moveaxis(arr, row_axis, 0).reshape(rows, cols)
    if np.iscomplexobj(block):
        out = np.empty((block.shape[0], 2 * block.shape[1]))
        out[:, 0::2] = block.real
        out[:, 1::2] = block.imag
        return out
    if block.dtype.kind in 'iu' and block.size and np.max(np.abs(block)) >= 2 ** 53:
        raise ValueError('an integer array holds values too large to write '
                         'exactly as text (|x| >= 2**53)')
    return block.astype(np.float64)


def _write_rows(buf, block, is_int):
    """Write a float64 block as CSV rows: floats as Python's shortest text
    that reads back to the same float64 (``repr``: ``0.1``, ``nan``,
    ``-inf``), integer-typed columns as integers."""
    rows = block.tolist()
    if not any(is_int):
        buf.write('\n'.join(','.join(map(repr, r)) for r in rows))
    else:
        conv = [(lambda v: str(int(v))) if i else repr for i in is_int]
        buf.write('\n'.join(','.join(c(v) for c, v in zip(conv, r)) for r in rows))
    buf.write('\n')


def _heading_text(value):
    """A manifest value made safe for a one-line, human-only heading."""
    return ' '.join(str(value).split())


def _item_heading(index, entry):
    kind = entry['kind']
    meta = entry.get('meta') or {}
    name = meta.get('test_name')
    parts = ['item %d, %s' % (index, kind)]
    if name:
        parts[0] += " '%s'" % _heading_text(name)
    units = meta.get('units')
    if isinstance(units, list) and units:
        parts.append('units ' + _heading_text(', '.join(str(u) for u in units)))
    cal = meta.get('channel_cal_factors')
    if isinstance(cal, dict) and isinstance(cal.get('__array__'), list):
        parts.append('cal_factors ' + ', '.join(
            '%.12g' % v if isinstance(v, (int, float)) else '?'
            for v in cal['__array__']))
    return '; '.join(parts)


def _plan_tables(manifest, arrays):
    """Group every array into tables; returns the ``csv_tables`` record."""
    tables = []
    for index, entry in enumerate(manifest['items']):
        members = list((entry.get('arrays') or {}).items())
        if not members:
            continue
        first = arrays[members[0][1]]
        rows = first.shape[0] if first.ndim else 1
        main = {'item': index, 'rows': rows, 'arrays': []}
        own = []
        for field, member in members:
            arr = arrays[member]
            axis = next((k for k, n in enumerate(arr.shape) if n == rows), None)
            spec = {'member': member, 'field': field, 'shape': list(arr.shape),
                    'dtype': arr.dtype.str, 'complex': bool(np.iscomplexobj(arr))}
            if arr.ndim == 0:
                spec['row_axis'] = None
                own.append({'item': index, 'rows': 1, 'arrays': [spec]})
            elif axis is None:
                spec['row_axis'] = 0
                own.append({'item': index, 'rows': arr.shape[0], 'arrays': [spec]})
            else:
                spec['row_axis'] = axis
                main['arrays'].append(spec)
        for table in [main] + own:
            if not table['arrays']:
                continue
            column = 0
            for spec in table['arrays']:
                shape = tuple(spec['shape'])
                trailing = () if spec['row_axis'] is None else \
                    shape[:spec['row_axis']] + shape[spec['row_axis'] + 1:]
                spec['trailing'] = list(trailing)
                spec['first_column'] = column
                spec['n_columns'] = int(np.prod(trailing, dtype=int)) * (2 if spec['complex'] else 1)
                column += spec['n_columns']
            table['n_columns'] = column
            tables.append(table)
    return tables


# ---------------------------------------------------------------------------
# CSV


def dataset_to_csv_text(dataset):
    """`dataset` as the text of a ``pydvma-csv 1`` file (see the module
    docstring for the layout)."""
    manifest, arrays = container.dataset_manifest(dataset)
    tables = _plan_tables(manifest, arrays)
    manifest['storage'] = 'csv'
    manifest['csv_tables'] = tables
    buf = io.StringIO()
    buf.write('\n'.join([
        _CSV_FIRST_LINE,
        '# Written by pydvma %s. Load it back with pydvma.load_data, or Load '
        'Data in the web app.' % datastructure.VERSION,
        '# Values are RAW, calibration NOT applied: multiply a column by its '
        "item's channel_cal_factors.",
        "# Each '# table' line below starts one table: its column names, then "
        'its rows.',
        _MANIFEST_PREFIX + json.dumps(manifest, allow_nan=False, ensure_ascii=True),
    ]) + '\n')
    for k, table in enumerate(tables):
        entry = manifest['items'][table['item']]
        fields = ', '.join(s['field'] for s in table['arrays'])
        buf.write('%s%d: %s (%s)\n' % (_TABLE_PREFIX, k, _item_heading(table['item'], entry), fields))
        names, blocks, fmts = [], [], []
        for spec in table['arrays']:
            arr = arrays[spec['member']]
            names += _column_names(spec['field'], tuple(spec['trailing']), spec['complex'])
            blocks.append(_as_columns(arr, spec['row_axis']))
            fmts += [arr.dtype.kind in 'biu'] * spec['n_columns']
        buf.write(','.join(names) + '\n')
        block = np.hstack(blocks) if blocks else np.zeros((table['rows'], 0))
        if block.shape[1] and block.shape[0]:
            _write_rows(buf, block, fmts)
    return buf.getvalue()


def _read_table(body, rows, n_columns, k, name):
    """One table's data rows as a (rows, n_columns) float64 array."""
    if n_columns == 0:
        data = np.zeros((rows, 0))         # no columns, so no lines: rows from the manifest
    elif rows == 0 or not body.strip():
        data = np.zeros((0, n_columns))
    else:
        try:
            data = np.loadtxt(io.StringIO(body), delimiter=',', dtype=np.float64, ndmin=2)
        except ValueError as e:
            raise ValueError('%s: table %d cannot be read (%s); the file was '
                             'changed after it was exported?' % (name, k, e)) from e
    if data.shape != (rows, n_columns):
        raise ValueError(
            "%s: table %d has %d rows and %d columns, but the file's manifest "
            'says %d and %d: the file was changed after it was exported '
            '(opened and saved again in a spreadsheet?). Export it again.'
            % (name, k, data.shape[0], data.shape[1] if data.ndim == 2 else 0,
               rows, n_columns))
    return data


def _array_from_columns(data, spec):
    cols = data[:, spec['first_column']:spec['first_column'] + spec['n_columns']]
    if spec['complex']:
        # part by part: `re + 1j*im` is a complex multiply, which turns
        # 1+nanj into nan+nanj and an imaginary -0.0 into +0.0
        z = np.empty((cols.shape[0], cols.shape[1] // 2), dtype=complex)
        z.real = cols[:, 0::2]
        z.imag = cols[:, 1::2]
        cols = z
    shape = tuple(spec['shape'])
    if spec['row_axis'] is None:
        arr = cols.reshape(shape)
    else:
        moved = cols.reshape((data.shape[0],) + tuple(spec['trailing']))
        arr = np.moveaxis(moved, 0, spec['row_axis'])
    dtype = np.dtype(spec['dtype'])
    if dtype.kind in 'biu':
        arr = np.rint(arr)
    return np.ascontiguousarray(arr.astype(dtype)).reshape(shape)


def dataset_from_csv_text(text, name):
    """Rebuild a DataSet from the text of a ``pydvma-csv`` file.

    Args:
        text (str): The whole file.
        name (str): What to call the file in error messages.

    Returns:
        dataset (DataSet): Exactly what was exported.

    Raises:
        ValueError: If the text is not this format, is another version of
            it, or was changed after it was exported (a table's row or
            column count no longer matches its manifest).
    """
    text = text.lstrip('﻿').replace('\r\n', '\n')
    first, _, rest = text.partition('\n')
    found = _CSV_FORMAT_RE.search(first) if first.startswith('#') else None
    if found is None:
        raise ValueError("%s is not a pydvma CSV: its first line does not name "
                         "the format '%s'." % (name, CSV_FORMAT))
    if found.group(0) != CSV_FORMAT:
        raise ValueError("%s is format '%s', and this pydvma reads '%s'; update "
                         'pydvma (pip install --upgrade pydvma) to load it.'
                         % (name, found.group(0), CSV_FORMAT))
    start = text.find('\n' + _MANIFEST_PREFIX)
    if start < 0:
        raise ValueError('%s has no manifest line, so it cannot be loaded.' % name)
    start += 1 + len(_MANIFEST_PREFIX)
    end = text.find('\n', start)
    manifest = json.loads(text[start:end if end >= 0 else None])
    tables = manifest.get('csv_tables') or []

    arrays = {}
    pos = end
    for k, table in enumerate(tables):
        head = text.find('\n' + _TABLE_PREFIX + '%d:' % k, pos)
        if head < 0:
            raise ValueError('%s: table %d is missing; the file was changed or '
                             'cut short after it was exported.' % (name, k))
        names_start = text.find('\n', head + 1) + 1
        body_start = text.find('\n', names_start)
        body_start = len(text) if body_start < 0 else body_start + 1
        nxt = text.find('\n' + _TABLE_PREFIX, body_start - 1)
        body_end = len(text) if nxt < 0 else nxt + 1
        data = _read_table(text[body_start:body_end], table['rows'],
                           table['n_columns'], k, name)
        for spec in table['arrays']:
            arrays[spec['member']] = _array_from_columns(data, spec)
        pos = body_end - 1
    return container.dataset_from_manifest(manifest, arrays.__getitem__, name)


# ---------------------------------------------------------------------------
# MATLAB

MAT_FORMAT = 'pydvma-mat 1'
_MAT_FORMAT_RE = re.compile(r'pydvma-mat ([^\s)]+)')


def is_pydvma_mat(d):
    """True if the loaded MATLAB variables `d` are a pydvma export (any
    version): they hold ``pydvma_manifest``."""
    return 'pydvma_manifest' in d


def _mat_text(value):
    return '' if value is None else str(value)


def dataset_to_mat_dict(dataset):
    """`dataset` as the variables of a ``pydvma-mat 1`` file, for
    ``scipy.io.savemat(..., oned_as='column')``.

    - ``pydvma_format``: ``'pydvma-mat 1'``.
    - ``pydvma_manifest``: the ``.dvma`` manifest as JSON text (MATLAB's
      ``jsondecode`` reads it); its ``mat_arrays`` key gives each array's
      item, field, shape and dtype, which is all the reader needs.
    - ``pydvma_items``: a cell array with one struct per item, in order:
      ``kind``, ``test_name``, ``units`` (a cell of text), ``fs``,
      ``timestamp`` (ISO text), ``channel_cal_factors``, and each array
      under its own field name at its exact shape (1-D arrays as column
      vectors). In MATLAB, ``d = load('x.mat'); d.pydvma_items{2}.tf_data``.
    """
    manifest, arrays = container.dataset_manifest(dataset)
    manifest['storage'] = 'mat'
    manifest['mat_arrays'] = {}
    items = np.empty((len(manifest['items']),), dtype=object)
    for index, entry in enumerate(manifest['items']):
        meta = entry.get('meta') or {}
        settings = entry.get('settings') or {}
        struct = {'kind': entry['kind'],
                  'test_name': _mat_text(meta.get('test_name'))}
        units = meta.get('units')
        if isinstance(units, list):
            struct['units'] = np.array([_mat_text(u) for u in units], dtype=object)
        fs = settings.get('fs')
        if isinstance(fs, (int, float)):
            struct['fs'] = float(fs)
        stamp = meta.get('timestamp')
        if isinstance(stamp, dict) and '__datetime__' in stamp:
            struct['timestamp'] = stamp['__datetime__']
        cal = meta.get('channel_cal_factors')
        if isinstance(cal, dict) and isinstance(cal.get('__array__'), list):
            try:
                struct['channel_cal_factors'] = np.asarray(cal['__array__'], dtype=float)
            except (TypeError, ValueError):
                pass                     # tagged non-finite entries: in the manifest
        for field, member in (entry.get('arrays') or {}).items():
            arr = arrays[member]
            struct[field] = arr
            manifest['mat_arrays'][member] = {
                'item': index, 'field': field, 'shape': list(arr.shape),
                'dtype': arr.dtype.str}
        items[index] = struct
    return {'pydvma_format': MAT_FORMAT,
            'pydvma_manifest': json.dumps(manifest, allow_nan=False, ensure_ascii=True),
            'pydvma_items': items}


def dataset_from_mat_dict(d, name):
    """Rebuild a DataSet from the variables of a ``pydvma-mat`` file.

    Args:
        d (dict): The variables, as ``scipy.io.loadmat(path,
            simplify_cells=True)`` returns them.
        name (str): What to call the file in error messages.

    Returns:
        dataset (DataSet): Exactly what was exported.

    Raises:
        ValueError: If `d` is another version of the format, or an array
            is missing or no longer has its exported size.
    """
    fmt = str(d.get('pydvma_format', ''))
    found = _MAT_FORMAT_RE.search(fmt)
    if found is None or found.group(0) != MAT_FORMAT:
        raise ValueError("%s is format '%s', and this pydvma reads '%s'; update "
                         'pydvma (pip install --upgrade pydvma) to load it.'
                         % (name, fmt or 'unknown', MAT_FORMAT))
    manifest = json.loads(str(d['pydvma_manifest']))
    items = d.get('pydvma_items')
    if isinstance(items, dict):          # a one-element cell comes back as its struct
        items = [items]
    elif items is None:
        items = []
    arrays = {}
    for member, spec in (manifest.get('mat_arrays') or {}).items():
        try:
            raw = np.asarray(items[spec['item']][spec['field']])
            arr = raw.reshape(spec['shape']).astype(np.dtype(spec['dtype']))
        except (IndexError, KeyError, ValueError, TypeError) as e:
            raise ValueError('%s: item %d has no %s of the exported size %s; '
                             'the file was changed after it was exported.'
                             % (name, spec['item'], spec['field'], spec['shape'])) from e
        arrays[member] = np.ascontiguousarray(arr)
    return container.dataset_from_manifest(manifest, arrays.__getitem__, name)
