# -*- coding: utf-8 -*-
"""The .dvma container file format (format v2).

A ``.dvma`` file is a zip archive holding ``manifest.json`` plus one
plain ``.npy`` file (saved with ``allow_pickle=False``) per array
attribute. Unlike the legacy ``.npy`` pickle format, it contains no
executable content, is versioned, and is independent of pydvma's
class layout — the manifest schema, not the Python object graph, is
the contract. It is also readable outside Python (unzip + any npy
parser), which the browser interface relies on.

Layout::

    manifest.json                    # schema below
    arrays/0000_time_axis.npy        # one member per array attribute
    arrays/0000_time_data.npy
    arrays/0001_freq_axis.npy
    ...

Manifest schema (format_version 1)::

    {
      "format": "dvma-dataset",
      "format_version": 1,
      "pydvma_version": "<version that wrote the file>",
      "storage": "npy",              # extension point for future
                                     # HDF5 / chunked backends
      "items": [
        {
          "kind": "TimeData",        # class name in datastructure.py
          "arrays": {"time_axis": "arrays/0000_time_axis.npy", ...},
          "meta": {...},             # scalars: see _META_FIELDS
          "settings": {...} | null   # MySettings.__dict__, JSON-encoded
        },
        ...
      ]
    }

Scalar values use small type tags so JSON round-trips losslessly:
``{"__uuid__": "..."}, {"__datetime__": "<isoformat>"},
{"__array__": [...]}, {"__float__": "inf" | "-inf" | "nan"}``;
everything else is a plain JSON value. The manifest is guaranteed
strict JSON (``allow_nan=False``): non-finite floats are always
tagged, so ``JSON.parse`` in a browser never chokes on bare
``Infinity`` / ``NaN``. Arrays embedded in the manifest
(``__array__``) are stored as plain JSON lists and restore as
float64/int arrays; the ``.npy`` members preserve dtype exactly.
``meta`` may also carry optional analysis flags (see `_OPTIONAL_META`)
that are written only when set on the object.

Manifest keys unknown to this reader are not consumed — but they are
not DISCARDED either: `load` stashes them, per item, on the rebuilt
object as `_ITEM_EXTRA_ATTR` and `_write_dataset` re-emits them
verbatim. That makes a Python load→save round-trip LOSSLESS for
document state only the browser app understands (its per-item ``ui``
block of channel labels and per-set analysis settings; the ModalData
``meta`` extras ``measurement_type`` / ``source_targets``), which
:meth:`pydvma.session.Session.push` would otherwise destroy on every
push. Python's own known fields always win on collision.

Use `save` / `load`, or their in-memory twins `save_bytes` /
`load_bytes` (same manifest, same members, one shared writer/reader —
no filesystem touched) for callers that move a dataset over a socket
or straight into another buffer rather than a file, e.g. the serve
bridge's capture path and the pyodide engine's legacy/mat import ops.
``file.save_data`` and ``file.load_data`` delegate to `save`/`load` —
`load` sniffs the format from magic bytes so old pickle ``.npy``
files keep working.
"""
import datetime
import io
import json
import math
import os
import tempfile
import uuid
import zipfile

import numpy as np

from . import datastructure
from . import options

FORMAT_NAME = 'dvma-dataset'
FORMAT_VERSION = 1

# Array attributes per data kind. Order defines member naming only.
_ARRAY_FIELDS = {
    'TimeData':      ['time_axis', 'time_data'],
    'FreqData':      ['freq_axis', 'freq_data'],
    'CrossSpecData': ['freq_axis', 'Pxy', 'Cxy'],
    'TfData':        ['freq_axis', 'tf_data', 'tf_coherence',
                       'bla_sigma_nl', 'bla_sigma_n'],
    'SonoData':      ['time_axis', 'freq_axis', 'sono_data'],
    'ModalData':     ['M'],
    'MetaData':      [],
}

# Scalar/metadata attributes per data kind.
_META_FIELDS = {
    'TimeData':      ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'unique_id', 'id_link'],
    'FreqData':      ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'id_link'],
    'CrossSpecData': ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'id_link'],
    'TfData':        ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'id_link', 'flag_modal_TF',
                       'bla'],
    'SonoData':      ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'id_link'],
    'ModalData':     ['units', 'test_name', 'timestamp', 'timestring',
                       'id_link', 'channels'],
    'MetaData':      ['units', 'channel_cal_factors', 'tf_cal_factors',
                       'timestamp', 'timestring'],
}

# Optional post-construction attributes set by in-place analysis
# (analysis.multiply_by_power_of_iw, analysis.clean_impulse) or stamped
# at the calc sites (analysis._stamp_source: source_signature, the hash
# of the SOURCE samples this result was computed from, and
# source_settings, the analysis knobs that call used). Written only
# when present on the object; restored only when present in the
# manifest — absence must survive the round-trip because downstream
# code uses hasattr() guards, and because a derived item written before
# signatures existed makes no claim about its chain.
_OPTIONAL_META = {
    'TimeData': ['impulse_cleaned'],
    'FreqData': ['iw_power_counter', 'source_signature', 'source_settings'],
    'TfData':   ['iw_power_counter', 'source_signature', 'source_settings'],
}

# Tag keys reserved by _encode_value; user dicts must not use them.
_RESERVED_TAGS = ('__uuid__', '__datetime__', '__array__', '__float__')

# Item-entry keys this reader consumes itself. Everything else in an
# item's manifest entry belongs to some other writer (today: the
# browser app's `ui` block) and is stashed verbatim by `load`.
_ITEM_KEYS = ('kind', 'arrays', 'meta', 'settings')

# Private attribute holding one item's unconsumed manifest keys, as
# raw (already-encoded) manifest JSON. Shape mirrors the entry: unknown
# top-level keys at the top level, unknown `meta` keys under 'meta'
# (unambiguous, since 'meta' itself is never a top-level extra). Absent
# when the item had none, so `hasattr` stays a meaningful test and
# objects built in Python never grow it. Never a data field: it merges
# into the manifest dict on save and nowhere else.
_ITEM_EXTRA_ATTR = '_container_extra'

_KIND_CLASSES = {
    'TimeData': datastructure.TimeData,
    'FreqData': datastructure.FreqData,
    'CrossSpecData': datastructure.CrossSpecData,
    'TfData': datastructure.TfData,
    'SonoData': datastructure.SonoData,
    'ModalData': datastructure.ModalData,
    'MetaData': datastructure.MetaData,
}


def _encode_value(value):
    """JSON-encode one metadata value with type tags for uuid /
    datetime / ndarray / non-finite float so decoding is lossless.

    Non-finite floats become ``{'__float__': 'inf'|'-inf'|'nan'}`` —
    including inside ``__array__`` lists — because the manifest is
    written with ``allow_nan=False`` and must stay strict JSON.
    Dicts are encoded recursively; keys must be strings and must not
    collide with the reserved tag names (`_RESERVED_TAGS`)."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return {'__uuid__': str(value)}
    if isinstance(value, datetime.datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, np.ndarray):
        # route tolist() back through the list branch so non-finite
        # elements (possibly nested) get tagged too
        return {'__array__': _encode_value(value.tolist())}
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return {'__float__': 'nan'}
        return {'__float__': 'inf' if value > 0 else '-inf'}
    if isinstance(value, dict):
        encoded = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(
                    'dict keys must be str for the JSON manifest, '
                    'got {!r}'.format(k))
            if k in _RESERVED_TAGS:
                raise ValueError(
                    'dict key {!r} collides with a reserved manifest '
                    'type tag'.format(k))
            encoded[k] = _encode_value(v)
        return encoded
    if isinstance(value, (list, tuple)):
        return [_encode_value(v) for v in value]
    return value  # str, int, finite float, bool


def _encode_field(kind, field, value):
    """`_encode_value` with save-time diagnostics: encoding errors are
    re-raised naming the item kind and field so the offending
    attribute is obvious from the traceback."""
    try:
        return _encode_value(value)
    except (TypeError, ValueError) as e:
        raise type(e)('while encoding {} field {!r}: {}'.format(
            kind, field, e)) from e


def _decode_value(value):
    if isinstance(value, dict):
        if '__uuid__' in value:
            return uuid.UUID(value['__uuid__'])
        if '__datetime__' in value:
            return datetime.datetime.fromisoformat(value['__datetime__'])
        if '__array__' in value:
            return np.array(_decode_value(value['__array__']))
        if '__float__' in value:
            return float(value['__float__'])
        return {k: _decode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_value(v) for v in value]
    return value


def _settings_to_dict(settings):
    if settings is None:
        return None
    return {k: _encode_value(v) for k, v in vars(settings).items()}


def _settings_from_dict(d):
    """Rebuild MySettings without re-running __init__ — the stored
    dict is the exact post-validation state, so re-validating could
    change it (and __init__ probes sound devices)."""
    if d is None:
        return None
    settings = options.MySettings.__new__(options.MySettings)
    for k, v in d.items():
        setattr(settings, k, _decode_value(v))
    return settings


def _collect_item_extra(entry, kind):
    """Every manifest key in one item ``entry`` this reader does not
    consume, as raw manifest JSON ready to re-emit.

    Returns a dict of unknown TOP-LEVEL entry keys (see `_ITEM_KEYS`),
    plus — under the key ``'meta'``, which can never collide with a
    top-level extra because ``meta`` is itself consumed — a dict of the
    ``meta`` keys unknown for this ``kind`` (`_META_FIELDS` +
    `_OPTIONAL_META`). Empty dict when there is nothing unknown, which
    is what keeps `_ITEM_EXTRA_ATTR` absent on ordinary files.

    Values are NOT decoded: they are re-emitted exactly as they were
    read, so a writer that owns them (the browser app) sees its own
    bytes back regardless of what they mean.

    Args:
        entry (dict): one ``manifest['items']`` entry.
        kind (str): the entry's data kind, selecting the known-field
            sets to subtract.
    """
    extra = {k: v for k, v in entry.items() if k not in _ITEM_KEYS}
    known_meta = set(_META_FIELDS.get(kind, ()))
    known_meta.update(_OPTIONAL_META.get(kind, ()))
    meta = entry.get('meta') or {}
    meta_extra = {k: v for k, v in meta.items() if k not in known_meta}
    if meta_extra:
        extra['meta'] = meta_extra
    return extra


def _apply_item_extra(item, entry):
    """Merge `item`'s stashed manifest extras into its ``entry``.

    The item's own known fields ALWAYS win: a top-level extra is only
    written when the key is absent from ``entry``, and a ``meta`` extra
    only when absent from ``entry['meta']`` (which by then already
    holds every `_META_FIELDS` key, present-but-None included). A
    non-dict stash — nothing writes one, but pickles are forgiving — is
    ignored rather than raising.

    Args:
        item: the data object being written, possibly carrying
            `_ITEM_EXTRA_ATTR`.
        entry (dict): the manifest entry built for it, mutated in place.
    """
    extra = getattr(item, _ITEM_EXTRA_ATTR, None)
    if not isinstance(extra, dict):
        return
    for key, value in extra.items():
        if key == 'meta':
            if isinstance(value, dict):
                for meta_key, meta_value in value.items():
                    entry['meta'].setdefault(meta_key, meta_value)
        elif key not in entry:
            entry[key] = value


def manifest_ids(data):
    """The ``unique_id`` of every item in in-memory ``.dvma`` bytes.

    Reads ``manifest.json`` ONLY — no ``.npy`` member is decompressed —
    so this is cheap enough to run on a whole session document on the
    calling thread. Ids come back as ``str`` whether the manifest tags
    them (``{"__uuid__": "..."}``, what `save` writes) or stores a plain
    string (what a hand-built or browser-authored manifest may carry).
    Only `TimeData` currently carries a ``unique_id`` — derived items
    reference their source through ``id_link`` instead — so in practice
    this is the set of captures a document contains.

    Deliberately total: anything unreadable (not a zip, no manifest,
    invalid JSON, unexpected shapes) yields an EMPTY set rather than
    raising, because the callers
    (:meth:`pydvma.journal.SessionJournal.add_capture` /
    :meth:`~pydvma.journal.SessionJournal.set_doc`) use it only to
    decide whether a pending capture is already inside a posted
    document, and must degrade to the conservative answer rather than
    fail a write.

    Args:
        data (bytes-like): ``.dvma`` container bytes.

    Returns:
        ids (set): the ``unique_id`` strings found, possibly empty.
    """
    ids = set()
    try:
        with zipfile.ZipFile(io.BytesIO(data), 'r') as zf:
            manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        items = manifest.get('items') or []
        for entry in items:
            meta = (entry or {}).get('meta') or {}
            value = meta.get('unique_id')
            if isinstance(value, dict):
                value = value.get('__uuid__')
            if isinstance(value, str) and value:
                ids.add(value)
    except Exception:
        return set()
    return ids


def _write_array(zf, member, arr):
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    zf.writestr(member, buf.getvalue())


def _read_array(zf, member):
    return np.load(io.BytesIO(zf.read(member)), allow_pickle=False)


def _write_dataset(zf, dataset):
    """Write every item in `dataset` plus `manifest.json` into the
    already-open `zf`. The one writer shared by `save` and
    `save_bytes` — the manifest schema and member layout are defined
    here, once (see module docstring)."""
    manifest = {
        'format': FORMAT_NAME,
        'format_version': FORMAT_VERSION,
        'pydvma_version': datastructure.VERSION,
        'storage': 'npy',
        'items': [],
    }
    data_lists = [dataset.time_data_list, dataset.freq_data_list,
                  dataset.cross_spec_data_list, dataset.tf_data_list,
                  dataset.modal_data_list, dataset.sono_data_list,
                  dataset.meta_data_list]
    index = 0
    for data_list in data_lists:
        for item in data_list:
            kind = item.__class__.__name__
            entry = {'kind': kind, 'arrays': {}, 'meta': {}}
            for field in _ARRAY_FIELDS[kind]:
                # Default None: an object unpickled from a legacy
                # file predates any array field added since it was
                # written (e.g. TfData.bla_sigma_n), and must still
                # save — absent is written exactly like None.
                arr = getattr(item, field, None)
                if arr is None:      # e.g. TfData.tf_coherence
                    continue
                if kind == 'ModalData' and len(arr) == 0:
                    continue         # fresh ModalData has M == []
                member = 'arrays/{:04d}_{}.npy'.format(index, field)
                _write_array(zf, member, arr)
                entry['arrays'][field] = member
            for field in _META_FIELDS[kind]:
                entry['meta'][field] = _encode_field(
                    kind, field, getattr(item, field, None))
            for field in _OPTIONAL_META.get(kind, ()):
                if hasattr(item, field):
                    entry['meta'][field] = _encode_field(
                        kind, field, getattr(item, field))
            try:
                entry['settings'] = _settings_to_dict(
                    getattr(item, 'settings', None))
            except (TypeError, ValueError) as e:
                raise type(e)(
                    'while encoding {} field {!r}: {}'.format(
                        kind, 'settings', e)) from e
            # Re-emit whatever `load` stashed but did not consume (the
            # app's `ui` block, ModalData's meta extras) — see the
            # module docstring's lossless-round-trip paragraph.
            _apply_item_extra(item, entry)
            manifest['items'].append(entry)
            index += 1
    zf.writestr('manifest.json',
                json.dumps(manifest, indent=1, allow_nan=False))


def save(dataset, filename):
    """Save a DataSet to `filename` in .dvma container format (v2).

    Writes a zip archive with a JSON manifest and pickle-free .npy
    members (see module docstring for the schema). Unlike the legacy
    format this is safe to share and open: loading executes no code.

    The manifest's ``pydvma_version`` is always the version doing the
    writing (`datastructure.VERSION`), not the version recorded on
    `dataset` — resaving an old file records the new writer.

    The write is atomic: data goes to a temporary file in the same
    directory, which is renamed over `filename` only on success, so a
    crash or encoding error mid-save cannot destroy a pre-existing
    good file. The manifest is strict JSON (``allow_nan=False``); any
    non-finite float that escapes `_encode_value`'s tagging raises at
    save time rather than corrupting the file.
    """
    tmp = tempfile.NamedTemporaryFile(
        delete=False, suffix='.dvma.tmp',
        dir=os.path.dirname(os.path.abspath(filename)))
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            _write_dataset(zf, dataset)
        tmp.close()
        os.replace(tmp.name, filename)
    except BaseException:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise
    return filename


def save_bytes(dataset):
    """Serialise a DataSet to ``.dvma`` container bytes in memory.

    The same archive `save` writes (same manifest, same members, one
    shared writer, see `_write_dataset`) without touching the
    filesystem — for the session journal and
    :meth:`pydvma.session.Session.push`, which move documents over
    sockets rather than into files.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        _write_dataset(zf, dataset)
    return buf.getvalue()


def load(filename, _source_name=None):
    """Load a .dvma container file and return the DataSet.

    Objects are rebuilt attribute-by-attribute (no constructors run),
    so timestamps, unique ids and settings come back exactly as
    saved. Only manifest-known fields become attributes — the schema,
    not the class layout, defines the file. Manifest keys unknown to
    this reader are not turned into attributes, but they ARE kept: each
    item's unconsumed keys are stashed verbatim on the object as
    `_ITEM_EXTRA_ATTR` and re-emitted by the next `save`, so a Python
    round-trip never destroys browser-authored document state (see the
    module docstring).

    Raises ValueError if the file's ``format_version`` is newer than
    this reader supports, or if an item's ``kind`` is unknown —
    rather than silently misreading a file written by a newer pydvma.
    These messages are user-facing (e.g. the crash-recovery offer that
    lets a user re-open a previous pydvma version's spill file), so
    they name the offending source; the private ``_source_name``
    overrides what's named in place of ``filename`` when the caller
    has a friendlier name to give (`load_bytes` uses it since its
    `filename` is a bare `BytesIO` with no useful repr).
    """
    source = filename if _source_name is None else _source_name
    with zipfile.ZipFile(filename, 'r') as zf:
        try:
            manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        except KeyError:
            raise ValueError(
                '{!r} is a zip file but not a dvma-dataset '
                '(no manifest.json inside)'.format(source)) from None
        if manifest.get('format') != FORMAT_NAME:
            raise ValueError(
                '{!r} is a zip file but not a dvma-dataset '
                '(manifest format={!r})'.format(source,
                                                 manifest.get('format')))
        file_version = manifest.get('format_version')
        if not isinstance(file_version, int) or file_version > FORMAT_VERSION:
            raise ValueError(
                '{!r} uses dvma-dataset format_version {!r}, but this '
                'pydvma reads up to {}. Update pydvma to open this file '
                '(pip install --upgrade pydvma).'.format(
                    source, file_version, FORMAT_VERSION))
        dataset = datastructure.DataSet()
        for entry in manifest['items']:
            kind = entry['kind']
            cls = _KIND_CLASSES.get(kind)
            if cls is None:
                raise ValueError(
                    '{!r} contains unknown data kind {!r} — written by '
                    'a newer pydvma?'.format(source, kind))
            item = cls.__new__(cls)
            arrays = entry.get('arrays', {})
            meta = entry.get('meta', {})
            for field in _ARRAY_FIELDS[kind]:
                member = arrays.get(field)
                setattr(item, field, _read_array(zf, member)
                        if member is not None else None)
            if kind == 'ModalData' and 'M' not in arrays:
                item.M = []                  # matches fresh ModalData
            for field in _META_FIELDS[kind]:
                setattr(item, field, _decode_value(meta.get(field)))
            for field in _OPTIONAL_META.get(kind, ()):
                # restore only when present: absent must stay absent so
                # downstream hasattr() guards keep working
                if meta.get(field) is not None:
                    setattr(item, field, _decode_value(meta[field]))
            item.settings = _settings_from_dict(entry.get('settings'))
            extra = _collect_item_extra(entry, kind)
            if extra:
                setattr(item, _ITEM_EXTRA_ATTR, extra)
            if kind == 'ModalData' and 'M' in arrays:
                # rebuild the derived per-mode summary arrays
                from . import modal
                fn, zn, an, pn, rk, rm = modal.unpack_matrix(item.M)
                item.fn, item.zn, item.an, item.pn = fn, zn, an, pn
            dataset.add_to_dataset(item)
        dataset.pydvma_version = manifest.get('pydvma_version',
                                               dataset.pydvma_version)
    return dataset


def load_bytes(data):
    """Load a DataSet from in-memory ``.dvma`` container bytes.

    The bytes-side twin of `load` (which see for the schema/version
    rules — both share the reader; `zipfile.ZipFile` accepts a
    file-like object exactly like a filename, so this just wraps
    `data` in a `io.BytesIO` and delegates). Any of `load`'s
    user-facing error messages name the source as
    ``'<in-memory .dvma bytes>'`` rather than a `BytesIO` object's
    unhelpful repr.
    """
    return load(io.BytesIO(data), _source_name='<in-memory .dvma bytes>')
