# -*- coding: utf-8 -*-
"""Tests for the .dvma container format (format v2) and the legacy
pickle reader. See dev/2026-07-01-web-ui-design.md, Stage 0.5."""
import pathlib

import numpy as np
import pytest

import pydvma as dvma

DATA_DIR = pathlib.Path(__file__).resolve().parent / 'data'
REFERENCE_V140 = DATA_DIR / 'reference_dataset_v140.npy'


def test_legacy_pickle_file_still_loads():
    # Contract: files saved by <=1.4.0 remain loadable forever.
    d = dvma.load_data(filename=str(REFERENCE_V140))
    assert d.pydvma_version == '1.4.0'
    assert len(d.time_data_list) == 1
    assert d.time_data_list[0].units == ['N', 'm/s']
    assert len(d.freq_data_list) == 1
    assert len(d.tf_data_list) == 1
    assert len(d.cross_spec_data_list) == 1
    assert len(d.sono_data_list) == 1
    assert np.isfinite(d.tf_data_list[0].tf_data).all()
