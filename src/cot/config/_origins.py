"""Where a configuration value came from.

The point of merging several sources is that the winner is not obvious. When
`log_cli_level` ends up as `DEBUG`, the question "which of the four places that
mention it won, and why" has to be answerable -- otherwise debugging a
misconfigured run means guessing.

Origins are recorded by the manager as it merges, so sources need no changes:
a source that says nothing about itself is still attributed by class and
precedence. A source that can be more specific implements `describe_origin`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from ._precedence import Precedence

OriginKind = Literal["default", "file", "env", "cli", "addopts", "override"]


@dataclass(frozen=True)
class Origin:
    """The provenance of a single configuration value."""

    kind: OriginKind
    """Broad category of source."""

    location: str
    """Where exactly: a file path, an env var name, a CLI option."""

    precedence: int
    """The precedence that let this value win."""

    def __str__(self) -> str:
        return f"{self.kind}:{self.location}"


DEFAULT_ORIGIN_PRECEDENCE = Precedence.DEFAULTS


def default_origin(field_dotted: str) -> Origin:
    """The origin used for values that no source supplied."""
    return Origin(
        kind="default",
        location=f"{field_dotted} default",
        precedence=DEFAULT_ORIGIN_PRECEDENCE,
    )


@runtime_checkable
class OriginAware(Protocol):
    """Optional protocol: a source that can name where a value came from.

    Sources that do not implement this are still tracked -- the manager falls
    back to a generic origin built from the source's class and precedence.
    """

    def describe_origin(
        self, part_type: type[Any], path: tuple[str, ...]
    ) -> Origin | None:
        """Describe where ``path`` came from, or None if this source has no value."""
        ...


def generic_origin(source: Any) -> Origin:
    """Attribute a value to a source that does not describe itself."""
    kind: OriginKind = "file"
    name = type(source).__name__
    if "Env" in name:
        kind = "env"
    elif "Addopts" in name:
        kind = "addopts"
    elif "CLI" in name:
        kind = "cli"

    location = name
    path = getattr(source, "path", None)
    if path is not None:
        location = str(path)

    return Origin(kind=kind, location=location, precedence=source.precedence)


__all__ = [
    "DEFAULT_ORIGIN_PRECEDENCE",
    "Origin",
    "OriginAware",
    "OriginKind",
    "default_origin",
    "generic_origin",
]
