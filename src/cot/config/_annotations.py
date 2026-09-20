"""Annotation helpers for configuration fields."""

from __future__ import annotations

from typing import Annotated, Any

from ._fields import MISSING
from ._precedence import Precedence


class Marker:
    """Base of every marker this library defines.

    Being one is what makes a marker the library's business: it is how a
    misplaced marker is told from a third party's ``Annotated`` extra, which is
    none of our concern.
    """

    def __rmatmul__(self, other: object) -> object:
        return Annotated[other, self]

    def __eq__(self, other: object) -> bool:
        # A marker is a value: `named("x")` written in two classes is the same
        # marker. Identity comparison would make two roots' annotations differ
        # for no reason a reader could see, and adoption would be unreachable.
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        return hash((type(self), tuple(sorted(self.__dict__.items()))))


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


class InjectedArgsMarker(Marker):
    """
    A field whose value is re-parsed as command-line tokens.

    The value becomes a source of its own at ``precedence``: above config files
    and the environment, below the arguments the user actually typed. pytest's
    ``addopts`` is the motivating instance; the marker is named for the
    capability, so that no host's word for it sits in the core.

    Example:
        class PytestConfig(ConfigPart):
            addopts: Annotated[str, injected_args] = ""
    """

    precedence: int

    def __init__(self, precedence: int = Precedence.ADDOPTS) -> None:
        self.precedence = precedence

    def __repr__(self) -> str:
        return f"<InjectedArgs precedence={self.precedence}>"


injected_args = InjectedArgsMarker()


class NoIniMarker(Marker):
    """
    Mark a field as having no file spelling.

    The mirror of `no_cli`. A host that wants command-line-only options, or
    that scopes an override flag to file-backed fields, needs "has a file
    spelling" to be able to be false.

    Example:
        class RunConfig(ConfigPart):
            dry_run: Annotated[bool, no_ini] = False
    """

    def __repr__(self) -> str:
        return "<NoIni>"


no_ini = NoIniMarker()


class FromEnvMarker(Marker):
    """
    Give a field, or a nested part's whole subtree, an environment spelling.

    Exposure is opt-in: the environment is the one source nobody declares, so
    a field is readable from it only when someone decided it should be. On a
    nested field the marker opts in everything beneath it, which is what gives
    a variable holding a whole table its definition.

    Example:
        class DatabaseConfig(ConfigPart, prefix="app"):
            host: Annotated[str, from_env] = "localhost"
            password: str = ""              # not environment-readable
    """

    def __repr__(self) -> str:
        return "<FromEnv>"


from_env = FromEnvMarker()


class EnvNamedMarker(Marker):
    """
    Pin an absolute environment variable name: no prefix, no derivation.

    For cross-tool conventions that every tool must spell identically.
    `named()` cannot serve, because the environment spelling is derived from
    the flat name it replaces. A field carrying this still needs `from_env` to
    be read at all.

    Example:
        class BuildConfig(ConfigPart):
            epoch: Annotated[
                int | None, from_env, env_named("SOURCE_DATE_EPOCH")
            ] = None
    """

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<EnvNamed {self.name!r}>"


def env_named(name: str) -> EnvNamedMarker:
    """Pin an absolute environment variable name for a field."""
    return EnvNamedMarker(name)


class FormerlyMarker(Marker):
    """
    Declare a legacy flat spelling the field is still reachable under.

    A value arriving that way warns. This is the only way an alias comes to
    exist: `named()` replaces the derived name and leaves nothing behind.

    Example:
        class FileConfig(ConfigPart):
            version_file: Annotated[str | None, formerly("write_to")] = None
    """

    name: str

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"<Formerly {self.name!r}>"


def formerly(name: str) -> FormerlyMarker:
    """Declare a legacy flat spelling for a field."""
    return FormerlyMarker(name)


class CountedMarker(Marker):
    """
    Occurrences of any of the field's CLI forms are summed.

    Nothing in the annotation implies it: `-j 4` and `-v -v` are both `int`
    with a short option.

    Example:
        class RunConfig(ConfigPart):
            verbosity: Annotated[int, short("v"), counted] = 0
    """

    def __repr__(self) -> str:
        return "<Counted>"


counted = CountedMarker()


class FormMarker(Marker):
    """
    Add a further command-line form to a field, optionally with a constant.

    One path can be addressed by several option strings with different
    behaviour: pytest's `maxfail` is `--maxfail N` and also `-x`, which
    supplies the constant 1. The first form is derived from the qualified path
    and `short()`; each `form()` adds one more.

    Example:
        class RunConfig(ConfigPart):
            maxfail: Annotated[int, form("--exitfirst", short="x", contributes=1)] = 0
    """

    long: str | None
    short: str | None
    contributes: Any

    def __init__(
        self,
        long: str | None = None,
        *,
        short: str | None = None,
        contributes: Any = MISSING,
    ) -> None:
        if long is None and short is None:
            raise ValueError("a form needs a long option, a short option, or both")
        if long is not None and not long.startswith("--"):
            raise ValueError(f"a long option starts with '--', got {long!r}")
        if short is not None and len(short) != 1:
            raise ValueError("short option must be a single character")
        self.long = long
        self.short = short
        self.contributes = contributes

    def __repr__(self) -> str:
        return f"<Form {self.long or ''}{'/-' + self.short if self.short else ''}>"


def form(
    long: str | None = None,
    *,
    short: str | None = None,
    contributes: Any = MISSING,
) -> FormMarker:
    """Add a further command-line form, optionally supplying a constant."""
    return FormMarker(long, short=short, contributes=contributes)


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
    "InjectedArgsMarker",
    "injected_args",
    "ShortMarker",
    "short",
    "NoIniMarker",
    "no_ini",
    "FromEnvMarker",
    "from_env",
    "EnvNamedMarker",
    "env_named",
    "FormerlyMarker",
    "formerly",
    "CountedMarker",
    "counted",
    "FormMarker",
    "form",
]
