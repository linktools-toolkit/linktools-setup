#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import abc
import hashlib
import json
import logging
import os
import pkgutil
import re
from importlib.util import module_from_spec
from typing import Any, Optional

import setuptools
import yaml
from jinja2 import Template
from setuptools.config.pyprojecttoml import load_file

logger = logging.getLogger("linktools_setup")


class EntryPoint(abc.ABC):

    @abc.abstractmethod
    def as_script(self) -> str:
        pass


class ScriptEntryPoint(EntryPoint):

    def __init__(self, name: str, module: str, object: Optional[str], attr: Optional[str]):
        self.name = name
        self.module = module
        self.object = object
        self.attr = attr

    def as_script(self) -> str:
        name = self.name.replace('_', '-')
        value = self.module
        if self.object:
            value = f"{value}:{self.object}"
            if self.attr:
                value = f"{value}.{self.attr}"
        return f"{name} = {value}"


class SubScriptEntryPoint(ScriptEntryPoint):
    pass


class ModuleEntryPoint(EntryPoint):

    def __init__(self, name: str, module: str):
        self.name = name
        self.module = module

    def as_script(self) -> str:
        name = self.name.replace('_', '-')
        value = self.module
        return f"{name} = {value}"


class SetupConst:

    def __init__(self):
        self.module_command_key = "__command__"
        self.scripts_entrypoint = "linktools_scripts"
        self.updater_entrypoint = "linktools_updater"
        self.default_script_object = "command"
        self.default_script_attr = "main"


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
        self.const = SetupConst()
        self.config = SetupConfig()
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
        file = self.config.get("tool", "linktools", "dependencies", "file")
        if file:
            dist_install_requires = self.dist.install_requires = self.dist.metadata.install_requires = \
                getattr(self.dist.metadata, "install_requires", None) or []
            dist_extras_require = self.dist.extras_require = self.dist.metadata.extras_require = \
                getattr(self.dist.metadata, "extras_require", None) or {}

            install_requires, extras_require = [], {}
            with open(file, "rt", encoding="utf-8") as fd:
                data = yaml.safe_load(fd)
                # install_requires = dependencies + dev-dependencies
                install_requires.extend(data.get("dependencies", []))
                if self.develop:
                    install_requires.extend(data.get("dev-dependencies", []))
                if self.release:
                    install_requires.extend(data.get("release-dependencies", []))
                # extras_require = optional-dependencies
                extras_require.update(data.get("optional-dependencies", {}))
                if extras_require:
                    all_requires = extras_require.setdefault("all", [])
                    for requires in extras_require.values():
                        all_requires.extend(requires)

            dist_install_requires.extend(install_requires)
            dist_extras_require.update(extras_require)

    def _fill_entry_points(self):
        scripts = self.config.get("tool", "linktools", "scripts", "console")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("console_scripts", [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    console_scripts.append(entry_point.as_script())

        scripts = self.config.get("tool", "linktools", "scripts", "gui")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("gui_scripts", [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    console_scripts.append(entry_point.as_script())

        scripts = self.config.get("tool", "linktools", "scripts", "commands")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            console_scripts = dist_entry_points.setdefault("console_scripts", [])
            linktools_scripts = dist_entry_points.setdefault(self.const.scripts_entrypoint, [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    console_scripts.append(entry_point.as_script())
                if not isinstance(entry_point, SubScriptEntryPoint):
                    linktools_scripts.append(entry_point.as_script())

        scripts = self.config.get("tool", "linktools", "scripts", "update-command")
        if scripts:
            dist_entry_points = self.dist.entry_points = self.dist.metadata.entry_points = \
                getattr(self.dist.metadata, "entry_points", None) or {}
            linktools_updater = dist_entry_points.setdefault(self.const.updater_entrypoint, [])
            for entry_point in self._parse_scripts(scripts):
                linktools_updater.append(entry_point.as_script())

    def _parse_scripts(self, scripts):
        if not isinstance(scripts, (list, tuple, set)):
            scripts = [scripts]
        for script in scripts:
            yield from self._parse_script(script)

    def _parse_script(self, script):
        if "name" in script:
            yield ScriptEntryPoint(
                name=script.get("name"),
                module=script.get("module"),
                object=script.get("object", self.const.default_script_object),
                attr=script.get("object", self.const.default_script_attr)
            )
        elif "path" in script:
            module = script.get("module").rstrip(".")
            path = script.get("path")
            root_path = os.path.join(path, "__init__.py")
            if os.path.exists(root_path):
                m = hashlib.md5()
                m.update(root_path.encode())
                yield ModuleEntryPoint(
                    name=f"module-{m.hexdigest()}",
                    module=module,
                )
                yield from self._iter_module_scripts(
                    path=script.get("path"),
                    prefix=f"{module}.",
                    object=script.get("object", self.const.default_script_object),
                    attr=script.get("object", self.const.default_script_attr),
                )

    def _iter_module_scripts(self, path, prefix, object, attr, parents=None):
        for module_info in pkgutil.iter_modules([path]):
            if module_info.ispkg:
                spec = module_info.module_finder.find_spec(module_info.name)
                module = module_from_spec(spec)
                spec.loader.exec_module(module)
                items = list(parents or [])
                items.append(getattr(module, self.const.module_command_key, module_info.name))
                yield from self._iter_module_scripts(
                    path=os.path.join(path, module_info.name),
                    prefix=f"{prefix}{module_info.name}.",
                    object=object,
                    attr=attr,
                    parents=items,
                )
            elif not module_info.name.startswith("_"):
                yield SubScriptEntryPoint(
                    name=f"{'-'.join(parents)}-{module_info.name}" if parents else module_info.name,
                    module=f"{prefix}{module_info.name}",
                    object=object,
                    attr=attr,
                )

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


def finalize_distribution_options(dist: setuptools.Distribution) -> None:
    context = SetupContext(dist)
    context.convert_files()


if __name__ == '__main__':
    context = SetupContext(setuptools.Distribution())

    # scripts = [{
    #     "path": os.path.expanduser("~/Projects/linktools/src/linktools/cli/commands"),
    #     "module": "linktools.cli.commands",
    # }]
    scripts = {"name": "ct-cntr", "module": "linktools_cntr.__main__"}
    # print([ep.as_script() for ep in context._parse_scripts(scripts)])
    # print([ep.as_script() for ep in context._parse_scripts(scripts) if isinstance(ep, ScriptEntryPoint)])
    print([ep.as_script() for ep in context._parse_scripts(scripts) if not isinstance(ep, SubScriptEntryPoint)])
