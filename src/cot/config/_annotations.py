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


class BootstrapOnlyMarker(_MarkerMixin):
    """
    Marker to indicate a field that can only be set during bootstrap.

    Fields marked with `bootstrap_only` cannot be set via addopts or other
    late-stage configuration sources. They must be set via CLI args or
    early bootstrap fragments.

    This is useful for fields like config_file where it's too late to
    change them once the config file has been loaded.

    Example:
        class PytestConfig(ConfigPart):
            config_file: Annotated[Path | None, config_source, bootstrap_only] = None
    """

    def __repr__(self) -> str:
        return "<BootstrapOnly>"


bootstrap_only = BootstrapOnlyMarker()


class AddoptsMarker(_MarkerMixin):
    """
    Marker to indicate a field whose value should be re-parsed as CLI args.

    When a field is annotated with `addopts_field`, after loading its value
    from sources, the value will be parsed as CLI arguments and applied to
    other config fields (with precedence between file and CLI).

    Example:
        class PytestConfig(ConfigPart):
            addopts: Annotated[str, addopts_field] = ""
    """

    precedence: int

    def __init__(self, precedence: int = 18) -> None:
        # Default precedence 18: file(15) < addopts(18) < env(20) < cli(25)
        self.precedence = precedence

    def __repr__(self) -> str:
        return f"<AddoptsField precedence={self.precedence}>"


addopts_field = AddoptsMarker()


class ShortMarker(_MarkerMixin):
    """
    Marker to specify a short CLI option for a field.

    When a field is annotated with `short("v")`, it can be set via `-v`
    in addition to the long option `--field-name`.

    Example:
        class PytestConfig(ConfigPart):
            verbose: Annotated[bool, short("v")] = False
    """

    char: str

    def __init__(self, char: str) -> None:
        if len(char) != 1:
            raise ValueError("short option must be a single character")
        self.char = char

    def __repr__(self) -> str:
        return f"<Short -{self.char}>"


def short(char: str) -> ShortMarker:
    """Create a short option marker for CLI parsing."""
    return ShortMarker(char)


__all__ = [
    "FromParentMarker",
    "from_parent",
    "PrefixMarker",
    "HelpMarker",
    "help",
    "ConfigSourceMarker",
    "config_source",
    "BootstrapOnlyMarker",
    "bootstrap_only",
    "AddoptsMarker",
    "addopts_field",
    "ShortMarker",
    "short",
]
