#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from typing import Any

_CONFIG_FILE = "linktools.yml"

if not os.path.isfile(_CONFIG_FILE):
    raise RuntimeError("missing Linktools config: %s" % os.path.abspath(_CONFIG_FILE))

from setuptools import build_meta as _build_meta
from setuptools.build_meta import *  # noqa


def get_requires_for_build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    return _build_meta.get_requires_for_build_editable(*args, **kwargs)


def prepare_metadata_for_build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    return _build_meta.prepare_metadata_for_build_editable(*args, **kwargs)


def build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    return _build_meta.build_editable(*args, **kwargs)
