# -*- coding: utf-8 -*-
"""
Created on Thu Sep  6 15:06:51 2018

@author: tb267
"""
from setuptools import setup, find_packages

requires = ['peakutils', 'numpy', 'scipy', 'pyqtgraph', 'matplotlib', 'seaborn', 'sounddevice']
#requires = ['peakutils', 'numpy', 'scipy', 'pyqtgraph', 'matplotlib', 'seaborn', 'sounddevicem', 'qtpy', 'pyqt5', 'qdarktheme']

setup(
    name='pydvma',
    version='1.0.0', # keep in sync with datastructure.py
    install_requires=requires,
    packages=['pydvma'],
    package_data={'': ['icon.png']},
    license='BSD 3-Clause License',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Tore Butlin',
    author_email='tb267@cam.ac.uk',
    url='https://github.com/torebutlin/pydvma'
)