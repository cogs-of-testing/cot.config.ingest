"""The field model: one walker, one record, read by everything else.

Before this module existed, knowledge about a field was re-derived ad hoc in
eight places -- each with its own ``get_origin(x) is Annotated`` loop, each
seeing only one class level deep. ``iter_fields`` replaces all of them.

The model is deliberately read-only and cached per class: a ``ConfigPart``'s
shape is fixed once the class body has executed.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from typing import (
    Annotated,
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)


class _Missing:
    """Sentinel for "this field has no default"."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()

_M = TypeVar("_M")


@dataclass(frozen=True)
class FieldInfo:
    """Everything known about one configuration field.

    A field is either a *leaf* (a plain value) or a *sub-config* (a nested
    ``SubConfig`` type).  ``iter_fields`` yields both, and ``path`` is what
    distinguishes ``cli.level`` from the top-level ``level``.
    """

    path: tuple[str, ...]
    """Dotted path from the ConfigPart root, e.g. ``("cli", "level")``."""

    name: str
    """The bare attribute name, e.g. ``"level"``."""

    annotation: Any
    """The declared annotation, ``Annotated[...]`` wrapper preserved."""

    type: Any
    """The annotation with ``Annotated`` and ``Optional`` stripped."""

    default: Any
    """The class-level default, or :data:`MISSING`."""

    markers: tuple[object, ...]
    """Every ``Annotated`` extra, in declaration order."""

    owner: type[Any]
    """The class whose body declared this field."""

    is_sub_config: bool
    """True when :attr:`type` is a ``SubConfig`` subclass."""

    @property
    def required(self) -> bool:
        """A field with no default that is not a sub-config must be supplied."""
        return self.default is MISSING and not self.is_sub_config

    @property
    def dotted(self) -> str:
        """The path rendered as ``"cli.level"``."""
        return ".".join(self.path)


def is_sub_config(tp: Any) -> bool:
    """Check whether a type annotation refers to a ``SubConfig`` subclass."""
    from ._bases import SubConfig

    return isinstance(tp, type) and issubclass(tp, SubConfig)


def unwrap_type(annotation: Any) -> Any:
    """Strip ``Annotated`` and ``Optional``/union wrappers down to one type.

    ``Annotated[str | None, from_parent]`` becomes ``str``.  For unions with
    several non-None members the first is returned -- config values come from
    strings, so the first member is what parsing targets.
    """
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            return unwrap_type(args[0])

    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in get_args(annotation) if a is not type(None)]
        if non_none:
            return unwrap_type(non_none[0])

    return annotation


def markers_of(annotation: Any) -> tuple[object, ...]:
    """Return the ``Annotated`` extras of an annotation, outermost first."""
    if get_origin(annotation) is Annotated:
        return tuple(get_args(annotation)[1:])
    return ()


def marker_of(field: FieldInfo, marker_type: type[_M]) -> _M | None:
    """Return the first marker of ``marker_type`` on ``field``, if any."""
    for marker in field.markers:
        if isinstance(marker, marker_type):
            return marker
    return None


def has_marker(field: FieldInfo, marker_type: type[Any]) -> bool:
    """Check whether ``field`` carries a marker of ``marker_type``."""
    return marker_of(field, marker_type) is not None


def resolve_hints(cls: type[Any]) -> dict[str, Any]:
    """Resolve a class's annotations, keeping ``Annotated`` metadata."""
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception:
        # Unresolvable forward reference: fall back to the raw annotations so
        # a partially-defined class still yields something usable.
        return dict(getattr(cls, "__annotations__", {}))


def _declared_names(cls: type[Any]) -> list[str]:
    """Field names in MRO order, base classes first, without duplicates."""
    names: list[str] = []
    for klass in reversed(cls.__mro__):
        for name in getattr(klass, "__annotations__", {}):
            if name.startswith("_"):
                continue
            if name not in names:
                names.append(name)
    return names


def _owner_of(cls: type[Any], name: str) -> type[Any]:
    """The most-derived class in ``cls.__mro__`` that declares ``name``."""
    for klass in cls.__mro__:
        if name in getattr(klass, "__annotations__", {}):
            return klass
    return cls


def _default_of(cls: type[Any], name: str) -> Any:
    """The class-level default for ``name``, or :data:`MISSING`.

    Callables are skipped: a method or classmethod that happens to share a
    field's name is not a default value.
    """
    if not hasattr(cls, name):
        return MISSING
    value = getattr(cls, name)
    if callable(value):
        return MISSING
    return value


_FIELD_CACHE: dict[tuple[type[Any], bool], tuple[FieldInfo, ...]] = {}


def fields_of(cls: type[Any], *, recurse: bool = True) -> tuple[FieldInfo, ...]:
    """Return the fields of a ``ConfigPart``/``SubConfig`` class.

    Args:
        cls: The class to inspect.
        recurse: When True, descend into ``SubConfig``-typed fields and yield
            their fields too, with dotted paths.  The sub-config field itself
            is yielded as well, before its children.

    Results are cached per ``(cls, recurse)``.
    """
    key = (cls, recurse)
    cached = _FIELD_CACHE.get(key)
    if cached is not None:
        return cached

    result = tuple(_walk(cls, prefix=(), recurse=recurse, seen=frozenset()))
    _FIELD_CACHE[key] = result
    return result


def iter_fields(cls: type[Any], *, recurse: bool = True) -> tuple[FieldInfo, ...]:
    """Alias of :func:`fields_of`, spelled for iteration at call sites."""
    return fields_of(cls, recurse=recurse)


def _walk(
    cls: type[Any],
    *,
    prefix: tuple[str, ...],
    recurse: bool,
    seen: frozenset[type[Any]],
) -> list[FieldInfo]:
    hints = resolve_hints(cls)
    result: list[FieldInfo] = []

    for name in _declared_names(cls):
        annotation = hints.get(name, getattr(cls, "__annotations__", {}).get(name))
        if annotation is None:
            continue

        unwrapped = unwrap_type(annotation)
        nested = is_sub_config(unwrapped)

        info = FieldInfo(
            path=(*prefix, name),
            name=name,
            annotation=annotation,
            type=unwrapped,
            default=_default_of(cls, name),
            markers=markers_of(annotation),
            owner=_owner_of(cls, name),
            is_sub_config=nested,
        )
        result.append(info)

        if nested and recurse:
            if unwrapped in seen:
                # Self-referential sub-config: stop rather than recurse forever.
                continue
            result.extend(
                _walk(
                    unwrapped,
                    prefix=info.path,
                    recurse=recurse,
                    seen=seen | {unwrapped},
                )
            )

    return result


def leaf_fields(cls: type[Any]) -> tuple[FieldInfo, ...]:
    """Every non-sub-config field, including nested ones, with dotted paths."""
    return tuple(f for f in fields_of(cls) if not f.is_sub_config)


def field_defaults(cls: type[Any]) -> dict[str, Any]:
    """Top-level field name to default, for fields that have one.

    This is the flat mapping the manager seeds its merge with; nested
    sub-configs are built separately.
    """
    return {
        f.name: f.default
        for f in fields_of(cls, recurse=False)
        if f.default is not MISSING
    }


__all__ = [
    "MISSING",
    "FieldInfo",
    "field_defaults",
    "fields_of",
    "has_marker",
    "is_sub_config",
    "iter_fields",
    "leaf_fields",
    "marker_of",
    "markers_of",
    "resolve_hints",
    "unwrap_type",
]
