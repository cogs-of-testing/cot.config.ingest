"""Proof of concept: cot.config fragments inside pytest.

**This plugin monkeypatches pytest.** It adds three methods that pytest does not
have -- `Parser.add_config`, `Config.get_config` and `Config.explain_config` --
so a plugin author can declare a whole nested ConfigPart in `pytest_addoption`
and read it back as a typed object in `pytest_configure` or anywhere else that
holds a `Config`.

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

Which also means the patch applies to *every* environment this package is
installed into, including ones that acquired it as a transitive dependency and
never asked for it. That is a deliberate trade for a proof of concept and is
not how a stable release should behave; it will change. Turn it off with
`-p no:cot_config`.

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
from ._diagnostics import ConfigLifecycleError
from ._fields import MISSING, unwrap_type
from ._manager import ConfigManager
from ._precedence import Precedence
from ._store import Reading

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

    from ._index import SpellingIndex
    from ._origins import OriginKind
    from ._specs import CliForm, FieldSpec
    from ._store import Dialect, Unmatched

_T = TypeVar("_T", bound=ConfigPart)

#: Attribute the manager is stashed under on the pytest Parser.
MANAGER_ATTR = "_cot_config_manager"


def _ini_type_of(spec: FieldSpec) -> str:
    """Map a spec onto one of pytest's ini types.

    Anything that is not obviously a bool or a list is read as a string and
    converted by this library, which already knows how to parse a config value
    against an annotation.
    """
    if spec.repeatable:
        return "linelist"
    if unwrap_type(spec.annotation) is bool:
        return "bool"
    return "string"


def _argparse_attrs(spec: FieldSpec, form: CliForm) -> dict[str, Any]:
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
    elif spec.repeatable:
        attrs["action"] = "append"
    return attrs


class _PytestHost:
    """What both pytest-backed sources share: the Parser, then the Config."""

    def __init__(self, parser: Parser) -> None:
        self.parser = parser
        self.config: Config | None = None
        self.options: set[str] = set()
        self.ini_keys: set[str] = set()


class PytestOptionSource:
    """The values pytest parsed from the command line, and the binder.

    Declaration goes out to the `Parser` in the library's vocabulary translated
    to argparse's; values come back from the `Config` once pytest has finished
    parsing. The two happen in different pytest phases, which is exactly why
    the manager separates declare from resolve.
    """

    dialect: Dialect = "string"
    kind: OriginKind = "cli"

    def __init__(
        self, host: _PytestHost | Parser, *, precedence: int = Precedence.CLI
    ) -> None:
        self._host = host if isinstance(host, _PytestHost) else _PytestHost(host)
        self.precedence = precedence

    @property
    def host(self) -> _PytestHost:
        return self._host

    @property
    def base_dir(self) -> Path | None:
        config = self._host.config
        return None if config is None else config.invocation_params.dir

    def bind(self, specs: Iterable[FieldSpec]) -> None:
        """Register every spec's forms and file key with pytest. Idempotent."""
        for spec in specs:
            self._bind_ini(spec)
            if spec.cli:
                self._bind_options(spec)

    def _bind_ini(self, spec: FieldSpec) -> None:
        key = spec.file_key
        if key is None or key in self._host.ini_keys:
            return
        self._host.ini_keys.add(key)
        if key in getattr(self._host.parser, "_inidict", {}):
            # pytest, or another plugin, already declares this ini key. Adopt
            # it rather than clobbering the existing help and type -- during a
            # migration the same option is expected to exist on both sides.
            return
        # default=None so an unset ini key is distinguishable from one set to
        # a falsy value; this library's own declared default fills the gap.
        self._host.parser.addini(
            key,
            help=spec.help,
            type=_ini_type_of(spec),  # type: ignore[arg-type]
            default=None,
        )

    def _bind_options(self, spec: FieldSpec) -> None:
        if spec.flat in self._host.options:
            return
        self._host.options.add(spec.flat)
        group = self._host.parser.getgroup(spec.group)
        for form in spec.cli:
            names = [name for name in (form.short, form.long) if name is not None]
            try:
                group.addoption(*names, **_argparse_attrs(spec, form))
            except ArgumentError as exc:
                # An option pytest or another plugin already owns. Raw argparse
                # says "conflicting option string" and names nothing useful, so
                # point at the field and the ways out.
                raise ConfigLifecycleError(
                    f"Cannot declare {names[-1]} for field "
                    f"{'.'.join(spec.path)!r}: {exc}. "
                    f"Rename it with named(...), suppress the option with no_cli, "
                    f"or change the ConfigPart's name_prefix."
                ) from exc

    def read(self, index: SpellingIndex) -> Iterator[Reading | Unmatched]:
        config = self._host.config
        if config is None:
            return
        for root in index.roots:
            for spec in index.specs(root):
                if spec.flat not in self._host.options:
                    continue
                value = config.getoption(spec.flat, default=None)
                if value is None:
                    continue
                if spec.counts and value == 0:
                    continue
                location = next(
                    (form.long or form.short for form in spec.cli), spec.flat
                )
                yield Reading(
                    root=root, path=spec.path, raw=value, location=str(location)
                )


class PytestIniSource:
    """The values pytest read from its ini file, one rung below the CLI."""

    dialect: Dialect = "string"
    kind: OriginKind = "file"

    def __init__(self, host: _PytestHost, *, precedence: int = Precedence.FILE) -> None:
        self._host = host
        self.precedence = precedence

    @property
    def base_dir(self) -> Path | None:
        config = self._host.config
        inipath = None if config is None else config.inipath
        return None if inipath is None else inipath.parent

    def read(self, index: SpellingIndex) -> Iterator[Reading | Unmatched]:
        config = self._host.config
        if config is None:
            return
        inipath = config.inipath
        for root in index.roots:
            for spec in index.specs(root):
                key = spec.file_key
                if key is None or key not in self._host.ini_keys:
                    continue
                value = config.getini(key)
                # pytest normalises unset list/string ini values to [] / "".
                if value in (None, "", []):
                    continue
                location = f"{inipath}[{key}]" if inipath is not None else key
                yield Reading(root=root, path=spec.path, raw=value, location=location)


# -- the patch -------------------------------------------------------------


def manager_for_parser(parser: Parser) -> ConfigManager:
    """The ConfigManager attached to a Parser, created on first use."""
    manager: ConfigManager | None = getattr(parser, MANAGER_ATTR, None)
    if manager is None:
        host = _PytestHost(parser)
        manager = ConfigManager(
            sources=[PytestIniSource(host), PytestOptionSource(host)]
        )
        setattr(parser, MANAGER_ATTR, manager)
    return manager


def _binder(manager: ConfigManager) -> PytestOptionSource:
    for source in manager.sources:
        if isinstance(source, PytestOptionSource):
            return source
    raise LookupError("this manager has no pytest source")


def manager_for_config(config: Config) -> ConfigManager:
    """The ConfigManager for a Config, with its sources bound to it.

    Binding here rather than in a `pytest_configure` hook keeps this free of
    hook-ordering concerns: whoever asks first triggers it.
    """
    manager = manager_for_parser(config._parser)
    _binder(manager).host.config = config
    return manager


def _parser_add_config(self: Parser, part_type: type[ConfigPart]) -> None:
    """`Parser.add_config` -- declare a ConfigPart's options with pytest.

    Bound at once rather than at resolve: pytest parses between
    `pytest_addoption` and the first read, so an option registered later would
    never be seen.
    """
    from ._specs import field_specs

    manager = manager_for_parser(self)
    manager.declare(part_type)
    _binder(manager).bind(field_specs(part_type))


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
    "PytestIniSource",
    "PytestOptionSource",
    "install",
    "manager_for_config",
    "manager_for_parser",
]
