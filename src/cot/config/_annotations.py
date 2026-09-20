"""Annotation helpers for configuration fields."""

from __future__ import annotations

from typing import Annotated

from ._precedence import Precedence


class Marker:
    """Base of every marker this library defines.

    Being one is what makes a marker the library's business: it is how a
    misplaced marker is told from a third party's ``Annotated`` extra, which is
    none of our concern.
    """

    def __rmatmul__(self, other: object) -> object:
        return Annotated[other, self]


class FromParentMarker(Marker):
    """marker to indicate fields to load from a parent configuration"""

    pass


from_parent = FromParentMarker()


class NameMarker(Marker):
    """
    Override the derived name of a single field in every source.

    Needed where a field's structural path and its conventional name diverge.
    pytest calls the log file's path `log_file`, but structurally it is
    `file.path`, which would derive `log_file_path`.

    Example:
        class LogFileConfig(ConfigPart):
            path: Annotated[str | None, named("log_file")] = None
    """

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<Name {self.name!r}>"


def named(name: str) -> NameMarker:
    """Give a field an explicit name, overriding the derived one."""
    return NameMarker(name)


class NoCLIMarker(Marker):
    """
    Mark a field as unreachable from the command line.

    Some options are deliberately file-only. pytest's `log_cli` is an ini
    option with no CLI flag: live logging is switched on via
    `--log-cli-level` instead.

    Example:
        class LogCliConfig(ConfigPart):
            enabled: Annotated[bool, no_cli] = False
    """

    def __repr__(self) -> str:
        return "<NoCLI>"


no_cli = NoCLIMarker()


class HelpMarker(Marker):
    """marker to provide help text for configuration fields."""

    help: str

    def __init__(self, help: str) -> None:
        self.help = help

    def __repr__(self) -> str:
        return f"<Help {self.help!r}>"


def help(text: str) -> HelpMarker:
    """Helper function to create a HelpMarker."""
    return HelpMarker(text)


class ConfigSourceMarker(Marker):
    """
    Marker to indicate a field whose value should become a config source.

    When a field is annotated with `config_source`, its value (typically a
    Path to a config file) will be automatically added as a source during
    registration.

    Example:
        class PytestConfig(ConfigPart):
            config_file: Annotated[Path | None, config_source] = None
    """

    precedence: int

    def __init__(self, precedence: int = Precedence.FILE) -> None:
        self.precedence = precedence

    def __repr__(self) -> str:
        return f"<ConfigSource precedence={self.precedence}>"


config_source = ConfigSourceMarker()


class BootstrapOnlyMarker(Marker):
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


class AddoptsMarker(Marker):
    """
    Marker to indicate a field whose value should be re-parsed as CLI args.

    When a field is annotated with `addopts_field`, after loading its value
    from sources, the value will be parsed as CLI arguments and applied to
    other config fields (with precedence between file and CLI).

    The value becomes an ``AddoptsSource`` at ``precedence``: above config
    files and the environment, below the arguments the user actually typed.

    Example:
        class PytestConfig(ConfigPart):
            addopts: Annotated[str, addopts_field] = ""
    """

    precedence: int

    def __init__(self, precedence: int = Precedence.ADDOPTS) -> None:
        self.precedence = precedence

    def __repr__(self) -> str:
        return f"<AddoptsField precedence={self.precedence}>"


addopts_field = AddoptsMarker()


class ShortMarker(Marker):
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
    "Marker",
    "FromParentMarker",
    "from_parent",
    "NameMarker",
    "named",
    "NoCLIMarker",
    "no_cli",
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
