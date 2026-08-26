#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
from typing import Any, Dict, List

import setuptools
from setuptools import build_meta as _build_meta
from setuptools.build_meta import *  # noqa
from setuptools.dist import Distribution

from ._build import finalize_distribution_options, get_setup_context

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_CONFIG_FILE = "linktools.yml"
_PYPROJECT_FILE = "pyproject.toml"
_PATCH_ATTR = "_linktools_setup_finalize_patched"

if not os.path.isfile(_CONFIG_FILE):
    raise RuntimeError("missing Linktools config: %s" % os.path.abspath(_CONFIG_FILE))


def _install_distribution_hook() -> None:
    if getattr(Distribution, _PATCH_ATTR, False):
        return

    original = Distribution.finalize_options

    def finalize_options(dist: Distribution) -> None:
        original(dist)
        finalize_distribution_options(dist)

    Distribution.finalize_options = finalize_options
    setattr(Distribution, _PATCH_ATTR, True)


def _project_attrs() -> Dict[str, Any]:
    try:
        with open(_PYPROJECT_FILE, "rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("invalid pyproject.toml: %s" % exc) from exc

    project = data.get("project")
    if not isinstance(project, dict):
        raise RuntimeError("pyproject.toml must define [project]")

    name = project.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError("pyproject.toml project.name must be a non-empty string")

    names: List[str] = []
    emails: List[str] = []
    authors = project.get("authors", [])
    if authors is not None:
        if not isinstance(authors, list):
            raise RuntimeError("pyproject.toml project.authors must be a list")
        for author in authors:
            if not isinstance(author, dict):
                raise RuntimeError("pyproject.toml project.authors items must be mappings")
            author_name = author.get("name")
            author_email = author.get("email")
            if author_name is not None:
                if not isinstance(author_name, str) or not author_name:
                    raise RuntimeError("pyproject.toml author.name must be a non-empty string")
                names.append(author_name)
            if author_email is not None:
                if not isinstance(author_email, str) or not author_email:
                    raise RuntimeError("pyproject.toml author.email must be a non-empty string")
                emails.append(author_email)

    return {
        "name": name,
        "author": ", ".join(names),
        "author_email": ", ".join(emails),
    }


def _convert_files() -> None:
    dist = Distribution(_project_attrs())
    get_setup_context(dist).convert_files()


_install_distribution_hook()


def build_wheel(*args: Any, **kwargs: Any) -> Any:
    _convert_files()
    return _build_meta.build_wheel(*args, **kwargs)


def build_sdist(*args: Any, **kwargs: Any) -> Any:
    _convert_files()
    return _build_meta.build_sdist(*args, **kwargs)


def get_requires_for_build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    return _build_meta.get_requires_for_build_editable(*args, **kwargs)


def prepare_metadata_for_build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    return _build_meta.prepare_metadata_for_build_editable(*args, **kwargs)


def build_editable(*args: Any, **kwargs: Any) -> Any:
    os.environ["SETUP_EDITABLE_MODE"] = "true"
    _convert_files()
    return _build_meta.build_editable(*args, **kwargs)
