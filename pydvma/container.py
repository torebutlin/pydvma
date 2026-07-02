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
{"__array__": [...]}``; everything else is a plain JSON value.

Use `save` / `load`; `file.save_data` and `file.load_data` call them
for you (load sniffs the format from the file's magic bytes, so old
pickle ``.npy`` files keep working).
"""
import datetime
import io
import json
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
    'TfData':        ['freq_axis', 'tf_data', 'tf_coherence'],
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
                       'timestamp', 'timestring', 'id_link', 'flag_modal_TF'],
    'SonoData':      ['units', 'channel_cal_factors', 'test_name',
                       'timestamp', 'timestring', 'id_link'],
    'ModalData':     ['units', 'test_name', 'timestamp', 'timestring',
                       'id_link', 'channels'],
    'MetaData':      ['units', 'channel_cal_factors', 'tf_cal_factors',
                       'timestamp', 'timestring'],
}

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
    datetime / ndarray so decoding is lossless."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return {'__uuid__': str(value)}
    if isinstance(value, datetime.datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, np.ndarray):
        return {'__array__': value.tolist()}
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [_encode_value(v) for v in value]
    return value  # str, int, float, bool


def _decode_value(value):
    if isinstance(value, dict):
        if '__uuid__' in value:
            return uuid.UUID(value['__uuid__'])
        if '__datetime__' in value:
            return datetime.datetime.fromisoformat(value['__datetime__'])
        if '__array__' in value:
            return np.array(value['__array__'])
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


def _write_array(zf, member, arr):
    buf = io.BytesIO()
    np.save(buf, np.asarray(arr), allow_pickle=False)
    zf.writestr(member, buf.getvalue())


def _read_array(zf, member):
    return np.load(io.BytesIO(zf.read(member)), allow_pickle=False)


def save(dataset, filename):
    """Save a DataSet to `filename` in .dvma container format (v2).

    Writes a zip archive with a JSON manifest and pickle-free .npy
    members (see module docstring for the schema). Unlike the legacy
    format this is safe to share and open: loading executes no code.
    """
    manifest = {
        'format': FORMAT_NAME,
        'format_version': FORMAT_VERSION,
        'pydvma_version': getattr(dataset, 'pydvma_version',
                                   datastructure.VERSION),
        'storage': 'npy',
        'items': [],
    }
    data_lists = [dataset.time_data_list, dataset.freq_data_list,
                  dataset.cross_spec_data_list, dataset.tf_data_list,
                  dataset.modal_data_list, dataset.sono_data_list,
                  dataset.meta_data_list]
    with zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        index = 0
        for data_list in data_lists:
            for item in data_list:
                kind = item.__class__.__name__
                entry = {'kind': kind, 'arrays': {}, 'meta': {}}
                for field in _ARRAY_FIELDS[kind]:
                    arr = getattr(item, field)
                    if arr is None:          # e.g. TfData.tf_coherence
                        continue
                    if kind == 'ModalData' and len(arr) == 0:
                        continue             # fresh ModalData has M == []
                    member = 'arrays/{:04d}_{}.npy'.format(index, field)
                    _write_array(zf, member, arr)
                    entry['arrays'][field] = member
                for field in _META_FIELDS[kind]:
                    entry['meta'][field] = _encode_value(
                        getattr(item, field, None))
                entry['settings'] = _settings_to_dict(
                    getattr(item, 'settings', None))
                manifest['items'].append(entry)
                index += 1
        zf.writestr('manifest.json', json.dumps(manifest, indent=1))
    return filename


def load(filename):
    """Load a .dvma container file and return the DataSet.

    Objects are rebuilt attribute-by-attribute (no constructors run),
    so timestamps, unique ids and settings come back exactly as
    saved. Only manifest-known fields are restored — the schema, not
    the class layout, defines the file.
    """
    with zipfile.ZipFile(filename, 'r') as zf:
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        if manifest.get('format') != FORMAT_NAME:
            raise ValueError(
                '{!r} is a zip file but not a dvma-dataset '
                '(manifest format={!r})'.format(filename,
                                                 manifest.get('format')))
        dataset = datastructure.DataSet()
        for entry in manifest['items']:
            kind = entry['kind']
            cls = _KIND_CLASSES[kind]
            item = cls.__new__(cls)
            for field in _ARRAY_FIELDS[kind]:
                member = entry['arrays'].get(field)
                setattr(item, field, _read_array(zf, member)
                        if member is not None else None)
            if kind == 'ModalData' and 'M' not in entry['arrays']:
                item.M = []                  # matches fresh ModalData
            for field in _META_FIELDS[kind]:
                setattr(item, field, _decode_value(entry['meta'].get(field)))
            item.settings = _settings_from_dict(entry.get('settings'))
            if kind == 'ModalData' and 'M' in entry['arrays']:
                # rebuild the derived per-mode summary arrays
                from . import modal
                fn, zn, an, pn, rk, rm = modal.unpack_matrix(item.M)
                item.fn, item.zn, item.an, item.pn = fn, zn, an, pn
            dataset.add_to_dataset(item)
        dataset.pydvma_version = manifest.get('pydvma_version',
                                               dataset.pydvma_version)
    return dataset
