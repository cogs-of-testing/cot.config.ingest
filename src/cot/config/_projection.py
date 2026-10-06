"""From a store of layers to one built, typed, frozen instance.

Three things happen here, in this order: the winner per path is taken, the
``from_parent`` cascade fills what a child did not say for itself, and the
result is assembled depth-first into nested parts and constructed.

Construction is where required fields are enforced and where a directly built
instance is type-checked, so a hand-written ``LoggingConfig(level=5)`` fails the
same way a config file does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from ._annotations import FromParentMarker
from ._bases import ConfigPart
from ._diagnostics import MissingConfigError
from ._fields import MISSING, FieldInfo, fields_of, has_marker
from ._origins import Origin, default_origin
from ._store import FailedValue, LayeredStore

_T = TypeVar("_T", bound=ConfigPart)


@dataclass(frozen=True)
class Projection(Generic[_T]):
    """One root's built instance, and where every value in it came from."""

    instance: _T
    origins: dict[str, Origin]


def project(root: type[_T], store: LayeredStore) -> Projection[_T]:
    """Build ``root`` from what the store holds, recording every origin."""
    values, origins = _winners(root, store)
    _cascade(root, values, origins)
    instance: _T = _assemble(root, values, prefix=())
    return Projection(instance=instance, origins=origins)


def _winners(
    root: type[ConfigPart], store: LayeredStore
) -> tuple[dict[tuple[str, ...], Any], dict[str, Origin]]:
    """The value each leaf ends up with, before the cascade, and its origin.

    A class default is a value like any other and carries an origin of its own,
    because a value that cannot be attributed means the merge is wrong.
    """
    values: dict[tuple[str, ...], Any] = {}
    origins: dict[str, Origin] = {}

    for info in fields_of(root):
        if info.is_nested:
            continue
        won = store.winner(root, info.path)
        if won is not None and not isinstance(won, FailedValue):
            values[info.path] = won.value
            origins[info.dotted] = won.origin
        elif info.default is not MISSING:
            values[info.path] = info.default
            origins[info.dotted] = default_origin(info.dotted)

    return values, origins


def _cascade(
    root: type[ConfigPart],
    values: dict[tuple[str, ...], Any],
    origins: dict[str, Origin],
) -> None:
    """Fill a `from_parent` field from the parent field of the same name.

    Presence is what is tested, not truthiness: an explicit ``0``, ``""`` or
    ``[]`` in the child stays. A cascaded value is attributed to wherever the
    parent got it, not to the child's default, or ``--log-level DEBUG`` would
    report ``cli.level`` as a default.
    """
    for info in fields_of(root):
        if info.is_nested or not has_marker(info, FromParentMarker):
            continue

        parent_path = _parent_path(info)
        if parent_path is None or parent_path not in values:
            continue

        if _was_supplied(info, values, origins):
            continue

        values[info.path] = values[parent_path]
        parent_origin = origins.get(".".join(parent_path))
        if parent_origin is not None:
            origins[info.dotted] = Origin(
                kind=parent_origin.kind,
                location=(
                    f"inherited from {'.'.join(parent_path)} ({parent_origin.location})"
                ),
                precedence=parent_origin.precedence,
                base_dir=parent_origin.base_dir,
            )


def _was_supplied(
    info: FieldInfo,
    values: dict[tuple[str, ...], Any],
    origins: dict[str, Origin],
) -> bool:
    """Whether the child said something itself, rather than falling back."""
    if info.path not in values:
        return False
    origin = origins.get(info.dotted)
    return origin is not None and origin.kind != "default"


def _parent_path(info: FieldInfo) -> tuple[str, ...] | None:
    """The field of the same name one level up, which is what cascades.

    Matching is by field name rather than by any `named()` override: the
    cascade is structural, and a renamed leaf keeps cascading from the field it
    sits beneath.
    """
    if len(info.path) < 2:
        return None
    return (*info.path[:-2], info.path[-1])


def _assemble(
    root: type[ConfigPart],
    values: dict[tuple[str, ...], Any],
    prefix: tuple[str, ...],
) -> Any:
    """Build one part, depth-first, from the winners below it."""
    kwargs: dict[str, Any] = {}
    missing: list[str] = []

    for info in fields_of(root, recurse=False):
        path = (*prefix, info.name)
        if info.is_nested:
            kwargs[info.name] = _assemble(info.type, values, prefix=path)
            continue
        if path in values:
            kwargs[info.name] = values[path]
        elif info.default is MISSING:
            missing.append(".".join(path))

    if missing and not prefix:
        raise MissingConfigError(
            f"{root.__name__} is missing required field(s): "
            f"{', '.join(sorted(missing))}. No source supplied them."
        )

    return root(**kwargs)


def check_cascade_targets(root: type[ConfigPart]) -> None:
    """Raise if a nested `from_parent` field has no parent field of that name.

    A misplaced marker would otherwise look like a cascade that never fires.

    A top-level field carrying the marker is inert rather than wrong: the
    marker is usually written once on a shared base class, and the root that
    inherits it has nothing above it by definition.
    """
    from ._diagnostics import ConfigDeclarationError

    names = {info.path for info in fields_of(root)}
    for info in fields_of(root):
        if info.is_nested or not has_marker(info, FromParentMarker):
            continue
        parent = _parent_path(info)
        if parent is None:
            continue
        if parent not in names:
            raise ConfigDeclarationError(
                f"{root.__name__}.{info.dotted} is marked from_parent, but "
                f"{'.'.join(parent)} does not exist, so the cascade could "
                f"never fire. Declare it, or drop the marker."
            )


__all__ = [
    "Projection",
    "check_cascade_targets",
    "project",
]
