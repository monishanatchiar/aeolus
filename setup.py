#!/usr/bin/env python
"""Package build and install script."""
import os
import sys

from setuptools import find_packages, setup

import versioneer


# Publish the library to PyPI.
if "publish" in sys.argv[-1]:
    os.system("python setup.py sdist upload")
    sys.exit()


def get_readme():
    """Load README for display on PyPI."""
    with open("README.md") as f:
        return f.read()


CMDCLASS = versioneer.get_cmdclass()


setup(
    name="aeolus",
    version=versioneer.get_version(),
    cmdclass=CMDCLASS,
    description="Python library for object-oriented analysis of atmospheric model output",
    long_description=get_readme(),
    author="Denis Sergeev",
    author_email="dennis.sergeev@gmail.com",
    url="https://github.com/exoclim/aeolus",
    package_dir={"aeolus": "aeolus"},
    packages=find_packages(),
    zip_safe=False,
    setup_requires=["numpy>=1.7"],
    install_requires=["numpy>=1.7", "pytest>=3.3", "pandas>=0.20", "scitools-iris>=2.0.*"],
    classifiers=[
        "Intended Audience :: Science/Research",
        "Natural Language :: English",
        "License :: OSI Approved :: LGPL License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Topic :: Scientific/Engineering :: Atmospheric Science",
    ],
)