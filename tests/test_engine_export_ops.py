# -*- coding: utf-8 -*-
"""The web app's Export CSV / Export Matlab: ``engine.dvma_to_csv`` and
``engine.dvma_to_mat`` turn the document Save builds (``.dvma`` bytes) into
the files Python's ``export_to_csv`` / ``export_to_matlab`` write, so the two
can never drift apart and both load back exactly."""
import io

import scipy.io

from pydvma import _exchange, container, engine
from _rich_dataset import assert_same_dataset, rich_dataset


def test_dvma_to_csv_is_pythons_export():
    ds = rich_dataset()
    out = engine.dvma_to_csv(container.save_bytes(ds))
    text = out['csv'].decode('utf-8')
    assert text.startswith('# pydvma dataset (pydvma-csv 1)\n')
    assert_same_dataset(_exchange.dataset_from_csv_text(text, 'x.csv'), ds)


def test_dvma_to_mat_is_pythons_export():
    ds = rich_dataset()
    out = engine.dvma_to_mat(container.save_bytes(ds))
    d = scipy.io.loadmat(io.BytesIO(bytes(out['mat'])), simplify_cells=True)
    assert d['pydvma_format'] == 'pydvma-mat 1'
    assert_same_dataset(_exchange.dataset_from_mat_dict(d, 'x.mat'), ds)


def test_an_empty_document_is_refused():
    import pytest
    from pydvma import datastructure
    empty = container.save_bytes(datastructure.DataSet())
    for op in (engine.dvma_to_csv, engine.dvma_to_mat):
        with pytest.raises(ValueError, match='nothing to export'):
            op(empty)
