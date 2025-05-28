#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os

from setuptools import setup

if __name__ == '__main__':
    version = os.environ.get("VERSION", None)
    if not version:
        version = "0.0.1"
    if version.startswith("v"):
        version = version[len("v"):]

    setup(version=version)
