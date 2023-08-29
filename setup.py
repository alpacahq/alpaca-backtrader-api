#!/usr/bin/env python

import ast
import os
import re
from setuptools import setup

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('alpaca_backtrader_api/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')).group(1)))

with open('README.md') as readme_file:
    README = readme_file.read()

with open(os.path.join("requirements", "requirements.txt")) as reqs:
    REQUIREMENTS = reqs.readlines()

with open(os.path.join("requirements", "requirements_test.txt")) as reqs:
    REQUIREMENTS_TEST = reqs.readlines()

setup(
    name='alpaca-backtrader-api',
    version=version,
    description='Alpaca API within backtrader',
    long_description=README,
    long_description_content_type='text/markdown',
    author='Alpaca',
    author_email='oss@alpaca.markets',
    url='https://github.com/alpacahq/alpaca-backtrader-api',
    classifiers=[
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',

        # Operating Systems on which it runs
        'Operating System :: OS Independent',
    ],
    keywords='financial,timeseries,api,trade,backtrader',
    packages=['alpaca_backtrader_api'],
    install_requires=REQUIREMENTS,
    tests_require=REQUIREMENTS_TEST,
    setup_requires=['pytest-runner', 'flake8'],
)
