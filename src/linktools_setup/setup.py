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
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import setuptools
import yaml
from jinja2 import Template

logger = logging.getLogger("linktools_setup")

_CONFIG_FILE = "linktools.yml"
_ROOT_FIELDS = {
    "name",
    "version",
    "dependencies",
    "dev-dependencies",
    "release-dependencies",
    "optional-dependencies",
    "scripts",
    "convert",
}
_SCRIPT_FIELDS = {"capability", "console", "gui", "commands"}
_SCRIPT_ITEM_FIELDS = {"name", "path", "module", "object", "attr"}
_CONVERT_FIELDS = {"type", "source", "dest"}
_CONVERT_TYPES = {"jinja2", "yml2json"}


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> Dict[Any, Any]:
    mapping: Dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicated = key in mapping
        except TypeError as exc:
            raise ValueError("mapping keys must be scalar values") from exc
        if duplicated:
            raise ValueError("duplicate YAML key: %s" % key)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class EntryPoint(abc.ABC):

    @abc.abstractmethod
    def as_script(self) -> str:
        pass


class ScriptEntryPoint(EntryPoint):

    def __init__(
        self,
        name: str,
        module: str,
        object: Optional[str],
        attr: Optional[str],
    ):
        self.name = name
        self.module = module
        self.object = object
        self.attr = attr

    def as_script(self) -> str:
        name = self.name.replace("_", "-")
        value = self.module
        if self.object:
            value = "%s:%s" % (value, self.object)
            if self.attr:
                value = "%s.%s" % (value, self.attr)
        return "%s = %s" % (name, value)


class SubScriptEntryPoint(ScriptEntryPoint):
    pass


class ModuleEntryPoint(EntryPoint):

    def __init__(self, name: str, module: str):
        self.name = name
        self.module = module

    def as_script(self) -> str:
        name = self.name.replace("_", "-")
        return "%s = %s" % (name, self.module)


class SetupConst:

    def __init__(self):
        self.module_command_key = "__command__"
        self.capability_entrypoint = "linktools_capability"
        self.scripts_entrypoint = "linktools_scripts"
        self.default_script_object = "command"
        self.default_script_attr = "main"


class SetupConfig:

    def __init__(self, root_path: Optional[Path] = None):
        self.root_path = (root_path or Path.cwd()).resolve()
        self.path = self.root_path / _CONFIG_FILE
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = yaml.load(file, Loader=_UniqueKeyLoader)
        except FileNotFoundError as exc:
            raise ValueError("missing Linktools config: %s" % self.path) from exc
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ValueError("invalid Linktools config %s: %s" % (self.path, exc)) from exc

        config = self._require_mapping(data, "config")
        self._reject_unknown(config, _ROOT_FIELDS, "config")

        version = config.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("config.version must be a non-empty string")
        version = version.strip()
        if version.startswith("v"):
            raise ValueError("config.version must not start with 'v'")
        config["version"] = version

        name = config.get("name")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ValueError("config.name must be a non-empty string")
        if isinstance(name, str):
            config["name"] = name.strip()

        for key in ("dependencies", "dev-dependencies", "release-dependencies"):
            config[key] = self._require_string_list(config.get(key, []), "config.%s" % key)

        optional = self._require_mapping(
            config.get("optional-dependencies", {}),
            "config.optional-dependencies",
        )
        normalized_optional: Dict[str, List[str]] = {}
        for extra, requirements in optional.items():
            if not isinstance(extra, str) or not extra:
                raise ValueError("config.optional-dependencies keys must be non-empty strings")
            normalized_optional[extra] = self._require_string_list(
                requirements,
                "config.optional-dependencies.%s" % extra,
            )
        config["optional-dependencies"] = normalized_optional

        config["scripts"] = self._validate_scripts(config.get("scripts", {}))
        config["convert"] = self._validate_convert(config.get("convert", []))
        return config

    @staticmethod
    def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("%s must be a mapping" % label)
        if not all(isinstance(key, str) for key in value):
            raise ValueError("%s field names must be strings" % label)
        return dict(value)

    @staticmethod
    def _reject_unknown(value: Dict[str, Any], allowed: set, label: str) -> None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError("%s has unknown field(s): %s" % (label, ", ".join(unknown)))

    @staticmethod
    def _require_string_list(value: Any, label: str) -> List[str]:
        if not isinstance(value, list):
            raise ValueError("%s must be a list of strings" % label)
        result: List[str] = []
        for item in value:
            if not isinstance(item, str) or not item:
                raise ValueError("%s must be a list of non-empty strings" % label)
            result.append(item)
        return result

    @staticmethod
    def _require_optional_string(value: Any, label: str) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError("%s must be a non-empty string or null" % label)
        return value

    def _resolve_path(self, value: Any, label: str) -> Path:
        if not isinstance(value, str) or not value:
            raise ValueError("%s must be a non-empty relative path" % label)
        if os.path.isabs(value):
            raise ValueError("%s must be relative: %s" % (label, value))
        path = (self.root_path / value).resolve()
        self._require_inside_root(path, label)
        return path

    def _resolve_source(self, value: Any, label: str, directory: bool = False) -> str:
        path = self._resolve_path(value, label)
        if directory:
            if path.exists() and not path.is_dir():
                raise ValueError("%s must be a directory: %s" % (label, value))
        elif not path.is_file():
            raise ValueError("%s file does not exist: %s" % (label, value))
        return value

    def _resolve_dest(self, value: Any, label: str) -> str:
        self._resolve_path(value, label)
        return value

    def _require_inside_root(self, path: Path, label: str) -> None:
        try:
            inside = os.path.commonpath((str(self.root_path), str(path))) == str(self.root_path)
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("%s escapes project root: %s" % (label, path))

    def _validate_scripts(self, value: Any) -> Dict[str, Any]:
        scripts = self._require_mapping(value, "config.scripts")
        self._reject_unknown(scripts, _SCRIPT_FIELDS, "config.scripts")

        capability = scripts.get("capability")
        if capability is not None:
            if not isinstance(capability, str) or not capability:
                raise ValueError("config.scripts.capability must be a non-empty string")

        for group in ("console", "gui", "commands"):
            if group not in scripts:
                continue
            raw_items = scripts[group]
            items = raw_items if isinstance(raw_items, list) else [raw_items]
            if not items:
                raise ValueError("config.scripts.%s must not be empty" % group)
            normalized = []
            for index, raw_item in enumerate(items):
                label = "config.scripts.%s[%d]" % (group, index)
                item = self._require_mapping(raw_item, label)
                self._reject_unknown(item, _SCRIPT_ITEM_FIELDS, label)
                has_name = "name" in item
                has_path = "path" in item
                if has_name == has_path:
                    raise ValueError("%s must define exactly one of name or path" % label)

                module = item.get("module")
                if not isinstance(module, str) or not module:
                    raise ValueError("%s.module must be a non-empty string" % label)

                if has_name:
                    name = item.get("name")
                    if not isinstance(name, str) or not name:
                        raise ValueError("%s.name must be a non-empty string" % label)
                else:
                    item["path"] = self._resolve_source(
                        item.get("path"),
                        "%s.path" % label,
                        directory=True,
                    )

                if "object" in item:
                    item["object"] = self._require_optional_string(
                        item.get("object"),
                        "%s.object" % label,
                    )
                if "attr" in item:
                    item["attr"] = self._require_optional_string(
                        item.get("attr"),
                        "%s.attr" % label,
                    )
                normalized.append(item)
            scripts[group] = normalized if isinstance(raw_items, list) else normalized[0]
        return scripts

    def _validate_convert(self, value: Any) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            raise ValueError("config.convert must be a list")
        result: List[Dict[str, str]] = []
        for index, raw_item in enumerate(value):
            label = "config.convert[%d]" % index
            item = self._require_mapping(raw_item, label)
            self._reject_unknown(item, _CONVERT_FIELDS, label)
            convert_type = item.get("type")
            if convert_type not in _CONVERT_TYPES:
                raise ValueError("%s.type must be one of: %s" % (
                    label,
                    ", ".join(sorted(_CONVERT_TYPES)),
                ))
            source = self._resolve_source(item.get("source"), "%s.source" % label)
            dest = self._resolve_dest(item.get("dest"), "%s.dest" % label)
            result.append({
                "type": convert_type,
                "source": source,
                "dest": dest,
            })
        return result

    def get(self, *keys: str, default: Any = None) -> Any:
        value: Any = self._config
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
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

    def _fill_version(self) -> str:
        version = self.dist.metadata.version
        if not version:
            version = self.config.get("version")
            if not self.release:
                items = []
                for item in version.split("."):
                    find = re.findall(r"^\d+", item)
                    if find:
                        items.append(int(find[0]))
                if not items:
                    raise ValueError("config.version has no numeric version components")
                version = ".".join(map(str, items))
                version = "%s.post100.dev0" % version
            self.dist.metadata.version = version
        return version

    def _fill_dependencies(self) -> None:
        dist_install_requires = self.dist.install_requires = self.dist.metadata.install_requires = \
            getattr(self.dist.metadata, "install_requires", None) or []
        dist_extras_require = self.dist.extras_require = self.dist.metadata.extras_require = \
            getattr(self.dist.metadata, "extras_require", None) or {}

        install_requires: List[str] = []
        install_requires.extend(self.config.get("dependencies", default=[]))
        if self.develop:
            install_requires.extend(self.config.get("dev-dependencies", default=[]))
        if self.release:
            install_requires.extend(self.config.get("release-dependencies", default=[]))

        extras_require = {
            name: list(requirements)
            for name, requirements in self.config.get(
                "optional-dependencies",
                default={},
            ).items()
        }
        if extras_require:
            all_requires = extras_require.setdefault("all", [])
            for name, requirements in extras_require.items():
                if name != "all":
                    all_requires.extend(requirements)

        dist_install_requires.extend(install_requires)
        dist_extras_require.update(extras_require)

    def _entry_points(self) -> Dict[str, List[str]]:
        entry_points = getattr(self.dist.metadata, "entry_points", None) or {}
        self.dist.entry_points = self.dist.metadata.entry_points = entry_points
        return entry_points

    def _fill_entry_points(self) -> None:
        scripts = self.config.get("scripts", "console")
        if scripts:
            console_scripts = self._entry_points().setdefault("console_scripts", [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    console_scripts.append(entry_point.as_script())

        scripts = self.config.get("scripts", "gui")
        if scripts:
            gui_scripts = self._entry_points().setdefault("gui_scripts", [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    gui_scripts.append(entry_point.as_script())

        scripts = self.config.get("scripts", "commands")
        if scripts:
            entry_points = self._entry_points()
            console_scripts = entry_points.setdefault("console_scripts", [])
            linktools_scripts = entry_points.setdefault(self.const.scripts_entrypoint, [])
            for entry_point in self._parse_scripts(scripts):
                if isinstance(entry_point, ScriptEntryPoint):
                    console_scripts.append(entry_point.as_script())
                if not isinstance(entry_point, SubScriptEntryPoint):
                    linktools_scripts.append(entry_point.as_script())

        capability = self.config.get("scripts", "capability")
        if capability:
            linktools_module = self._entry_points().setdefault(
                self.const.capability_entrypoint,
                [],
            )
            linktools_module.append(ModuleEntryPoint(
                name="module-%s" % self.get_md5(capability),
                module=capability,
            ).as_script())

    def _parse_scripts(self, scripts: Any) -> Iterator[EntryPoint]:
        items = scripts if isinstance(scripts, list) else [scripts]
        for script in items:
            yield from self._parse_script(script)

    def _parse_script(self, script: Dict[str, Any]) -> Iterator[EntryPoint]:
        if "name" in script:
            yield ScriptEntryPoint(
                name=script["name"],
                module=script["module"],
                object=script.get("object", self.const.default_script_object),
                attr=script.get("attr", self.const.default_script_attr),
            )
            return

        module = script["module"].rstrip(".")
        path = str((self.config.root_path / script["path"]).resolve())
        yield ModuleEntryPoint(
            name="module-%s" % self.get_md5(script["path"]),
            module=module,
        )
        yield from self._iter_module_scripts(
            path=path,
            prefix="%s." % module,
            object=script.get("object", self.const.default_script_object),
            attr=script.get("attr", self.const.default_script_attr),
        )

    def _iter_module_scripts(
        self,
        path: str,
        prefix: str,
        object: Optional[str],
        attr: Optional[str],
        parents: Optional[Sequence[str]] = None,
    ) -> Iterator[EntryPoint]:
        for module_info in pkgutil.iter_modules([path]):
            if module_info.ispkg:
                spec = module_info.module_finder.find_spec(module_info.name)
                if spec is None or spec.loader is None:
                    raise ValueError("cannot load command package: %s" % module_info.name)
                module = module_from_spec(spec)
                spec.loader.exec_module(module)
                items = list(parents or [])
                items.append(getattr(module, self.const.module_command_key, module_info.name))
                yield from self._iter_module_scripts(
                    path=os.path.join(path, module_info.name),
                    prefix="%s%s." % (prefix, module_info.name),
                    object=object,
                    attr=attr,
                    parents=items,
                )
            elif not module_info.name.startswith("_"):
                yield SubScriptEntryPoint(
                    name="%s-%s" % ("-".join(parents), module_info.name)
                    if parents else module_info.name,
                    module="%s%s" % (prefix, module_info.name),
                    object=object,
                    attr=attr,
                )

    def convert_files(self) -> None:
        for item in self.config.get("convert", default=[]):
            source = self.config.root_path / item["source"]
            dest = self.config.root_path / item["dest"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if item["type"] == "jinja2":
                with source.open("r", encoding="utf-8") as fd_in:
                    rendered = Template(fd_in.read()).render(
                        metadata=self.dist.metadata,
                        **{key: value for key, value in vars(self).items() if not key.startswith("_")},
                    )
                dest.write_text(rendered, encoding="utf-8")
            elif item["type"] == "yml2json":
                with source.open("r", encoding="utf-8") as fd_in:
                    data = yaml.safe_load(fd_in)
                if not isinstance(data, dict):
                    raise ValueError("yml2json source must contain a mapping: %s" % item["source"])
                result = {}
                for key, value in data.items():
                    if not isinstance(key, str):
                        raise ValueError("yml2json source keys must be strings: %s" % item["source"])
                    if not key.startswith("$"):
                        result[key] = value
                with dest.open("w", encoding="utf-8") as fd_out:
                    json.dump(result, fd_out)

    @staticmethod
    def get_md5(data: Any) -> str:
        if isinstance(data, str):
            data = data.encode()
        if not isinstance(data, bytes):
            raise TypeError("data must be str or bytes")
        digest = hashlib.md5()
        digest.update(data)
        return digest.hexdigest()


def _finder_path(dirname: str, relative: str) -> str:
    normalized = os.path.normpath(relative)
    if dirname:
        return os.path.join(dirname, normalized)
    return normalized


def find_linktools_files(dirname: str) -> Iterable[str]:
    root = Path(dirname or ".")
    config_path = root / _CONFIG_FILE
    if not config_path.is_file():
        return []

    result = [_finder_path(dirname, _CONFIG_FILE)]
    try:
        with config_path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
        if not isinstance(data, dict):
            return result
        convert = data.get("convert", [])
        if not isinstance(convert, list):
            return result

        root_resolved = root.resolve()
        for item in convert:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if not isinstance(source, str) or not source or os.path.isabs(source):
                continue
            normalized = os.path.normpath(source)
            if normalized == os.pardir or normalized.startswith(os.pardir + os.sep):
                continue
            candidate = (root_resolved / normalized).resolve()
            try:
                inside = os.path.commonpath((str(root_resolved), str(candidate))) == str(root_resolved)
            except ValueError:
                inside = False
            if inside and candidate.is_file():
                result.append(_finder_path(dirname, normalized))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        logger.warning("cannot inspect %s for source files: %s", config_path, exc)
    return result


def finalize_distribution_options(dist: setuptools.Distribution) -> None:
    if not (Path.cwd() / _CONFIG_FILE).is_file():
        return
    context = SetupContext(dist)
    context.convert_files()


if __name__ == "__main__":
    context = SetupContext(setuptools.Distribution())
    scripts = {"name": "ct-cntr", "module": "linktools_cntr.__main__"}
    print([
        entry_point.as_script()
        for entry_point in context._parse_scripts(scripts)
        if not isinstance(entry_point, SubScriptEntryPoint)
    ])
