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
from weakref import WeakKeyDictionary


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

    A field is either a *leaf* (a plain value) or *nested* (a ``ConfigPart``
    typed field, which is a section). ``fields_of`` yields both, and ``path``
    is what distinguishes ``cli.level`` from the top-level ``level``.
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

    is_nested: bool
    """True when :attr:`type` is a ``ConfigPart`` subclass: a section."""

    @property
    def required(self) -> bool:
        """A field with no default and no nested type must be supplied."""
        return self.default is MISSING and not self.is_nested

    @property
    def dotted(self) -> str:
        """The path rendered as ``"cli.level"``."""
        return ".".join(self.path)


def is_nested_type(tp: Any) -> bool:
    """Whether ``tp`` is a ``ConfigPart`` subclass, and so a nested section."""
    from ._bases import ConfigPart

    return isinstance(tp, type) and issubclass(tp, ConfigPart)


def strip_annotated(annotation: Any) -> Any:
    """Return ``annotation`` with any ``Annotated`` wrapper removed."""
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if args:
            return strip_annotated(args[0])
    return annotation


def union_members(annotation: Any) -> tuple[Any, ...] | None:
    """The members of ``annotation`` if it is a union, else ``None``."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return get_args(annotation)
    return None


def declared_type(annotation: Any) -> Any:
    """The declared type: ``Annotated`` removed, ``Optional`` collapsed.

    ``Annotated[str | None, from_parent]`` is ``str``, because ``None`` says
    the field may be absent rather than what it holds. A union with more than
    one real member is returned whole: ``bool | int | None`` is ``bool | int``,
    and which member a raw value becomes is conversion's question, answered by
    trying them in order.
    """
    annotation = strip_annotated(annotation)

    members = union_members(annotation)
    if members is None:
        return annotation

    real = [strip_annotated(m) for m in members if m is not type(None)]
    if not real:
        return annotation
    if len(real) == 1:
        return real[0]
    return Union[tuple(real)]  # noqa: UP007  - built from a variable


def unwrap_type(annotation: Any) -> Any:
    """Strip wrappers down to exactly one type, taking a union's first member.

    The callers left are the ones that must name a single type to a host's
    parser. They go when [sources](../../docs/design/sources.md) is rebuilt
    against specs, which describe a union without collapsing it.
    """
    declared = declared_type(annotation)
    members = union_members(declared)
    if members:
        return members[0]
    return declared


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
    except NameError:
        # Unresolvable forward reference: fall back to the raw annotations so
        # a partially-defined class still yields something usable. Only
        # NameError is tolerated -- a broader except would swallow a genuinely
        # malformed annotation, and the string that came back in its place
        # would make a nested field look like a leaf.
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


#: Keyed weakly, so inspecting a class -- which classes defined inside a test
#: function do constantly -- does not keep it alive for the process lifetime.
_FIELD_CACHE: WeakKeyDictionary[type[Any], dict[bool, tuple[FieldInfo, ...]]] = (
    WeakKeyDictionary()
)


def fields_of(cls: type[Any], *, recurse: bool = True) -> tuple[FieldInfo, ...]:
    """Return the fields of a ``ConfigPart`` class.

    Args:
        cls: The class to inspect.
        recurse: When True, descend into ``ConfigPart``-typed fields and yield
            their fields too, with dotted paths.  The sub-config field itself
            is yielded as well, before its children.

    Results are cached per ``(cls, recurse)``.
    """
    per_class = _FIELD_CACHE.setdefault(cls, {})
    cached = per_class.get(recurse)
    if cached is not None:
        return cached

    result = tuple(_walk(cls, prefix=(), recurse=recurse, seen=frozenset()))
    per_class[recurse] = result
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

        declared = declared_type(annotation)
        nested = is_nested_type(declared)

        info = FieldInfo(
            path=(*prefix, name),
            name=name,
            annotation=annotation,
            type=declared,
            default=_default_of(cls, name),
            markers=markers_of(annotation),
            owner=_owner_of(cls, name),
            is_nested=nested,
        )
        result.append(info)

        if nested and recurse:
            if declared in seen:
                # Self-referential nested part: stop rather than recurse forever.
                continue
            result.extend(
                _walk(
                    declared,
                    prefix=info.path,
                    recurse=recurse,
                    seen=seen | {declared},
                )
            )

    return result


def misbound_markers(annotation: Any) -> tuple[object, ...]:
    """Library markers attached to a union member instead of to the field.

    ``str | None @ from_parent`` parses as ``str | Annotated[None, ...]``,
    because ``@`` binds tighter than ``|``. The marker is then attached to
    ``None`` and describes nothing.
    """
    from ._annotations import Marker

    members = union_members(strip_annotated(annotation))
    if members is None:
        return ()
    return tuple(
        marker
        for member in members
        for marker in markers_of(member)
        if isinstance(marker, Marker)
    )


def check_declaration(root: type[Any]) -> None:
    """Raise if ``root``'s shape is something the library cannot honour.

    Called by ``declare()``, because a malformed declaration is known the
    moment the class is seen and reporting it then puts the traceback at the
    call site that caused it.
    """
    from ._bases import declared_root_keywords
    from ._diagnostics import ConfigDeclarationError

    for field in fields_of(root):
        misbound = misbound_markers(field.annotation)
        if misbound:
            names = ", ".join(repr(marker) for marker in misbound)
            raise ConfigDeclarationError(
                f"{root.__name__}.{field.dotted}: {names} "
                f"is bound to a member of the union, not to the field, "
                f"because `@` binds tighter than `|`. "
                f"Write `({field.annotation}) @ marker`, "
                f"or Annotated[...] with the marker as an extra."
            )

        if not field.is_nested:
            continue
        keywords = declared_root_keywords(field.type)
        if keywords:
            raise ConfigDeclarationError(
                f"{root.__name__}.{field.dotted} is a nested part, and "
                f"{field.type.__name__} declares {', '.join(keywords)}=. "
                f"Those describe a root: the section, the name prefix and the "
                f"environment exposure of a whole declaration. Nested here, "
                f"they would have no effect. Remove them, or declare "
                f"{field.type.__name__} as a root of its own."
            )


def leaf_fields(cls: type[Any]) -> tuple[FieldInfo, ...]:
    """Every leaf field, at every depth, with its dotted path."""
    return tuple(f for f in fields_of(cls) if not f.is_nested)


def field_defaults(cls: type[Any]) -> dict[str, Any]:
    """Top-level field name to default, for fields that have one.

    This is the flat mapping the manager seeds its merge with; nested parts
    are built separately.
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
    "check_declaration",
    "declared_type",
    "is_nested_type",
    "iter_fields",
    "leaf_fields",
    "marker_of",
    "misbound_markers",
    "markers_of",
    "resolve_hints",
    "strip_annotated",
    "union_members",
    "unwrap_type",
]
