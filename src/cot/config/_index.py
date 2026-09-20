"""The reverse direction: a spelling a user typed, back to the field it means.

`_names.py` derives spellings from paths. This index resolves them back, and
those are the only two places a source-facing name is produced or recognised. A
source asks the index what a spelling means; it never splits a key, strips a
prefix or compares token strings.

The index holds every declared root at once, which is what makes two things
possible. A key is unknown only when nothing in it claims the key, so a root
never warns about another root's keys. And two roots that derive the same
spelling are judged against each other, rather than one silently winning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from ._diagnostics import ConfigCollisionError
from ._specs import FieldSpec, field_specs

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ._bases import ConfigPart


_K = TypeVar("_K")


@dataclass(frozen=True)
class SpellingTarget:
    """One field a spelling resolves to."""

    root: type[ConfigPart]
    path: tuple[str, ...]
    spec: FieldSpec
    deprecated: bool = False
    """The spelling is one of the field's ``formerly()`` aliases."""


@dataclass
class _Entry:
    """Everything one spelling resolves to, and the spec they agree on."""

    spec: FieldSpec
    targets: list[SpellingTarget] = field(default_factory=list)
    deprecated: bool = False


def _describe(root: type[ConfigPart], path: tuple[str, ...]) -> str:
    return f"{root.__name__}.{'.'.join(path)}"


class SpellingIndex:
    """Every spelling of every declared root, resolvable back to its field."""

    def __init__(self) -> None:
        self._flat: dict[str, _Entry] = {}
        self._cli: dict[str, _Entry] = {}
        self._env: dict[str, _Entry] = {}
        self._nested: dict[tuple[str | None, tuple[str, ...], str], _Entry] = {}
        self._roots: list[type[ConfigPart]] = []

    @property
    def roots(self) -> tuple[type[ConfigPart], ...]:
        """The roots this index was built over, in the order they were added."""
        return tuple(self._roots)

    def add(self, root: type[ConfigPart]) -> None:
        """Register every spelling of ``root``, judging collisions as it goes.

        Adding the same root twice is a no-op. Adding a root whose spellings
        another root already claims is either adoption, when the two specs
        agree on everything but where the value lands, or an error.
        """
        if root in self._roots:
            return

        for spec in field_specs(root):
            self._claim(self._flat, spec.flat, root, spec, "flat name")
            for alias in spec.aliases:
                self._claim(self._flat, alias, root, spec, "flat name", deprecated=True)
            for form in spec.cli:
                for option in (form.long, form.short, form.negative):
                    if option is not None:
                        self._claim(self._cli, option, root, spec, "option")
            if spec.env is not None:
                self._claim(self._env, spec.env.name, root, spec, "variable")
            if spec.file_key is not None:
                nested = (
                    _section_of(root),
                    _table_of(root, spec),
                    spec.path[-1],
                )
                self._claim(self._nested, nested, root, spec, "file table")

        self._roots.append(root)

    def _claim(
        self,
        namespace: dict[_K, _Entry],
        key: _K,
        root: type[ConfigPart],
        spec: FieldSpec,
        kind: str,
        *,
        deprecated: bool = False,
    ) -> None:
        target = SpellingTarget(
            root=root, path=spec.path, spec=spec, deprecated=deprecated
        )
        held = namespace.get(key)
        if held is None:
            namespace[key] = _Entry(spec=spec, targets=[target], deprecated=deprecated)
            return

        adoptable = (
            held.deprecated == deprecated
            and held.spec.comparable() == spec.comparable()
        )
        if not adoptable:
            first = held.targets[0]
            raise ConfigCollisionError(
                f"{_describe(first.root, first.path)} and "
                f"{_describe(root, spec.path)} both claim the {kind} "
                f"{key!r}, and do not agree on what it means. "
                f"Give one of them a name_prefix=, a named(...) override, "
                f"or no_cli."
            )
        held.targets.append(target)

    def flat(self, name: str) -> tuple[SpellingTarget, ...]:
        """Resolve an ini key, a flat TOML key or an ``-o`` key."""
        return self._targets(self._flat.get(name))

    def cli(self, option: str) -> tuple[SpellingTarget, ...]:
        """Resolve a command-line option, long, short or negated."""
        return self._targets(self._cli.get(option))

    def env(self, name: str, *, source_prefix: str = "") -> tuple[SpellingTarget, ...]:
        """Resolve an environment variable seen by a source with ``source_prefix``.

        The source's own prefix is composed here rather than stripped there: a
        source never takes a name apart.
        """
        for spelling, entry in self._env.items():
            composed = (
                spelling
                if entry.spec.env is not None and entry.spec.env.absolute
                else _with_prefix(source_prefix, spelling)
            )
            if composed == name:
                return self._targets(entry)
        return ()

    def nested(
        self, section: str | None, table: tuple[str, ...], key: str
    ) -> tuple[SpellingTarget, ...]:
        """Resolve a key inside a file table, spelled structurally."""
        return self._targets(self._nested.get((section, table, key)))

    def specs(self, root: type[ConfigPart]) -> tuple[FieldSpec, ...]:
        """Every spec of one declared root, for a binder to bind."""
        return field_specs(root)

    def all_specs(self) -> Iterable[FieldSpec]:
        """Every spec of every declared root."""
        for root in self._roots:
            yield from field_specs(root)

    @staticmethod
    def _targets(entry: _Entry | None) -> tuple[SpellingTarget, ...]:
        return tuple(entry.targets) if entry is not None else ()


def _with_prefix(prefix: str, name: str) -> str:
    return f"{prefix.upper()}_{name}" if prefix else name


def _section_of(root: type[ConfigPart]) -> str | None:
    from ._bases import part_prefix

    return part_prefix(root)


def _table_of(root: type[ConfigPart], spec: FieldSpec) -> tuple[str, ...]:
    from ._bases import part_name_prefix

    name_prefix = part_name_prefix(root)
    qualified = (name_prefix, *spec.path) if name_prefix else spec.path
    return tuple(qualified[:-1])


__all__ = [
    "SpellingIndex",
    "SpellingTarget",
]
