"""Mapping between a field's structural path and its name in each source.

A field lives at a structural path inside a ConfigPart -- ``("cli", "level")``
inside ``LoggingConfig``. Every source spells that differently:

===========  ==========================
CLI          ``--log-cli-level``
INI / flat   ``log_cli_level``
env          ``LOG_CLI_LEVEL``
TOML nested  ``[log.cli] level``
===========  ==========================

Two class-level knobs shape the result, and they are deliberately separate:

``prefix``
    Which *section* of a config file the ConfigPart occupies, and the default
    environment-variable prefix. Not part of option names.

``name_prefix``
    A prefix on every *field name*, in every source. This is what makes
    pytest's ``log_cli_level`` come out of a structural ``cli.level``.

pytest needs both at once: its logging options live in the ``[pytest]``
section but are named ``log_*``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._annotations import NameMarker, NamePrefixMarker, NoCLIMarker, PrefixMarker
from ._fields import FieldInfo, fields_of, has_marker, marker_of


@dataclass(frozen=True)
class FieldNames:
    """The names one field answers to, across sources."""

    path: tuple[str, ...]
    """Structural path inside the ConfigPart."""

    flat: str
    """Flat key, as used by INI files and flat TOML tables."""

    cli: str
    """Long CLI option, without the leading ``--``."""

    env: str
    """Environment variable name, without any source-level prefix."""


def part_prefix(part_type: type[Any]) -> str | None:
    """The section/env prefix declared via ``prefix=``, if any."""
    for marker in getattr(part_type, "_config_markers", ()):
        if isinstance(marker, PrefixMarker):
            return marker.prefix
    return None


def part_name_prefix(part_type: type[Any]) -> str | None:
    """The field-name prefix declared via ``name_prefix=``, if any."""
    for marker in getattr(part_type, "_config_markers", ()):
        if isinstance(marker, NamePrefixMarker):
            return marker.name_prefix
    return None


def section_name(part_type: type[Any]) -> str:
    """The config-file section a ConfigPart occupies."""
    return part_prefix(part_type) or part_type.__name__


def names_of(part_type: type[Any], field: FieldInfo) -> FieldNames:
    """Derive every source-specific name for ``field`` of ``part_type``.

    A ``named(...)`` marker on the field replaces the derived flat name
    outright; the CLI and env spellings are then derived from the override, so
    all three stay consistent.
    """
    override = marker_of(field, NameMarker)
    if override is not None:
        flat = override.name
    else:
        segments = list(field.path)
        name_prefix = part_name_prefix(part_type)
        if name_prefix:
            segments.insert(0, name_prefix)
        flat = "_".join(segments)

    return FieldNames(
        path=field.path,
        flat=flat,
        cli=flat.replace("_", "-"),
        env=flat.upper(),
    )


def cli_visible(field: FieldInfo) -> bool:
    """Whether the field should get a dedicated CLI option."""
    return not has_marker(field, NoCLIMarker)


def named_leaf_fields(part_type: type[Any]) -> list[tuple[FieldInfo, FieldNames]]:
    """Every leaf field of ``part_type`` paired with its names."""
    return [
        (field, names_of(part_type, field))
        for field in fields_of(part_type)
        if not field.is_sub_config
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
    "cli_visible",
    "expand_flat_keys",
    "flat_index",
    "named_leaf_fields",
    "names_of",
    "part_name_prefix",
    "part_prefix",
    "section_name",
    "set_path",
]
