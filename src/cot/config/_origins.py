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
from pathlib import Path
from typing import Literal

from ._precedence import Precedence

OriginKind = Literal["default", "file", "env", "cli", "injected", "override", "runtime"]


@dataclass(frozen=True)
class Origin:
    """The provenance of a single configuration value."""

    kind: OriginKind
    """Broad category of source."""

    location: str
    """Where exactly: a file path, an env var name, a CLI option."""

    precedence: int
    """The precedence that let this value win."""

    base_dir: Path | None = None
    """What a relative path in this value is relative to, when that is known.

    A config file's values are relative to that file; the command line's are
    relative to the invocation directory. A source that knows says so, and the
    ``Path`` conversion is the one thing that reads it.
    """

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


__all__ = [
    "DEFAULT_ORIGIN_PRECEDENCE",
    "Origin",
    "OriginKind",
    "default_origin",
]
