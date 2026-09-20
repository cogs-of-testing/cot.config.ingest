"""One declaration, four spellings: a field's path rendered per source.

A field lives at a structural path inside a ConfigPart -- ``("cli", "level")``
inside ``LoggingConfig``. Its *qualified* path is that path with the root's
``name_prefix`` prepended as a segment, and every spelling is the qualified
path rendered with a different separator::

    qualified    ("log", "cli", "level")
    flat         log_cli_level              (ini, flat TOML, and the -o key)
    CLI          log-cli-level              (rendered --log-cli-level)
    env          PYTEST_LOG_CLI_LEVEL       (a source prefixes its own on top)
    nested       [pytest.log.cli] level

Two class keywords shape the result, and they are deliberately separate:

``prefix``
    Which *section* of a config file the root occupies, and its
    environment-variable prefix. Not part of any option name.

``name_prefix``
    A segment leading every *field name*, in every source. This is what makes
    pytest's ``log_cli_level`` come out of a structural ``cli.level``.

pytest needs both at once: its logging options live in the ``[pytest]``
section but are named ``log_*``. ``prefix`` is shared -- every pytest plugin's
options live in ``[pytest]`` -- so ``name_prefix`` is the only thing keeping
one root's ``cli.level`` apart from another's.

This module is the forward direction only. Recognising a name a user typed is
the spelling index's job, and it arrives with build step 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._annotations import NameMarker, NoCLIMarker
from ._bases import part_name_prefix, part_prefix
from ._fields import FieldInfo, fields_of, has_marker, marker_of


@dataclass(frozen=True)
class NestedName:
    """Where a field sits when a file spells it as tables rather than a key."""

    section: str | None
    """The root's ``prefix``, or ``None`` when its keys sit at the top level."""

    table: tuple[str, ...]
    """The tables below the section: the qualified path without the leaf."""

    key: str
    """The bare field name, which is the key inside that table."""

    @property
    def dotted(self) -> str:
        """Section, tables and key as one dotted string, for display."""
        segments = (*((self.section,) if self.section else ()), *self.table, self.key)
        return ".".join(segments)


@dataclass(frozen=True)
class FieldNames:
    """The names one field answers to, across every source."""

    path: tuple[str, ...]
    """Structural path inside the root."""

    qualified: tuple[str, ...]
    """The path with the root's ``name_prefix`` prepended, if it has one."""

    flat: str
    """Flat key, as used by INI files, flat TOML tables and ``-o``."""

    cli: str
    """Long CLI option, without the leading ``--``."""

    env: str
    """Environment variable, root prefix included, source prefix not."""

    nested: NestedName
    """The tables-and-key spelling a file may use instead of :attr:`flat`."""


def section_name(part_type: type[Any]) -> str:
    """The config-file section a ConfigPart occupies.

    Pre-rebuild sources still need a section for a root that declares no
    ``prefix``, and use the class name. ``names.md`` rejects that -- a class
    name is an implementation detail, and renaming the class would silently
    move the section -- and :class:`NestedName` says ``None`` instead. The
    fallback goes when those sources are rebuilt against the index.
    """
    return part_prefix(part_type) or part_type.__name__


def qualified_path(part_type: type[Any], field: FieldInfo) -> tuple[str, ...]:
    """``field``'s path with the root's ``name_prefix`` prepended as a segment.

    A segment, not a string prefix: it has to survive into the nested file
    spelling, or two roots differing only in ``name_prefix``, each with a
    ``cli`` part, would both read ``[pytest.cli] level``.
    """
    name_prefix = part_name_prefix(part_type)
    if name_prefix:
        return (name_prefix, *field.path)
    return field.path


def names_of(part_type: type[Any], field: FieldInfo) -> FieldNames:
    """Derive every source-specific name for ``field`` of ``part_type``.

    A ``named(...)`` marker replaces the derived flat name outright, and the
    CLI and environment spellings are re-derived from the override so all three
    stay consistent. The nested spelling is unaffected: it is the structural
    path, and ``named()`` renames a leaf rather than moving it.
    """
    qualified = qualified_path(part_type, field)

    override = marker_of(field, NameMarker)
    flat = override.name if override is not None else "_".join(qualified)

    prefix = part_prefix(part_type)
    env = "_".join([prefix, flat] if prefix else [flat]).upper()

    return FieldNames(
        path=field.path,
        qualified=qualified,
        flat=flat,
        cli=flat.replace("_", "-"),
        env=env,
        nested=NestedName(section=prefix, table=qualified[:-1], key=field.name),
    )


def cli_visible(field: FieldInfo) -> bool:
    """Whether the field should get a dedicated CLI option."""
    return not has_marker(field, NoCLIMarker)


def named_leaf_fields(part_type: type[Any]) -> list[tuple[FieldInfo, FieldNames]]:
    """Every leaf field of ``part_type`` paired with its names."""
    return [
        (field, names_of(part_type, field))
        for field in fields_of(part_type)
        if not field.is_nested
    ]


def flat_index(part_type: type[Any]) -> dict[str, FieldInfo]:
    """Flat key -> field, for every leaf field of ``part_type``."""
    return {names.flat: field for field, names in named_leaf_fields(part_type)}


def set_path(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Assign ``value`` at ``path``, creating intermediate dicts as needed."""
    node = target
    for segment in path[:-1]:
        existing = node.get(segment)
        if not isinstance(existing, dict):
            existing = {}
            node[segment] = existing
        node = existing
    node[path[-1]] = value


def expand_flat_keys(
    part_type: type[Any],
    data: dict[str, Any],
    *,
    parse: Any = None,
) -> dict[str, Any]:
    """Rewrite recognised flat keys in ``data`` into their nested paths.

    Keys that are already structural (a top-level field name, or a nested
    table matching a sub-config) are passed through untouched, so a source may
    mix both spellings -- ``[log.cli] level`` and ``log_cli_level`` reach the
    same field.

    Args:
        part_type: The ConfigPart the data is being loaded for.
        data: Raw key/value pairs from a source.
        parse: Optional ``(raw_value, field_type) -> value`` callable applied
            to values whose key was recognised as a flat leaf name.

    Returns:
        A new dict shaped like the ConfigPart's structure.
    """
    own_names = {field.name for field in fields_of(part_type, recurse=False)}
    by_flat = flat_index(part_type)

    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in own_names:
            # Structural key: a direct field or a nested sub-config table.
            result[key] = value
            continue

        field = by_flat.get(key)
        if field is None:
            # Unknown to this ConfigPart; keep it so the manager can report it.
            result[key] = value
            continue

        if parse is not None and isinstance(value, str):
            value = parse(value, field.annotation)
        set_path(result, field.path, value)

    return result


__all__ = [
    "FieldNames",
    "NestedName",
    "cli_visible",
    "expand_flat_keys",
    "flat_index",
    "named_leaf_fields",
    "names_of",
    "qualified_path",
    "section_name",
    "set_path",
]
