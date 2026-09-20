"""What a raw value from a source means for a field with a declared annotation.

Every source hands over raw values and every one of them needs the same
question answered: what does this mean for a field declared ``list[str]``, or
``bool | int | None``? It is answered here, once, when the value enters the
store, so nothing downstream ever sees a raw value.

What stays in each source is *tokenisation*, which genuinely differs: an INI
list is newline- or comma-separated inside one value, while a repeated CLI
option carries one element per occurrence. Splitting is the source's business;
interpreting the pieces is not. That split is what keeps the source catalogue
open: a new source has to know how to find and tokenise its input, never what a
``bool`` looks like.

Two dialects. A string-dialect source hands over text and the registry
**converts** it. A typed-dialect source -- TOML, YAML, a host handing back what
its own parser produced -- hands over values that already have types, and the
registry **checks** them against the annotation instead. Which of the two a
value gets is decided by its source's dialect, once; a value is never converted
twice.
"""

from __future__ import annotations

import inspect
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin

from ._diagnostics import ConfigValueError
from ._fields import strip_annotated, union_members

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._origins import Origin

#: A converter takes the raw value and the origin it arrived from, and raises
#: if it cannot produce a value of the declared type.
Converter = "Callable[[Any, Origin], Any]"

_REGISTRY: dict[Any, Callable[[Any, Origin], Any]] = {}

#: Types every typed format can represent, so a typed source handing over text
#: for one of them is describing a value of the wrong type.
NATIVE_SCALARS = (bool, int, float, str)

TRUE_WORDS = frozenset({"true", "yes", "on", "1"})
FALSE_WORDS = frozenset({"false", "no", "off", "0"})


def register_conversion(
    annotation: Any, converter: Callable[..., Any], *, replace: bool = False
) -> None:
    """Teach the registry how to build ``annotation`` from a raw value.

    The converter may take the raw value alone, as ``re.compile`` does, or the
    raw value and the :class:`Origin` it arrived from. Which one it wants is
    settled here, at registration, rather than guessed at every call.

    The registry is global rather than per manager, because a conversion is a
    property of the type: the same annotation must mean the same thing in every
    part of one program.
    """
    if annotation in _REGISTRY and not replace:
        raise ValueError(
            f"{annotation!r} already has a conversion; "
            f"pass replace=True to take it over deliberately"
        )
    _REGISTRY[annotation] = _with_origin(converter)


def unregister_conversion(annotation: Any) -> None:
    """Forget a registered conversion. For tests, and for taking one back."""
    _REGISTRY.pop(annotation, None)


def _with_origin(converter: Callable[..., Any]) -> Callable[[Any, Origin], Any]:
    """Adapt a converter to the two-argument protocol.

    A converter asks for the origin by declaring a parameter called ``origin``,
    and is handed it by keyword. Anything else is called with the raw value
    alone, which is what lets an existing one-argument callable be registered
    as it stands: ``register_conversion(re.Pattern, re.compile)`` works, and
    guessing by arity would have passed the origin as ``re.compile``'s flags.
    """
    try:
        parameters = inspect.signature(converter).parameters
    except (TypeError, ValueError):
        # A builtin whose signature cannot be read takes the value alone.
        return lambda raw, _origin: converter(raw)

    if "origin" in parameters:
        return lambda raw, origin: converter(raw, origin=origin)
    return lambda raw, _origin: converter(raw)


def has_conversion(annotation: Any) -> bool:
    """Whether a value of ``annotation`` can be built from a raw one.

    Structure -- unions, lists, closed sets -- is handled by the walk in
    :func:`convert`, so this answers for the whole annotation and not only for
    what the registry holds directly.
    """
    declared = strip_annotated(annotation)

    members = union_members(declared)
    if members is not None:
        return all(has_conversion(m) for m in members if m is not type(None))

    if declared is type(None):
        return True
    if get_origin(declared) is Literal:
        return True
    if isinstance(declared, type) and issubclass(declared, Enum):
        return True
    if get_origin(declared) is list:
        args = get_args(declared)
        return has_conversion(args[0]) if args else True

    return declared in _REGISTRY


def convert(raw: Any, annotation: Any, origin: Origin) -> Any:
    """Build a value of ``annotation`` from ``raw``, which came from ``origin``.

    Raises :class:`ConfigValueError` naming the declared type, the value and
    where it came from.
    """
    declared = strip_annotated(annotation)

    members = union_members(declared)
    if members is not None:
        return _convert_union(raw, members, annotation, origin)

    if declared is type(None):
        if raw is None:
            return None
        raise _cannot(raw, annotation, origin)

    values = _closed_set(declared)
    if values is not None:
        return _convert_closed(raw, declared, values, annotation, origin)

    if get_origin(declared) is list:
        args = get_args(declared)
        element = args[0] if args else str
        items = raw if isinstance(raw, list) else [raw]
        return [convert(item, element, origin) for item in items]

    converter = _REGISTRY.get(declared)
    if converter is None:
        raise _cannot(raw, annotation, origin, why="no conversion is registered")

    try:
        return converter(raw, origin)
    except ConfigValueError:
        raise
    except Exception as exc:
        raise _cannot(raw, annotation, origin, why=str(exc)) from exc


def check(value: Any, annotation: Any, origin: Origin) -> Any:
    """Verify a value a typed source produced against ``annotation``.

    A typed source's values already have types, so they are checked rather than
    converted. What a check does *not* do is reinterpret: a TOML string stays a
    string, and a field declared ``int`` rejects it.
    """
    declared = strip_annotated(annotation)

    members = union_members(declared)
    if members is not None:
        for member in members:
            try:
                return check(value, member, origin)
            except ConfigValueError:
                continue
        raise _cannot(value, annotation, origin)

    if declared is type(None):
        if value is None:
            return None
        raise _cannot(value, annotation, origin)

    values = _closed_set(declared)
    if values is not None:
        return _convert_closed(value, declared, values, annotation, origin)

    if get_origin(declared) is list:
        if not isinstance(value, list):
            raise _cannot(value, annotation, origin)
        args = get_args(declared)
        element = args[0] if args else str
        return [check(item, element, origin) for item in value]

    if isinstance(declared, type) and isinstance(value, declared):
        # bool is an int in Python; a field declared int must not take True.
        if declared is not bool and isinstance(value, bool):
            raise _cannot(value, annotation, origin)
        return value

    # A typed source may still hand over a string for a domain type its format
    # cannot represent -- a path, a pattern -- so building one from text is the
    # last resort. It is never the answer for a scalar every format does have:
    # a TOML string where the field says int is a broken file, not something to
    # reinterpret.
    if (
        isinstance(value, str)
        and declared not in NATIVE_SCALARS
        and declared in _REGISTRY
    ):
        return convert(value, annotation, origin)

    raise _cannot(value, annotation, origin)


def _convert_union(
    raw: Any, members: tuple[Any, ...], annotation: Any, origin: Origin
) -> Any:
    """Try each member in declaration order, taking the first that works.

    ``bool | int | None`` from ``"4"`` is ``4`` and from ``"true"`` is ``True``,
    because ``bool`` only accepts its known words. A union whose members
    overlap resolves by order, which is why ``str`` belongs last.
    """
    for member in members:
        try:
            return convert(raw, member, origin)
        except ConfigValueError:
            continue
    raise _cannot(raw, annotation, origin)


def _closed_set(declared: Any) -> tuple[Any, ...] | None:
    if get_origin(declared) is Literal:
        return get_args(declared)
    if isinstance(declared, type) and issubclass(declared, Enum):
        return tuple(member.value for member in declared)
    return None


def _convert_closed(
    raw: Any,
    declared: Any,
    values: tuple[Any, ...],
    annotation: Any,
    origin: Origin,
) -> Any:
    """Match a value against a closed set, by value, reporting by name."""
    is_enum = isinstance(declared, type) and issubclass(declared, Enum)

    for permitted in values:
        if raw == permitted:
            return declared(permitted) if is_enum else permitted
        # A closed set of strings is reachable from a string source as written;
        # one of ints is reachable from the text of an int.
        if isinstance(permitted, int) and not isinstance(permitted, bool):
            try:
                if int(raw) == permitted:
                    return declared(permitted) if is_enum else permitted
            except (TypeError, ValueError):
                pass

    shown = ", ".join(repr(v) for v in values)
    raise _cannot(raw, annotation, origin, why=f"permitted values are {shown}")


def _cannot(
    raw: Any, annotation: Any, origin: Origin, *, why: str | None = None
) -> ConfigValueError:
    reason = f": {why}" if why else ""
    return ConfigValueError(
        f"{raw!r} from {origin} is not a valid {_show(annotation)}{reason}"
    )


def _show(annotation: Any) -> str:
    declared = strip_annotated(annotation)
    return getattr(declared, "__name__", None) or str(declared)


def _to_bool(raw: Any, _origin: Origin) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise ValueError(f"expected one of {sorted(TRUE_WORDS | FALSE_WORDS)}")


def _to_int(raw: Any, _origin: Origin) -> int:
    if isinstance(raw, bool):
        raise ValueError("a boolean is not an integer")
    return int(raw)


def _to_float(raw: Any, _origin: Origin) -> float:
    if isinstance(raw, bool):
        raise ValueError("a boolean is not a number")
    return float(raw)


def _to_str(raw: Any, _origin: Origin) -> str:
    if isinstance(raw, str):
        return raw
    raise ValueError("expected text")


def _to_path(raw: Any, origin: Origin) -> Path:
    """Resolve a path against whatever the value's origin is relative to.

    A relative path means different things depending on who supplied it: in a
    config file it is relative to that file, on the command line to the
    invocation directory. Without the origin, `Path` fields are either wrong
    for one of those or fixed up by the caller after construction.
    """
    path = Path(raw)
    if path.is_absolute() or origin.base_dir is None:
        return path
    return origin.base_dir / path


def _register_builtins() -> None:
    """Seed the registry. These are already in the two-argument internal form."""
    for annotation, converter in (
        (bool, _to_bool),
        (int, _to_int),
        (float, _to_float),
        (str, _to_str),
        (Path, _to_path),
    ):
        _REGISTRY[annotation] = converter


_register_builtins()


__all__ = [
    "FALSE_WORDS",
    "NATIVE_SCALARS",
    "TRUE_WORDS",
    "check",
    "convert",
    "has_conversion",
    "register_conversion",
    "unregister_conversion",
]
