"""The sources, as they read: input in, readings out.

A source reads its own input, asks the index what each spelling it finds means,
and yields one :class:`Reading` per value it can place and one
:class:`Unmatched` per spelling it cannot. It supplies only what it has:
absence is expressed by yielding nothing for a path, never by a ``None``
reading, which is what lets the store tell "unset" from "set to nothing".

Two things follow. A source never needs a part type, because the index knows
every declared root, so one read of a file serves all of them. And unknown keys
are judged in one place with everything declared in view, so a root never warns
about another root's keys.
"""

from __future__ import annotations

import configparser
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ._diagnostics import ConfigUsageError
from ._parser import ArgumentParser
from ._precedence import Precedence
from ._store import Reading, Unmatched

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from ._index import SpellingIndex, SpellingTarget
    from ._origins import OriginKind
    from ._specs import FieldSpec
    from ._store import Dialect


@runtime_checkable
class ConfigSource(Protocol):
    """What every source is, from the manager's side."""

    @property
    def precedence(self) -> int: ...

    @property
    def dialect(self) -> Dialect: ...

    @property
    def kind(self) -> OriginKind: ...

    @property
    def base_dir(self) -> Path | None:
        """What a relative path in this source's values is relative to."""
        ...

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]: ...


@runtime_checkable
class BindingSource(ConfigSource, Protocol):
    """A source that must be told an option exists before it can parse one."""

    def bind(self, specs: Iterable[FieldSpec]) -> None: ...


def _readings_for(
    targets: Sequence[SpellingTarget], raw: Any, location: str
) -> Iterator[Reading]:
    """One reading per field the spelling resolved to.

    More than one when two roots adopted a spelling, which is the migration
    case: a plugin and its host declaring the same option during a transition.
    """
    for target in targets:
        yield Reading(root=target.root, path=target.path, raw=raw, location=location)


# --- files ------------------------------------------------------------------


def _place(
    index: SpellingIndex, chain: tuple[str, ...], raw: Any, location: str
) -> Iterator[Reading | Unmatched]:
    """Resolve one key in a file, spelled either of the two ways it may be.

    A file has exactly two spellings for a field: fully flat in the section, or
    fully nested with the bare name as key. Each is looked up as what it is;
    neither is derived from the other by splitting or joining, because field
    names contain underscores and `named()` can replace a leaf's flat name with
    one that corresponds to no path at all.
    """
    key = chain[-1]
    candidates: list[tuple[SpellingTarget, ...]] = []

    if len(chain) >= 2:
        candidates.append(index.nested(chain[0], chain[1:-1], key))
        if len(chain) == 2:
            candidates.append(index.file_key(chain[0], key))
    if len(chain) == 1:
        candidates.append(index.file_key(None, key))
    candidates.append(index.nested(None, chain[:-1], key))

    for targets in candidates:
        if targets:
            yield from _readings_for(targets, raw, f"{location}[{'.'.join(chain)}]")
            return

    yield Unmatched(spelling=".".join(chain), location=location)


def _walk(
    index: SpellingIndex,
    data: Mapping[str, Any],
    location: str,
    chain: tuple[str, ...] = (),
) -> Iterator[Reading | Unmatched]:
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _walk(index, value, location, (*chain, key))
        else:
            yield from _place(index, (*chain, key), value, location)


@dataclass
class TomlSource:
    """One TOML file. Values arrive with types, so they are checked."""

    path: Path
    precedence: int = Precedence.FILE
    dialect: Dialect = "typed"
    kind: OriginKind = "file"

    @property
    def base_dir(self) -> Path | None:
        return self.path.parent

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        if not self.path.exists():
            return
        with self.path.open("rb") as stream:
            data = tomllib.load(stream)
        yield from _walk(index, data, str(self.path))


@dataclass
class IniSource:
    """One INI file. Every value is text, so values are converted."""

    path: Path
    precedence: int = Precedence.FILE
    dialect: Dialect = "string"
    kind: OriginKind = "file"

    @property
    def base_dir(self) -> Path | None:
        return self.path.parent

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        if not self.path.exists():
            return
        parser = configparser.ConfigParser()
        parser.read(self.path, encoding="utf-8")
        for section in parser.sections():
            for key, value in parser.items(section):
                yield from _place(index, (section, key), value, str(self.path))


#: Which source reads which suffix. A new file format costs a row and a loader.
FILE_SOURCES: dict[str, type[TomlSource] | type[IniSource]] = {
    ".toml": TomlSource,
    ".ini": IniSource,
    ".cfg": IniSource,
}


def source_for_file(path: Path, *, precedence: int = Precedence.FILE) -> ConfigSource:
    """Build the source that reads ``path``, by suffix."""
    try:
        source_type = FILE_SOURCES[path.suffix]
    except KeyError:
        raise ConfigUsageError(
            f"{path} has no reader: the suffix {path.suffix!r} is not one of "
            f"{', '.join(sorted(FILE_SOURCES))}"
        ) from None
    return source_type(path, precedence=precedence)


@dataclass
class ConfigFileDiscoverySource:
    """Files found by searching upwards, read as one source at one rung.

    One source rather than one per file, so that a chain of discovered files
    needs no rung of its own: they are ordered here, by depth, with the file
    nearest the invocation directory last, so the nearest wins without the
    result ever depending on the order sources were added.
    """

    invocation_dir: Path
    filenames: Sequence[str] = ("pyproject.toml", "setup.cfg", "tox.ini")
    precedence: int = Precedence.FILE
    dialect: Dialect = "typed"
    kind: OriginKind = "file"
    base_dir: Path | None = None

    def discovered(self) -> list[Path]:
        """Every file found, furthest from the invocation directory first."""
        found: list[Path] = []
        for directory in [self.invocation_dir, *self.invocation_dir.parents]:
            for name in self.filenames:
                candidate = directory / name
                if candidate.exists():
                    found.append(candidate)
        found.reverse()
        return found

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        for path in self.discovered():
            yield from source_for_file(path).read(index)


# --- the environment --------------------------------------------------------


@dataclass
class EnvSource:
    """Variables, as text. Exposure is opt-in, so only marked fields are read."""

    prefix: str = ""
    environ: Mapping[str, str] | None = None
    precedence: int = Precedence.ENV
    dialect: Dialect = "string"
    kind: OriginKind = "env"
    base_dir: Path | None = None

    def _environ(self) -> Mapping[str, str]:
        import os

        return os.environ if self.environ is None else self.environ

    def _interpret(self, raw: str) -> Any:
        return raw

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        environ = self._environ()
        for spelling, absolute, targets in index.env_spellings():
            name = (
                spelling
                if absolute or not self.prefix
                else f"{self.prefix.upper()}_{spelling}"
            )
            if name in environ:
                yield from _readings_for(targets, self._interpret(environ[name]), name)


@dataclass
class TomlEnvSource(EnvSource):
    """The same variables, each parsed as TOML, so one can carry a table."""

    dialect: Dialect = "typed"

    def _interpret(self, raw: str) -> Any:
        try:
            parsed = tomllib.loads(f"value = {raw}")
        except tomllib.TOMLDecodeError:
            # Not a TOML scalar: a bare word is the ordinary case, and the
            # store will check it against the annotation like any other value.
            try:
                return tomllib.loads(raw)
            except tomllib.TOMLDecodeError:
                return raw
        return parsed["value"]


# --- argv -------------------------------------------------------------------


@dataclass
class _ArgvSource:
    """Shared machinery for everything that parses command-line tokens."""

    precedence: int = Precedence.CLI
    dialect: Dialect = "string"
    kind: OriginKind = "cli"
    overrides: list[tuple[str, str, str]] = field(default_factory=list)
    """``-o`` pairs this source carried, with where each came from."""

    help_requested: bool = False
    unknown: list[str] = field(default_factory=list)

    @property
    def base_dir(self) -> Path | None:
        """Tokens carry no directory of their own unless a source knows one."""
        return None

    def tokens(self) -> Sequence[str]:
        raise NotImplementedError

    def label(self, token: str) -> str:
        return token

    def bind(self, specs: Iterable[FieldSpec]) -> None:
        """Nothing is kept: the parser is rebuilt from the index on every read.

        Registration order is therefore irrelevant, which is the whole point of
        re-parsing rather than re-opening a parsed namespace.
        """

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        parser = ArgumentParser()
        parser.register(index.all_specs())
        result = parser.parse(self.tokens())

        self.help_requested = result.help_requested
        self.unknown = list(result.unknown)
        self.overrides = [
            (key, value, self.label("-o")) for key, value in result.overrides
        ]

        yield from self._place_occurrences(index, result.occurrences)

    def _place_occurrences(
        self, index: SpellingIndex, occurrences: Iterable[Any]
    ) -> Iterator[Reading]:
        """Turn occurrences into one reading per path.

        A repeated option is one reading holding every element, and a counted
        one is a single total: the store keeps a layer per source, so a source
        that meant "three of these" has to say so once.
        """
        collected: dict[tuple[Any, tuple[str, ...]], list[Any]] = {}
        specs: dict[tuple[Any, tuple[str, ...]], FieldSpec] = {}
        tokens: dict[tuple[Any, tuple[str, ...]], str] = {}

        for occurrence in occurrences:
            for target in index.cli(occurrence.token):
                key = (target.root, target.path)
                collected.setdefault(key, []).append(occurrence.raw)
                specs[key] = target.spec
                tokens[key] = occurrence.token

        for (root, path), raws in collected.items():
            spec = specs[(root, path)]
            if spec.counts:
                raw: Any = str(
                    sum(int(value) if value is not True else 1 for value in raws)
                )
            elif spec.repeatable:
                raw = raws
            else:
                raw = raws[-1]
            yield Reading(
                root=root, path=path, raw=raw, location=self.label(tokens[(root, path)])
            )


@dataclass
class CLISource(_ArgvSource):
    """The arguments the user actually typed."""

    args: Sequence[str] = ()
    invocation_dir: Path = field(default_factory=Path.cwd)

    def tokens(self) -> Sequence[str]:
        return self.args

    @property
    def base_dir(self) -> Path | None:
        """A relative path on the command line is relative to where it was typed."""
        return self.invocation_dir


@dataclass
class InjectedArgsSource(_ArgvSource):
    """Tokens a configuration field contributed, re-parsed as arguments.

    A source at its own rung rather than a splice into argv, which is what lets
    it sit below the environment and above files, and lets an injected option
    be reported as injected rather than as something the user typed.
    """

    precedence: int = Precedence.INJECTED
    kind: OriginKind = "injected"
    contributions: list[tuple[str, Sequence[str]]] = field(default_factory=list)
    """(contributor, tokens), in the order the manager collected them."""

    def contribute(self, contributor: str, tokens: Sequence[str]) -> None:
        """Add one contribution. Later ones win, as later tokens do."""
        self.contributions.append((contributor, tokens))

    def clear(self) -> None:
        self.contributions.clear()

    def tokens(self) -> Sequence[str]:
        return [token for _, tokens in self.contributions for token in tokens]

    def label(self, token: str) -> str:
        contributor = self.contributions[-1][0] if self.contributions else "injected"
        return f"injected {token} ({contributor})"


@dataclass
class OverrideSource:
    """``-o key=value`` pairs, from whichever argv source carried them.

    The one source that does not read an input of its own: ``-o`` is typed on
    the command line or carried by injected arguments, and either way it lands
    here, at one rung above the command line, so that
    ``--log-level=A -o log_level=B`` has a documented answer.
    """

    sources: Sequence[_ArgvSource] = ()
    precedence: int = Precedence.OVERRIDE
    dialect: Dialect = "string"
    kind: OriginKind = "override"
    base_dir: Path | None = None

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        for source in self.sources:
            for key, value, _label in source.overrides:
                targets = index.flat(key)
                if not targets:
                    yield Unmatched(spelling=key, location=f"-o {key}")
                    continue
                yield from _readings_for(targets, value, f"-o {key}")


@dataclass
class RuntimeSource:
    """Writes made after resolution, with the whole configuration in view."""

    precedence: int = Precedence.RUNTIME
    dialect: Dialect = "typed"
    kind: OriginKind = "runtime"
    base_dir: Path | None = None
    writes: list[tuple[Any, tuple[str, ...], Any, str]] = field(default_factory=list)

    def set(self, root: Any, path: tuple[str, ...], value: Any, writer: str) -> None:
        self.writes.append((root, path, value, writer))

    def read(self, index: SpellingIndex) -> Iterable[Reading | Unmatched]:
        for root, path, value, writer in self.writes:
            yield Reading(root=root, path=path, raw=value, location=f"runtime:{writer}")


__all__ = [
    "FILE_SOURCES",
    "BindingSource",
    "CLISource",
    "ConfigFileDiscoverySource",
    "ConfigSource",
    "EnvSource",
    "IniSource",
    "InjectedArgsSource",
    "OverrideSource",
    "RuntimeSource",
    "TomlEnvSource",
    "TomlSource",
    "source_for_file",
]
