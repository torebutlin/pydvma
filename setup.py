# -*- coding: utf-8 -*-
"""
Created on Thu Sep  6 15:06:51 2018

@author: tb267
"""
from setuptools import setup, find_packages

requires = ['peakutils', 'numpy', 'scipy', 'pyqtgraph==0.11', 'matplotlib', 'seaborn']

setup(
    name='pydvma',
    version='0.8.5', # keep in sync with datastructure.py
    install_requires=requires,
    packages=['pydvma'],
    package_data={'': ['icon.png']},
    license='BSD 3-Clause License',
    long_description=open('README.md').read(),
    author='Tore Butlin',
    author_email='tb267@cam.ac.uk',
    url='https://github.com/torebutlin/pydvma'
)