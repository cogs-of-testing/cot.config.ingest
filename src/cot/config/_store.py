"""What every source said, kept per path, in ladder order.

Sources yield a reading per value they can place, so there is no dict merge,
deep or shallow: a command-line option for ``("file", "level")`` and a file
table for ``("file",)`` never meet as structures, only as rows for different
paths.

Every reading is converted as it enters, with its origin in hand, so nothing
downstream of the store ever sees a raw value. Losing layers are kept rather
than discarded, which is what lets provenance be a projection of the store, and
what lets a host expose per-layer accessors -- pytest's ``getoption`` and
``getini`` are that pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from ._convert import check, convert
from ._diagnostics import ConfigValueError, ShadowedValueWarning
from ._fields import fields_of

if TYPE_CHECKING:
    from ._bases import ConfigPart
    from ._diagnostics import Diagnostics
    from ._origins import Origin

Dialect = Literal["string", "typed"]


@dataclass(frozen=True)
class Reading:
    """One value a source could place, already resolved to a field."""

    root: type[ConfigPart]
    path: tuple[str, ...]
    raw: Any
    location: str
    """Where exactly: ``pytest.ini[log_level]``, ``--log-level``, ``APP_DB_HOST``."""


@dataclass(frozen=True)
class Unmatched:
    """A spelling a source saw that the index resolved to nothing."""

    spelling: str
    location: str


@dataclass(frozen=True)
class LayeredValue:
    """One source's contribution to one path, converted."""

    value: Any
    origin: Origin


@dataclass(frozen=True)
class FailedValue:
    """A reading that could not become the field's declared type.

    Kept rather than dropped, because whether it is an error depends on what it
    would have done: a failure that wins raises, and one that loses is still a
    broken file the day the override goes away.
    """

    raw: Any
    origin: Origin
    error: ConfigValueError


Layer = LayeredValue | FailedValue


@dataclass
class LayeredStore:
    """Every layer of every path, for every declared root."""

    layers_by_path: dict[tuple[type[ConfigPart], tuple[str, ...]], list[Layer]] = field(
        default_factory=dict
    )

    def add(self, reading: Reading, origin: Origin, dialect: Dialect) -> None:
        """Convert a reading and keep it, whether or not it will win."""
        annotation = _annotation_of(reading.root, reading.path)
        interpret = convert if dialect == "string" else check

        layer: Layer
        try:
            layer = LayeredValue(
                value=interpret(reading.raw, annotation, origin), origin=origin
            )
        except ConfigValueError as error:
            layer = FailedValue(raw=reading.raw, origin=origin, error=error)

        self.layers_by_path.setdefault((reading.root, reading.path), []).append(layer)

    def layers(
        self, root: type[ConfigPart], path: tuple[str, ...]
    ) -> tuple[Layer, ...]:
        """Every source that supplied this path, lowest rung first."""
        held = self.layers_by_path.get((root, path), [])
        return tuple(sorted(held, key=lambda layer: layer.origin.precedence))

    def winner(self, root: type[ConfigPart], path: tuple[str, ...]) -> Layer | None:
        """The layer the fragment gets, or None when nobody supplied one."""
        held = self.layers(root, path)
        return held[-1] if held else None

    def paths(self, root: type[ConfigPart]) -> tuple[tuple[str, ...], ...]:
        """Every path this store holds a layer for, for one root."""
        return tuple(path for (held, path) in self.layers_by_path if held is root)

    def report_failures(self, root: type[ConfigPart], diagnostics: Diagnostics) -> None:
        """Judge every failed layer by what it would have done.

        A failure that wins its path is an error. One a higher layer shadows is
        a warning naming what shadowed it: the run can continue, and the day
        the override goes away the file is still broken.
        """
        for path in self.paths(root):
            held = self.layers(root, path)
            top = held[-1]
            for layer in held:
                if not isinstance(layer, FailedValue):
                    continue
                if layer is top:
                    diagnostics.add(ConfigValueError, str(layer.error))
                else:
                    diagnostics.add(
                        ShadowedValueWarning,
                        f"{str(layer.error)}; it lost to {top.origin}, so the "
                        f"run continues, but the value is still wrong",
                    )


def _annotation_of(root: type[ConfigPart], path: tuple[str, ...]) -> Any:
    for info in fields_of(root):
        if info.path == path:
            return info.annotation
    raise KeyError(f"{root.__name__} has no field at {'.'.join(path)}")


__all__ = [
    "Dialect",
    "FailedValue",
    "Layer",
    "LayeredStore",
    "LayeredValue",
    "Reading",
    "Unmatched",
]
