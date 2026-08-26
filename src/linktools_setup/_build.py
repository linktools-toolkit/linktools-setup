#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path
from typing import List, Tuple

import setuptools
from setuptools.command.build_py import build_py as _build_py

from .setup import SetupConfig, SetupContext

_CONFIG_FILE = "linktools.yml"
_CONTEXT_ATTR = "_linktools_setup_context"


def get_setup_context(dist: setuptools.Distribution) -> SetupContext:
    context = getattr(dist, _CONTEXT_ATTR, None)
    if context is None:
        context = SetupContext(dist)
        setattr(dist, _CONTEXT_ATTR, context)
    return context


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


class _LinktoolsBuildPy(_build_py):

    def get_source_files(self) -> List[str]:
        config = SetupConfig()
        convert = config.get("convert", default=[])
        generated = {_normalize(item["dest"]) for item in convert}
        files = [
            path
            for path in super().get_source_files()
            if _normalize(path) not in generated
        ]
        files.append(_CONFIG_FILE)
        files.extend(item["source"] for item in convert)
        return list(dict.fromkeys(files))

    def get_data_files_without_manifest(self) -> List[Tuple[str, str, str, List[str]]]:
        config = SetupConfig()
        generated = [Path(item["dest"]).resolve() for item in config.get("convert", default=[])]
        result = []
        for package, src_dir, build_dir, filenames in super().get_data_files_without_manifest():
            source_root = Path(src_dir).resolve()
            excluded = set()
            for path in generated:
                try:
                    excluded.add(_normalize(str(path.relative_to(source_root))))
                except ValueError:
                    continue
            result.append((
                package,
                src_dir,
                build_dir,
                [filename for filename in filenames if _normalize(filename) not in excluded],
            ))
        return result


def finalize_distribution_options(dist: setuptools.Distribution) -> None:
    if not Path(_CONFIG_FILE).is_file():
        return

    get_setup_context(dist)

    cmdclass = getattr(dist, "cmdclass", None)
    if cmdclass is None:
        cmdclass = {}
        dist.cmdclass = cmdclass
    cmdclass["build_py"] = _LinktoolsBuildPy
