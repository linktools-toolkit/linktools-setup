#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import logging
import os
import pkgutil
import re
from typing import Any

import setuptools
import yaml
from jinja2 import Template
from setuptools.config.pyprojecttoml import load_file

logger = logging.getLogger("linktools_setup")


class SetupConfig:

    def __init__(self):
        self._config = load_file("pyproject.toml")

    def get(self, *keys: str, default=None) -> Any:
        missing = object()
        value = self._config
        try:
            for key in keys:
                value = value.get(key, missing)
                if value is missing:
                    return default
        except Exception as e:
            logger.warning(f"get {keys} failed: {e}")
            return default
        return value


class SetupContext:

    def __init__(self, dist: setuptools.Distribution):
        self.dist = dist
        self.config = SetupConfig()
        self.scripts_entrypoint = "linktools_scripts"
        self.updater_entrypoint = "linktools_updater"
        self.release = os.environ.get("RELEASE", "false").lower() in ("true", "1", "yes")
        self.develop = os.environ.get("SETUP_EDITABLE_MODE", "false").lower() in ("true", "1", "yes")
        self.version = self._fill_version()
        self._fill_dependencies()
        self._fill_entry_points()

    def _fill_version(self):
        version = self.dist.metadata.version
        if not version:
            version = os.environ.get("VERSION", None)
            if not version:
                file = self.config.get("tool", "linktools", "version", "file")
                if file:
                    path = os.path.abspath(file)
                    if os.path.isfile(path):
                        with open(path, encoding="utf-8") as fd:
                            version = fd.read().strip()
            if not version:
                version = "0.0.1"
            if version.startswith("v"):
                version = version[len("v"):]
            if not self.release:
                items = []
                for item in version.split("."):
                    find = re.findall(r"^\d+", item)
                    if find:
                        items.append(int(find[0]))
                version = ".".join(map(str, items))
                version = f"{version}.post100.dev0"
            self.dist.metadata.version = version
        return version

    def _fill_dependencies(self):
        deps = self.config.get("tool", "linktools", "dependencies", "file")
        if isinstance(deps, dict):
            dist_install_requires = self.dist.install_requires = self.dist.metadata.install_requires = \
                getattr(self.dist.metadata, "install_requires", None) or []
            dist_extras_require = self.dist.extras_require = self.dist.metadata.extras_require = \
                getattr(self.dist.metadata, "extras_require", None) or {}

            install_requires, extras_require = [], {}
            with open(deps.get("file"), "rt", encoding="utf-8") as fd:
                data = yaml.safe_load(fd)
                # install_requires = dependencies + dev-dependencies
                install_requires.extend(data.get("dependencies", []))
                install_requires.extend(
                    data.get("release-dependencies") if self.release else data.get("dev-dependencies"))
                # extras_require = optional-dependencies
                extras_require.update(data.get("optional-dependencies", {}))
                all_requires = []
                for requires in extras_require.values():
                    all_requires.extend(requires)
                extras_require["all"] = all_requires

            dist_install_requires.extend(install_requires)
            dist_extras_require.update(extras_require)

    def _fill_entry_points(self):
        scripts = self.config.get("tool", "linktools", "scripts", "console")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("console_scripts", [])
            for script in self._parse_scripts(scripts):
                console_scripts.append(script)

        scripts = self.config.get("tool", "linktools", "scripts", "gui")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("gui_scripts", [])
            for script in self._parse_scripts(scripts):
                console_scripts.append(script)

        scripts = self.config.get("tool", "linktools", "scripts", "commands")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("console_scripts", [])
            linktools_scripts = dist_entry_points.setdefault(self.scripts_entrypoint, [])
            for script in self._parse_scripts(scripts):
                console_scripts.append(script)
                linktools_scripts.append(script)

        scripts = self.config.get("tool", "linktools", "scripts", "update-command")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            linktools_updater = dist_entry_points.setdefault(self.updater_entrypoint, [])
            for script in self._parse_scripts(scripts):
                linktools_updater.append(script)

    @classmethod
    def _parse_scripts(cls, scripts):
        if not isinstance(scripts, (list, tuple, set)):
            scripts = [scripts]
        for script in scripts:
            yield from cls._parse_script(script)

    @classmethod
    def _parse_script(cls, script):
        if "name" in script:
            name = script.get("name")
            module = script.get("module")
            object = script.get("object", "command")
            attr = script.get("object", "main")
            yield f"{name.replace('_', '-')} = {module}:{object}.{attr}"
        if "path" in script:
            path = script.get("path")
            prefix = script.get("prefix")
            module = script.get("module")
            object = script.get("object", "command")
            attr = script.get("object", "main")
            for _, name, _ in pkgutil.iter_modules([path]):
                if not name.startswith("_"):
                    yield f"{prefix}-{name.replace('_', '-')} = {module}.{name}:{object}.{attr}"

    def convert_files(self):
        convert = self.config.get("tool", "linktools", "convert")
        if convert:
            for item in convert:
                type = item.get("type")
                source = item.get("source")
                dest = item.get("dest")
                if type == "jinja2":
                    with open(source, "rt", encoding="utf-8") as fd_in, open(dest, "wt", encoding="utf-8") as fd_out:
                        fd_out.write(Template(fd_in.read()).render(
                            metadata=self.dist.metadata,
                            **{k: v for k, v in vars(self).items() if k[0] not in "_"},
                        ))
                elif type == "yml2json":
                    with open(source, "rb") as fd_in, open(dest, "wt") as fd_out:
                        json.dump({
                            key: value
                            for key, value in yaml.safe_load(fd_in).items()
                            if key[0] not in ("$",)
                        }, fd_out)


def setup(dist: setuptools.Distribution) -> None:
    context = SetupContext(dist)
    context.convert_files()
