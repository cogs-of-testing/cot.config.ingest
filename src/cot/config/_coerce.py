"""Turning raw strings into field values.

Every source ultimately hands over strings -- an INI value, an environment
variable, a command-line token -- and every source needs the same question
answered: what does this string mean for a field declared ``list[str]``, or
``Annotated[bool, no_cli]``, or ``int | None``?

That question is answered here, once. What each source keeps is *tokenisation*,
which genuinely differs: an INI list is newline- or comma-separated in one
value, while a repeated CLI option carries one element per occurrence. Splitting
is the source's business; interpreting the pieces is not.
"""

from __future__ import annotations

import types
from typing import Any, Union, get_origin


def element_type_of(field_type: Any) -> Any:
    """The element type of a list annotation, or the type itself."""
    if get_origin(field_type) is list:
        args = getattr(field_type, "__args__", ())
        if args:
            return args[0]
        return str
    return field_type


def coerce(raw_value: str, field_type: Any) -> Any:
    """Convert a raw string to ``field_type``.

    ``Annotated`` wrappers and ``Optional``/union members are stripped first.
    Without that, ``Annotated[bool, no_cli]`` never reaches the bool branch and
    ``"false"`` comes back as a truthy string.
    """
    if field_type is None:
        return raw_value

    while hasattr(field_type, "__metadata__"):
        field_type = field_type.__origin__

    origin = get_origin(field_type)

    if origin is Union or origin is types.UnionType:
        args = getattr(field_type, "__args__", ())
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return coerce(raw_value, non_none_args[0])

    if origin is list:
        return split_list(raw_value, field_type)

    if field_type is bool:
        return raw_value.lower() in ("true", "yes", "on", "1")

    if field_type is int:
        return int(raw_value)

    if field_type is float:
        return float(raw_value)

    return raw_value


def split_list(raw_value: str, field_type: Any) -> list[Any]:
    """Split one string into list elements and coerce each.

    Newlines win over commas, because that is how an INI file spells a list.
    """
    if not raw_value:
        return []
    element = element_type_of(field_type)
    if "\n" in raw_value:
        items = [line.strip() for line in raw_value.strip().splitlines()]
    else:
        items = [item.strip() for item in raw_value.split(",")]
    return [coerce(item, element) for item in items if item]


def coerce_parsed(value: Any, field_type: Any) -> Any:
    """Coerce a value a parser already turned into a str, list or bool.

    A repeated CLI option arrives as a list of raw strings, each of which is one
    *element*: coercing it against the list type would wrap every item in a list
    of its own. Booleans arrive already converted and are passed through.
    """
    if isinstance(value, str):
        return coerce(value, field_type)
    if isinstance(value, list):
        element = element_type_of(_strip_wrappers(field_type))
        return [
            coerce(item, element) if isinstance(item, str) else item for item in value
        ]
    return value


def _strip_wrappers(field_type: Any) -> Any:
    """Strip ``Annotated`` and ``Optional`` down to the type that carries args."""
    while hasattr(field_type, "__metadata__"):
        field_type = field_type.__origin__
    origin = get_origin(field_type)
    if origin is Union or origin is types.UnionType:
        non_none = [
            a for a in getattr(field_type, "__args__", ()) if a is not type(None)
        ]
        if non_none:
            return _strip_wrappers(non_none[0])
    return field_type


__all__ = [
    "coerce",
    "coerce_parsed",
    "element_type_of",
    "split_list",
]
