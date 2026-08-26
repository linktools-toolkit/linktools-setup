#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Any, Dict, List

import setuptools

try:
    import tomllib
except ImportError:
    import tomli as tomllib

from .setup import finalize_distribution_options as _finalize_distribution_options

_CONFIG_FILE = "linktools.yml"
_PROJECT_FILE = "pyproject.toml"


def _load_project() -> Dict[str, Any]:
    path = Path(_PROJECT_FILE)
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("invalid project config %s: %s" % (path.resolve(), exc)) from exc

    project = data.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml must define [project]")
    return project


def _fill_project_metadata(dist: setuptools.Distribution) -> None:
    project = _load_project()
    metadata = dist.metadata

    name = project.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("project.name must be a non-empty string")
    if not metadata.name:
        metadata.name = name

    authors = project.get("authors", [])
    if authors is None:
        authors = []
    if not isinstance(authors, list):
        raise ValueError("project.authors must be a list")

    names: List[str] = []
    emails: List[str] = []
    for index, author in enumerate(authors):
        if not isinstance(author, dict):
            raise ValueError("project.authors[%d] must be a mapping" % index)
        author_name = author.get("name")
        author_email = author.get("email")
        if author_name is not None:
            if not isinstance(author_name, str) or not author_name:
                raise ValueError("project.authors[%d].name must be a non-empty string" % index)
            names.append(author_name)
        if author_email is not None:
            if not isinstance(author_email, str) or not author_email:
                raise ValueError("project.authors[%d].email must be a non-empty string" % index)
            emails.append(author_email)

    if names and not metadata.author:
        metadata.author = ", ".join(names)
    if emails and not metadata.author_email:
        metadata.author_email = ", ".join(emails)


def finalize_distribution_options(dist: setuptools.Distribution) -> None:
    if not Path(_CONFIG_FILE).is_file():
        return
    _fill_project_metadata(dist)
    _finalize_distribution_options(dist)
