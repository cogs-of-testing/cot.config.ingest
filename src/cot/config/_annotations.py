"""Annotation helpers for configuration fields."""

from __future__ import annotations

from typing import Annotated


class _MarkerMixin:
    def __rmatmul__(self, other: object) -> object:
        return Annotated[other, self]


class FromParentMarker(_MarkerMixin):
    """marker to indicate fields to load from a parent configuration"""

    pass


from_parent = FromParentMarker()


class PrefixMarker(_MarkerMixin):
    """indicate a prefix that should be used for the fields of a sub-configuration."""

    prefix: str

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def __repr__(self) -> str:
        return f"<Prefix {self.prefix!r}>"


class HelpMarker(_MarkerMixin):
    """marker to provide help text for configuration fields."""

    help: str

    def __init__(self, help: str) -> None:
        self.help = help

    def __repr__(self) -> str:
        return f"<Help {self.help!r}>"


def help(text: str) -> HelpMarker:
    """Helper function to create a HelpMarker."""
    return HelpMarker(text)


class ConfigSourceMarker(_MarkerMixin):
    """
    Marker to indicate a field whose value should become a config source.

    When a field is annotated with `config_source`, its value (typically a
    Path to a config file) will be automatically added as a source during
    registration.

    Example:
        class InvocationConfig(ConfigPart):
            config_file: Annotated[Path | None, config_source] = None
    """

    precedence: int

    def __init__(self, precedence: int = 15) -> None:
        self.precedence = precedence

    def __repr__(self) -> str:
        return f"<ConfigSource precedence={self.precedence}>"


config_source = ConfigSourceMarker()


__all__ = [
    "FromParentMarker",
    "from_parent",
    "PrefixMarker",
    "HelpMarker",
    "help",
    "ConfigSourceMarker",
    "config_source",
]
