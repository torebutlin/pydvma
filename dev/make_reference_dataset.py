# -*- coding: utf-8 -*-
"""Generate tests/data/reference_dataset_v140.npy — a legacy pickle
save from pydvma 1.4.0, checked in so the legacy reader path is
pinned forever. Run once from the repo root:

    python dev/make_reference_dataset.py

Regenerating it later (with newer code) would defeat the point; only
rerun if you deliberately need a new reference epoch.
"""
import os
import numpy as np
import pydvma as dvma

assert dvma.datastructure.VERSION == '1.4.0', 'reference must be written by 1.4.0'

# create_test_impulse_data returns a populated DataSet
data = dvma.create_test_impulse_data(noise_level=0)
td = data.time_data_list[0]
td.test_name = 'reference impulse'
td.units = ['N', 'm/s']
data.calculate_fft_set()
data.calculate_tf_set(ch_in=0)
data.calculate_cross_spectrum_matrix_set(window='hann')
data.calculate_sono_set()

out = os.path.join('tests', 'data', 'reference_dataset_v140.npy')
os.makedirs(os.path.dirname(out), exist_ok=True)
data.save_data(filename=out)
print('wrote', out)
