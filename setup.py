#!/usr/bin/env python

import ast
import re
from setuptools import setup

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('alpaca_backtrader_api/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')).group(1)))

with open('README.md') as readme_file:
    README = readme_file.read()

setup(
    name='alpaca-backtrader-api',
    version=version,
    description='Alpaca API within backtrader',
    long_description=README,
    long_description_content_type='text/markdown',
    author='Alpaca',
    author_email='oss@alpaca.markets',
    url='https://github.com/alpacahq/alpaca-backtrader-api',
    keywords='financial,timeseries,api,trade,backtrader',
    packages=['alpaca_backtrader_api'],
    install_requires=[
        'backtrader',
        'alpaca-trade-api',
    ],
    tests_require=[
        'pytest',
        'pytest-cov',
        'requests-mock',
        'coverage>=4.4.1',
        'mock>=1.0.1',
        'flake8',
    ],
    setup_requires=['pytest-runner', 'flake8'],
)
