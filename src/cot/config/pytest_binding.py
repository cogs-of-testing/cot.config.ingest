"""The pytest binding: two typed functions, and nothing patched.

    from cot.config.pytest_binding import add_config, get_config

    def pytest_addoption(parser):
        add_config(parser, LoggingConfig)

    def pytest_configure(config):
        log = get_config(config, LoggingConfig)
        log.cli.level        # typed, cascaded, provenance-tracked

Nothing is auto-enabled and nothing is added to pytest's classes: a plugin
that does not import these functions is untouched (P1).

## Division of labour

pytest keeps argument parsing and ini reading. This module is the binder in
both directions:

- **declare**: ``add_config`` declares the root with a manager and binds its
  specs at once, translating each into ``parser.addoption`` and
  ``parser.addini`` calls. The translation is in :func:`_option_attrs` and
  :func:`_ini_type`, and it is the only place argparse's or pytest's
  vocabulary appears.
- **load**: two sources read the values back, ``getoption`` at the command
  line's rung and ``getini`` at the files' rung, and yield readings. The store,
  the cascade, conversion and provenance are the core's.
"""

from __future__ import annotations

import argparse
import weakref
from argparse import ArgumentError
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, get_args, get_origin

from _pytest.stash import StashKey

from ._bases import ConfigPart
from ._diagnostics import ConfigCollisionError
from ._fields import MISSING, strip_annotated, unwrap_type
from ._manager import ConfigManager
from ._precedence import Precedence
from ._specs import field_specs
from ._store import Reading

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

    from ._index import SpellingIndex
    from ._origins import OriginKind
    from ._specs import CliForm, FieldSpec
    from ._store import Dialect, Unmatched

_T = TypeVar("_T", bound=ConfigPart)

#: The manager each Parser's declarations went to, until a Config takes it.
_BY_PARSER: weakref.WeakKeyDictionary[Parser, ConfigManager] = (
    weakref.WeakKeyDictionary()
)

#: Where a Config keeps its manager once it has one.
_STASH_KEY = StashKey[ConfigManager]()

#: ini types whose values pytest hands back already typed.
_TYPED_INI = frozenset({"bool", "int", "float", "linelist", "paths"})


def _ini_type(spec: FieldSpec) -> str:
    """The ini type a spec's annotation asks pytest to parse values into.

    Anything that is not plainly one of pytest's types is read as a string and
    converted by the library, which knows the whole annotation.
    """
    declared = strip_annotated(unwrap_type(spec.annotation))
    if spec.repeatable:
        (element,) = get_args(declared) or (str,)
        return "paths" if element is Path else "linelist"
    if spec.values is not None or get_origin(declared) is not None:
        return "string"
    return {bool: "bool", int: "int", float: "float"}.get(declared, "string")


def _choice(value: Any) -> str:
    return str(getattr(value, "value", value))


def _option_attrs(spec: FieldSpec, form: CliForm) -> dict[str, Any]:
    """The library's vocabulary, translated into argparse's, for one form."""
    attrs: dict[str, Any] = {
        "dest": spec.flat,
        "help": spec.help,
        # Never let argparse supply the default: "not given on the command
        # line" has to stay distinguishable so the ini value can win.
        "default": None,
    }
    if form.contributes is not MISSING:
        attrs["action"] = "store_const"
        attrs["const"] = form.contributes
    elif spec.counts:
        attrs["action"] = "count"
    elif form.flag:
        attrs["action"] = "store_true"
    else:
        if spec.repeatable:
            attrs["action"] = "append"
        if spec.values is not None:
            attrs["choices"] = [_choice(value) for value in spec.values]
    return attrs


#: The argparse action each of _option_attrs's ``action`` values creates.
_ACTIONS = {
    None: argparse._StoreAction,
    "store_const": argparse._StoreConstAction,
    "count": argparse._CountAction,
    "store_true": argparse._StoreTrueAction,
    "append": argparse._AppendAction,
}


def _existing_action(parser: Parser, names: list[str]) -> argparse.Action | None:
    """The action that already owns one of ``names``, if any."""
    known = parser.optparser._option_string_actions
    for name in names:
        if name in known:
            return known[name]
    return None


def _compatible(
    action: argparse.Action, names: list[str], attrs: dict[str, Any]
) -> bool:
    """Whether reading ``action``'s dest gives what declaring ``attrs`` would."""
    return (
        set(names) <= set(action.option_strings)
        and type(action) is _ACTIONS.get(attrs.get("action"))
        and action.const == attrs.get("const")
        and action.nargs is None
    )


def _hashable(value: Any) -> Any:
    return tuple(value) if isinstance(value, list) else value


class _Host:
    """What both pytest-backed sources share: the Parser, then the Config."""

    def __init__(self, parser: Parser) -> None:
        self.parser = parser
        self.config: Config | None = None
        self.options: dict[str, tuple[str, Any]] = {}
        """flat name -> the dest pytest stores it under, and the value that
        means "not given": ``None`` for options declared here, the existing
        default for adopted ones."""
        self.ini_keys: dict[str, str] = {}
        """file key -> the ini type pytest parses it as."""


class PytestOptionSource:
    """What pytest parsed from the command line; the binder for both halves."""

    dialect: Dialect = "string"
    kind: OriginKind = "cli"

    def __init__(self, host: _Host, *, precedence: int = Precedence.CLI) -> None:
        self.host = host
        self.precedence = precedence

    @property
    def base_dir(self) -> Path | None:
        config = self.host.config
        return None if config is None else config.invocation_params.dir

    def bind(self, specs: Iterable[FieldSpec], *, adopt: bool = False) -> None:
        """Register every spec's forms and file key with pytest. Idempotent.

        With ``adopt``, a compatible option pytest or another plugin already
        declares is read instead of declared again (P9).
        """
        for spec in specs:
            self._bind_ini(spec)
            if spec.cli:
                self._bind_options(spec, adopt=adopt)

    def _bind_ini(self, spec: FieldSpec) -> None:
        key = spec.file_key
        if key is None or key in self.host.ini_keys:
            return
        existing = getattr(self.host.parser, "_inidict", {}).get(key)
        if existing is not None:
            # pytest, or another plugin, already declares this ini key. Adopt
            # it rather than clobbering the existing help and type: during a
            # migration the same option is expected to exist on both sides.
            self.host.ini_keys[key] = existing[1] or "string"
            return
        ini_type = _ini_type(spec)
        self.host.ini_keys[key] = ini_type
        # default=None so an unset key is distinguishable from one set to a
        # falsy value; the library's own declared default fills the gap.
        self.host.parser.addini(
            key,
            help=spec.help,
            type=ini_type,  # type: ignore[arg-type]
            default=None,
            aliases=spec.aliases,
        )

    def _bind_options(self, spec: FieldSpec, *, adopt: bool) -> None:
        if spec.flat in self.host.options:
            return
        group = self.host.parser.getgroup(spec.group)
        adopted: set[tuple[str, Any]] = set()
        for form in spec.cli:
            names = [name for name in (form.short, form.long) if name is not None]
            attrs = _option_attrs(spec, form)
            existing = _existing_action(self.host.parser, names) if adopt else None
            if existing is not None and _compatible(existing, names, attrs):
                adopted.add((existing.dest, _hashable(existing.default)))
                continue
            try:
                group.addoption(*names, **attrs)
            except ArgumentError as exc:
                raise ConfigCollisionError(
                    f"{'.'.join(spec.path)} cannot be declared as {names[-1]}: "
                    f"pytest or another plugin already owns it ({exc}). "
                    f"Give it a named(...) override, no_cli, or a different "
                    f"name_prefix"
                    + (
                        "; the existing option is not compatible, so it was "
                        "not adopted."
                        if adopt
                        else ", or adopt it with add_config(..., adopt=True)."
                    )
                ) from exc
        if not adopted:
            self.host.options[spec.flat] = (spec.flat, None)
        elif len(adopted) == 1 and len(spec.cli) == 1:
            ((dest, default),) = adopted
            self.host.options[spec.flat] = (dest, default)
        else:
            raise ConfigCollisionError(
                f"{'.'.join(spec.path)} can only adopt an option when it has "
                f"one command-line form; it has {len(spec.cli)}."
            )

    def read(self, index: SpellingIndex) -> Iterator[Reading | Unmatched]:
        config = self.host.config
        if config is None:
            return
        for root in index.roots:
            for spec in index.specs(root):
                if spec.flat not in self.host.options:
                    continue
                dest, not_given = self.host.options[spec.flat]
                value = config.getoption(dest, default=None)
                if value is None or (spec.counts and value == 0):
                    continue
                if not_given is not None and _hashable(value) == not_given:
                    continue
                first = spec.cli[0]
                location = first.long or first.short or spec.flat
                yield Reading(root=root, path=spec.path, raw=value, location=location)


class PytestIniSource:
    """What pytest read from its ini file, at the files' rung.

    ``getini`` returns typed values for the ini types pytest parses, and text
    for ``string``, so each reading carries its own dialect.
    """

    dialect: Dialect = "string"
    kind: OriginKind = "file"

    def __init__(self, host: _Host, *, precedence: int = Precedence.FILE) -> None:
        self.host = host
        self.precedence = precedence

    @property
    def base_dir(self) -> Path | None:
        config = self.host.config
        inipath = None if config is None else config.inipath
        return None if inipath is None else inipath.parent

    def read(self, index: SpellingIndex) -> Iterator[Reading | Unmatched]:
        config = self.host.config
        if config is None:
            return
        for root in index.roots:
            for spec in index.specs(root):
                key = spec.file_key
                if key is None or key not in self.host.ini_keys:
                    continue
                value = config.getini(key)
                # pytest normalises unset list and string values to [] and "".
                if value in (None, "", []):
                    continue
                if isinstance(value, list) and value and isinstance(value[0], Path):
                    value = [str(item) for item in value]
                dialect: Dialect = (
                    "typed" if self.host.ini_keys[key] in _TYPED_INI else "string"
                )
                location = f"{config.inipath}[{key}]" if config.inipath else key
                yield Reading(
                    root=root,
                    path=spec.path,
                    raw=value,
                    location=location,
                    dialect=dialect,
                )


def _manager_for_parser(parser: Parser) -> ConfigManager:
    manager = _BY_PARSER.get(parser)
    if manager is None:
        host = _Host(parser)
        manager = ConfigManager(
            sources=[PytestIniSource(host), PytestOptionSource(host)]
        )
        _BY_PARSER[parser] = manager
    return manager


def _binder(manager: ConfigManager) -> PytestOptionSource:
    for source in manager.sources:
        if isinstance(source, PytestOptionSource):
            return source
    raise LookupError("this manager has no pytest source")  # pragma: no cover


def add_config(parser: Parser, root: type[ConfigPart], *, adopt: bool = False) -> None:
    """Declare ``root`` and register its options and ini keys with pytest.

    Call it from ``pytest_addoption``. The specs are bound at once rather than
    at resolve, because pytest parses between ``pytest_addoption`` and the
    first read, and an option registered later would never be seen.

    ``adopt=True`` is for a plugin that replaces the one owning its options:
    a command-line option that already exists with the same action is read
    rather than declared, and an incompatible one still raises (P9).
    """
    manager = _manager_for_parser(parser)
    manager.declare(root)
    _binder(manager).bind(field_specs(root), adopt=adopt)


def manager_for(config: Config) -> ConfigManager:
    """The manager this run's declarations went to, kept in ``config.stash``."""
    manager = config.stash.get(_STASH_KEY, None)
    if manager is None:
        manager = _manager_for_parser(config._parser)
        _binder(manager).host.config = config
        config.stash[_STASH_KEY] = manager
    return manager


def get_config(config: Config, root: type[_T]) -> _T:
    """The built, typed fragment. Resolves on first use."""
    return manager_for(config).get(root)


def explain_config(config: Config, root: type[ConfigPart]) -> str:
    """Every field's value, where it came from, and what it beat."""
    return manager_for(config).explain(root)


__all__ = [
    "PytestIniSource",
    "PytestOptionSource",
    "add_config",
    "explain_config",
    "get_config",
    "manager_for",
]
