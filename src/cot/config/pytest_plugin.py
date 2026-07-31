"""Proof of concept: cot.config fragments inside pytest.

**This plugin monkeypatches pytest.** It adds two methods that pytest does not
have -- `Parser.add_config` and `Config.get_config` -- so a plugin author can
declare a whole nested ConfigPart in `pytest_addoption` and read it back as a
typed object in `pytest_configure` or anywhere else that holds a `Config`.

    def pytest_addoption(parser):
        parser.add_config(LoggingConfig)

    def pytest_configure(config):
        log = config.get_config(LoggingConfig)
        log.cli.level        # typed, cascaded, provenance-tracked

The patch only *adds* attributes; nothing pytest already does is replaced. No
option, ini key, hook or behaviour of pytest's changes by loading this. The
intended end state is the reverse of this arrangement -- pytest using the
library directly -- and this module exists to find out what that would need.

It is **auto-enabled** through a `pytest11` entry point, so installing the
package is enough:

    def pytest_addoption(parser):
        parser.add_config(MyConfig)     # just works

Turn it off with `-p no:cot_config`.

Note that `pytest_plugins = [...]` inside a conftest is *not* a working
activation route: that conftest's own `pytest_addoption` runs before its plugin
list is processed. The entry point avoids the problem entirely by loading
before any conftest.

The entry point covers conftests and other entry-point plugins, but **not**
plugins loaded with `-p`: those load *before* entry points, so `add_config` is
not there yet. Any plugin that might load that early must import and call
`install()` itself -- it is idempotent, and `example_plugin` shows the pattern:

    from cot.config.pytest_plugin import install

    install()

The same applies to entry-point plugins, whose load order across distributions
is not defined.

## Division of labour

pytest keeps argument parsing. This module maps in both directions:

- **declare**: each leaf field becomes a `parser.addoption` and/or a
  `parser.addini`, named by the same mapping every other source uses, so
  `cli.level` under `name_prefix="log"` is `--log-cli-level` and `log_cli_level`.
- **load**: values come back through `config.getoption` then `config.getini` --
  pytest's own `get_option_ini` precedence -- and are reassembled into the
  nested shape, where defaults and the `from_parent` cascade apply.

That split is the interesting part: pytest is good at parsing argv and reading
ini files, and has no notion of structure. This library supplies the structure.
"""

from __future__ import annotations

from argparse import ArgumentError
from typing import TYPE_CHECKING, Any, TypeVar

from ._bases import ConfigPart
from ._fields import FieldInfo, marker_of, unwrap_type
from ._manager import ConfigLifecycleError, ConfigManager
from ._names import FieldNames, cli_visible, named_leaf_fields, set_path
from ._origins import Origin
from ._sources import _element_type_of, _parse_value

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

_T = TypeVar("_T", bound=ConfigPart)

#: Attribute the manager is stashed under on the pytest Parser.
MANAGER_ATTR = "_cot_config_manager"

#: pytest's precedence for these values. They arrive already merged by pytest,
#: so the number only has to put this source above nothing else in particular.
PYTEST_PRECEDENCE = 25


def _help_of(field: FieldInfo) -> str:
    from ._annotations import HelpMarker

    marker = marker_of(field, HelpMarker)
    return marker.help if marker is not None else ""


def _short_of(field: FieldInfo) -> str | None:
    from ._annotations import ShortMarker

    marker = marker_of(field, ShortMarker)
    return marker.char if marker is not None else None


def _ini_type_of(field: FieldInfo) -> str:
    """Map a field type onto one of pytest's ini types.

    Anything that is not obviously a bool or a list is read as a string and
    converted by this library, which already knows how to parse a config value
    against an annotation.
    """
    actual = unwrap_type(field.annotation)
    if actual is bool:
        return "bool"
    if actual is list or getattr(actual, "__origin__", None) is list:
        return "linelist"
    return "string"


class PytestOptionSource:
    """A ConfigSource backed by pytest's own Parser and Config.

    Declaration goes out to the `Parser`; values come back from the `Config`
    once pytest has finished parsing. The two happen in different pytest
    phases, which is exactly why the manager separates declare from resolve.
    """

    def __init__(self, parser: Parser, *, precedence: int = PYTEST_PRECEDENCE) -> None:
        self._parser = parser
        self._config: Config | None = None
        self._precedence = precedence
        self._ini_names: set[str] = set()
        self._cli_names: set[str] = set()
        # (part_type, path) -> "cli" | "ini", filled in during load()
        self._provenance: dict[tuple[type[ConfigPart], tuple[str, ...]], str] = {}

    @property
    def precedence(self) -> int:
        return self._precedence

    def bind(self, config: Config) -> None:
        """Attach the Config that parsing produced."""
        self._config = config

    # -- declaration ------------------------------------------------------

    def declare(self, part_type: type[ConfigPart]) -> None:
        """Turn a ConfigPart's leaf fields into pytest options and ini keys."""
        group = self._parser.getgroup(_group_name(part_type))

        for field, names in named_leaf_fields(part_type):
            self._declare_ini(field, names)
            if cli_visible(field):
                self._declare_option(group, field, names)

    def _declare_ini(self, field: FieldInfo, names: FieldNames) -> None:
        if names.flat in self._ini_names:
            return
        self._ini_names.add(names.flat)

        if names.flat in getattr(self._parser, "_inidict", {}):
            # pytest, or another plugin, already declares this ini key. Adopt
            # it rather than clobbering the existing help and type -- during a
            # migration the same option is expected to exist on both sides.
            return

        # default=None so an unset ini key is distinguishable from one set to
        # a falsy value; this library's own declared default fills the gap.
        self._parser.addini(
            names.flat,
            help=_help_of(field),
            type=_ini_type_of(field),  # type: ignore[arg-type]
            default=None,
        )

    def _declare_option(self, group: Any, field: FieldInfo, names: FieldNames) -> None:
        if names.flat in self._cli_names:
            return
        self._cli_names.add(names.flat)

        options = [f"--{names.cli}"]
        short = _short_of(field)
        if short:
            options.insert(0, f"-{short}")

        actual = unwrap_type(field.annotation)
        attrs: dict[str, Any] = {
            "dest": names.flat,
            "help": _help_of(field),
            # Never let argparse supply the default: "not given on the command
            # line" has to stay distinguishable so the ini value can win.
            "default": None,
        }
        if actual is bool:
            attrs["action"] = "store_true"
        elif actual is list or getattr(actual, "__origin__", None) is list:
            attrs["action"] = "append"

        try:
            group.addoption(*options, **attrs)
        except ArgumentError as exc:
            # An option pytest or another plugin already owns. Raw argparse
            # says "conflicting option string" and names nothing useful, so
            # point at the field and the ways out.
            raise ConfigLifecycleError(
                f"Cannot declare {options[-1]} for field "
                f"{'.'.join(names.path)!r}: {exc}. "
                f"Rename it with named(...), suppress the option with no_cli, "
                f"or change the ConfigPart's name_prefix."
            ) from exc

    # -- loading ----------------------------------------------------------

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """Read values back, reassembling pytest's flat names into structure."""
        config = self._config
        if config is None:
            return {}

        result: dict[str, Any] = {}
        for field, names in named_leaf_fields(part_type):
            value, kind = self._value_of(config, field, names)
            if value is None:
                continue
            self._provenance[(part_type, field.path)] = kind
            set_path(result, field.path, value)
        return result

    def _value_of(
        self, config: Config, field: FieldInfo, names: FieldNames
    ) -> tuple[Any, str]:
        """pytest's get_option_ini precedence: command line first, then ini.

        Values from either side arrive as strings unless pytest was told a
        type, so both go through this library's own conversion -- otherwise a
        `float` field holds "10" and comparisons blow up at use time.
        """
        if cli_visible(field):
            value = config.getoption(names.flat, default=None)
            if value is not None:
                return self._convert(value, field), "cli"

        if names.flat in self._ini_names:
            value = config.getini(names.flat)
            # pytest normalises unset list/string ini values to [] / "".
            if value not in (None, "", []):
                return self._convert(value, field), "ini"

        return None, ""

    def _convert(self, value: Any, field: FieldInfo) -> Any:
        """Parse strings against the field's annotation; pass anything else on."""
        if isinstance(value, str):
            return _parse_value(value, field.annotation)
        if isinstance(value, list):
            element = _element_type_of(unwrap_type(field.annotation))
            return [
                _parse_value(item, element) if isinstance(item, str) else item
                for item in value
            ]
        return value

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Say whether pytest took this value from argv or from an ini file."""
        kind = self._provenance.get((part_type, path))
        if kind is None:
            return None

        names = {f.path: n for f, n in named_leaf_fields(part_type)}.get(path)
        flat = names.flat if names is not None else ".".join(path)

        if kind == "cli":
            cli = names.cli if names is not None else flat.replace("_", "-")
            return Origin(kind="cli", location=f"--{cli}", precedence=self._precedence)

        location = flat
        inipath = getattr(self._config, "inipath", None)
        if inipath is not None:
            location = f"{inipath}[{flat}]"
        return Origin(kind="file", location=location, precedence=self._precedence)


def _group_name(part_type: type[ConfigPart]) -> str:
    """The pytest option group a ConfigPart's options are shown under."""
    from ._names import part_name_prefix, part_prefix

    return part_name_prefix(part_type) or part_prefix(part_type) or part_type.__name__


# -- the patch -------------------------------------------------------------


def manager_for_parser(parser: Parser) -> ConfigManager:
    """The ConfigManager attached to a Parser, created on first use."""
    manager: ConfigManager | None = getattr(parser, MANAGER_ATTR, None)
    if manager is None:
        manager = ConfigManager(sources=[PytestOptionSource(parser)])
        setattr(parser, MANAGER_ATTR, manager)
    return manager


def manager_for_config(config: Config) -> ConfigManager:
    """The ConfigManager for a Config, with its sources bound to it.

    Binding here rather than in a `pytest_configure` hook keeps this free of
    hook-ordering concerns: whoever asks first triggers it.
    """
    manager = manager_for_parser(config._parser)
    for source in manager.sources:
        if isinstance(source, PytestOptionSource):
            source.bind(config)
    return manager


def _parser_add_config(self: Parser, part_type: type[ConfigPart]) -> None:
    """`Parser.add_config` -- declare a ConfigPart's options with pytest."""
    manager_for_parser(self).declare(part_type)


def _config_get_config(self: Config, part_type: type[_T]) -> _T:
    """`Config.get_config` -- the built, typed ConfigPart instance."""
    return manager_for_config(self).get(part_type)


def _config_explain_config(self: Config, part_type: type[ConfigPart]) -> str:
    """`Config.explain_config` -- where each value came from."""
    return manager_for_config(self).explain(part_type)


def install() -> None:
    """Patch pytest. Idempotent."""
    from _pytest.config import Config as _Config
    from _pytest.config.argparsing import Parser as _Parser

    if getattr(_Parser, "add_config", None) is _parser_add_config:
        return

    _Parser.add_config = _parser_add_config  # type: ignore[attr-defined]
    _Config.get_config = _config_get_config  # type: ignore[attr-defined]
    _Config.explain_config = _config_explain_config  # type: ignore[attr-defined]


# Loading this module as a pytest plugin is the activation.
install()


__all__ = [
    "PytestOptionSource",
    "install",
    "manager_for_config",
    "manager_for_parser",
]
