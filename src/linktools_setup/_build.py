#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import List

import setuptools
from setuptools.command.build_py import build_py as _build_py

from .setup import SetupConfig, SetupContext

_CONFIG_FILE = "linktools.yml"
_CONTEXT_ATTR = "_linktools_setup_context"


def _get_context(dist: setuptools.Distribution) -> SetupContext:
    context = getattr(dist, _CONTEXT_ATTR, None)
    if context is None:
        context = SetupContext(dist)
        setattr(dist, _CONTEXT_ATTR, context)
    return context


class _LinktoolsBuildPy(_build_py):

    def run(self) -> None:
        _get_context(self.distribution).convert_files()
        super().run()

    def get_source_files(self) -> List[str]:
        files = list(super().get_source_files())
        config = SetupConfig()
        files.append(_CONFIG_FILE)
        files.extend(
            item["source"]
            for item in config.get("convert", default=[])
        )
        return list(dict.fromkeys(files))


def finalize_distribution_options(dist: setuptools.Distribution) -> None:
    if not Path(_CONFIG_FILE).is_file():
        return

    context = SetupContext(dist)
    setattr(dist, _CONTEXT_ATTR, context)

    cmdclass = getattr(dist, "cmdclass", None)
    if cmdclass is None:
        cmdclass = {}
        dist.cmdclass = cmdclass
    cmdclass["build_py"] = _LinktoolsBuildPy


finalize_distribution_options.order = 100
