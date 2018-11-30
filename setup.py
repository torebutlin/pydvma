# -*- coding: utf-8 -*-
"""
Created on Thu Sep  6 15:06:51 2018

@author: tb267
"""
from setuptools import setup, find_packages

requires = ['peakutils', 'numpy', 'scipy', 'pyqtgraph', 'pyaudio', 'matplotlib']

setup(
    name='pydvma',
    version='0.3.0',
    install_requires=requires,
    packages=['pydvma','labs'],
    license='BSD 3-Clause License',
    long_description=open('README.md').read(),
)