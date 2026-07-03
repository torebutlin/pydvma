# -*- coding: utf-8 -*-
"""Generate webui/tests/fixtures/impulse.dvma — a small real container
written by pydvma itself, used as ground truth by the webui codec tests.
Run from the repo root: python dev/make_webui_fixture.py"""
import os
import pydvma as dvma
import pydvma.file

data = dvma.create_test_impulse_data(noise_level=0)
data.time_data_list[0].test_name = 'webui fixture'
data.time_data_list[0].units = ['N', 'm/s']
data.calculate_fft_set()
data.calculate_tf_set(ch_in=0)
out = os.path.join('webui', 'tests', 'fixtures', 'impulse.dvma')
# DataSet.save_data() doesn't expose overwrite_without_prompt, so call
# the file-layer function directly to keep regeneration non-interactive.
pydvma.file.save_data(data, filename=out, overwrite_without_prompt=True)
print('wrote', out)
