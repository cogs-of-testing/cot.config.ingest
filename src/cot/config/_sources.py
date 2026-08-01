"""Configuration sources for loading from files, environment and arguments."""

from __future__ import annotations

import configparser
import os
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]

from ._annotations import HelpMarker, ShortMarker
from ._coerce import coerce, coerce_parsed
from ._fields import (
    FieldInfo,
    fields_of,
    leaf_fields,
    marker_of,
    markers_of,
    unwrap_type,
)
from ._names import (
    FieldNames,
    cli_visible,
    expand_flat_keys,
    named_leaf_fields,
    part_prefix,
    section_name,
    set_path,
)
from ._origins import Origin
from ._precedence import Precedence

if TYPE_CHECKING:
    from ._bases import ConfigPart
    from ._cli_parser import CLIParser


class TomlSource:
    """Load configuration from a TOML file."""

    def __init__(self, path: Path, *, precedence: int = Precedence.FILE) -> None:
        """
        Create a TOML configuration source.

        Args:
            path: Path to the TOML file
            precedence: Higher values override lower values
        """
        self._path = path
        self._precedence = precedence
        self._data: dict[str, Any] | None = None

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def path(self) -> Path:
        return self._path

    def _load_file(self) -> dict[str, Any]:
        """Load and cache the TOML file contents."""
        if self._data is None:
            if self._path.exists():
                with open(self._path, "rb") as f:
                    self._data = tomllib.load(f)
            else:
                self._data = {}
        return self._data

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type.

        Looks for a section matching the ConfigPart's prefix or class name.

        Both spellings work: a nested sub-table (``[log.cli] level``) and a
        flat prefixed key (``log_cli_level``) reach the same field.
        """
        data = self._load_file()
        section = data.get(section_name(part_type), {})
        return expand_flat_keys(part_type, dict(section))

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Name the file and the key inside it."""
        return _file_origin(self._path, part_type, path, self._precedence)


class IniSource:
    """Load configuration from an INI file (pytest-style)."""

    def __init__(self, path: Path, *, precedence: int = Precedence.FILE) -> None:
        """
        Create an INI configuration source.

        Args:
            path: Path to the INI file
            precedence: Higher values override lower values
        """
        self._path = path
        self._precedence = precedence
        self._parser: configparser.ConfigParser | None = None

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def path(self) -> Path:
        return self._path

    def _load_file(self) -> configparser.ConfigParser:
        """Load and cache the INI file contents."""
        if self._parser is None:
            self._parser = configparser.ConfigParser()
            if self._path.exists():
                self._parser.read(self._path)
        return self._parser

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type.

        Looks for a section matching the ConfigPart class name (case-insensitive).

        INI has no nesting, so flat keys are the only spelling available:
        `log_cli_level` maps onto the nested field `cli.level`.
        """
        parser = self._load_file()
        wanted = section_name(part_type)

        # INI sections are case-insensitive
        section_lower = wanted.lower()
        for section in parser.sections():
            if section.lower() == section_lower:
                return self._parse_section(parser[section], part_type)

        return {}

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Name the file and the flat key inside it."""
        return _file_origin(self._path, part_type, path, self._precedence)

    def _parse_section(
        self,
        section: configparser.SectionProxy,
        part_type: type[ConfigPart],
    ) -> dict[str, Any]:
        """Parse an INI section with type-aware conversion."""
        raw = dict(section.items())
        result = expand_flat_keys(part_type, raw, parse=coerce)

        # Values whose key was a direct field name are still raw strings.
        for field in fields_of(part_type, recurse=False):
            value = result.get(field.name)
            if isinstance(value, str):
                result[field.name] = coerce(value, field.annotation)

        return result


class _ArgvSource:
    """Shared machinery for sources whose input is a list of CLI tokens.

    Two of those exist: the arguments the user typed (:class:`CLISource`) and
    the arguments an ``addopts_field`` contributed (:class:`AddoptsSource`).
    They differ in where the tokens come from, what precedence they carry and
    how they describe themselves -- not in how a token becomes a field value.
    """

    def __init__(self, *, precedence: int) -> None:
        from ._cli_parser import CLIParser

        self._precedence = precedence
        self._parser: CLIParser = CLIParser()
        self._registered_fields: dict[str, Any] = {}

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def tokens(self) -> list[str]:
        """The argument tokens this source parses."""
        raise NotImplementedError

    def declare(self, part_type: type[ConfigPart]) -> None:
        """
        Register a ConfigPart type's fields with the parser.

        Leaf fields are registered, including those nested inside SubConfigs:
        `log.cli.level` becomes `--log-cli-level`. Sub-config containers
        themselves get no option -- there is nothing to type on a command line
        for a whole section.
        """
        for field, field_names in named_leaf_fields(part_type):
            if not cli_visible(field):
                continue
            if field_names.flat in self._registered_fields:
                # Already registered (possibly from another fragment)
                continue

            self._parser.add_field(
                field_names.flat,
                unwrap_type(field.annotation),
                long_option=field_names.cli,
                short=_short_option_of(field.annotation),
                help=_help_text_of(field),
            )
            self._registered_fields[field_names.flat] = field.annotation

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type from the tokens.

        Parses fresh each time (no caching) to handle dynamic field
        registration and tokens arriving after an earlier parse.
        """
        parse_result = self._parser.parse(self.tokens)

        result: dict[str, Any] = {}
        for field, field_names in named_leaf_fields(part_type):
            if field_names.flat not in parse_result.values:
                continue
            set_path(
                result,
                field.path,
                coerce_parsed(parse_result.values[field_names.flat], field.annotation),
            )

        self._apply_overrides(result, part_type, parse_result.overrides)
        return result

    def _apply_overrides(
        self,
        result: dict[str, Any],
        part_type: type[ConfigPart],
        overrides: dict[str, str],
    ) -> None:
        """Apply -o overrides to the result dict.

        The override path is resolved against the field model, so the value is
        converted to the field's declared type. Without that, `-o
        log.cli.enabled=false` would store the string "false", which is truthy.
        """
        prefix = part_prefix(part_type)
        by_path = {field.path: field for field in leaf_fields(part_type)}

        for key, raw_value in overrides.items():
            parts = tuple(key.split("."))

            # A leading segment matching the part's prefix is addressing this
            # part, not a field inside it.
            if prefix and parts and parts[0] == prefix:
                parts = parts[1:]

            field = by_path.get(parts)
            if field is None:
                continue

            set_path(result, parts, coerce(raw_value, field.annotation))

    def _option_display(self, names: FieldNames) -> str:
        """``-v/--verbose`` when a short option exists, ``--verbose`` otherwise."""
        option = f"--{names.cli}"
        spec = self._parser.get_field_by_long(names.cli)
        if spec is not None and spec.short_option:
            return f"-{spec.short_option}/{option}"
        return option


class CLISource(_ArgvSource):
    """
    Load configuration from command-line arguments.

    Flow:
    1. Create CLISource with args and invocation_dir
    2. declare() for each ConfigPart (adds fields to the parser)
    3. load() to get values for each fragment type
    4. get_unknown_args() to get unconsumed args

    Arguments contributed by an ``addopts_field`` are *not* handled here: they
    are a separate source (:class:`AddoptsSource`) sitting one rung lower on
    the precedence ladder, so a typed argument always beats one a config file
    injected.

    Override mechanism:
    Use -o/--override for options that don't have dedicated CLI flags:
        -o log.cli.level=DEBUG -o cache.dir=/tmp/cache
    """

    def __init__(
        self,
        args: list[str] | None = None,
        *,
        invocation_dir: Path | None = None,
        precedence: int = Precedence.CLI,
    ) -> None:
        """
        Create a CLI argument source.

        Args:
            args: Command line arguments (defaults to empty list)
            invocation_dir: Directory where command was invoked (defaults to cwd)
            precedence: Higher values override lower values
        """
        super().__init__(precedence=precedence)
        self._args: list[str] = list(args) if args is not None else []
        if invocation_dir is not None:
            self._invocation_dir: Path = invocation_dir
        else:
            self._invocation_dir = Path.cwd()

    @property
    def invocation_dir(self) -> Path:
        return self._invocation_dir

    @property
    def args(self) -> list[str]:
        """The command line arguments, as given."""
        return list(self._args)

    @property
    def tokens(self) -> list[str]:
        return self._args

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Name the option a value came from."""
        names = _names_by_path(part_type).get(path)
        if names is None:
            return None
        return Origin(
            kind="cli",
            location=self._option_display(names),
            precedence=self._precedence,
        )

    def format_help(self, *, prog: str | None = None) -> str:
        """Render help text for every registered option."""
        return self._parser.format_help(prog=prog)

    def help_requested(self) -> bool:
        """Whether -h/--help appeared in the arguments."""
        return self._parser.parse(self.tokens).help_requested

    def get_unknown_args(self) -> list[str]:
        """
        Get args not consumed by any registered fragment type.

        Returns:
            List of unconsumed command line arguments
        """
        return self._parser.parse(self.tokens).unknown_args

    def get_raw_value(self, field_name: str) -> str | None:
        """
        Get the raw string value for a field from CLI args.

        This is useful for sources that need to check CLI values before
        full type conversion (e.g., ConfigFileDiscoverySource checking
        for config_file path).

        Args:
            field_name: The field name to look up

        Returns:
            Raw string value if present, None otherwise
        """
        value = self._parser.parse(self.tokens).values.get(field_name)
        if isinstance(value, bool):
            return str(value).lower() if value else None
        return value


class AddoptsSource(_ArgvSource):
    """Arguments contributed by ``addopts_field`` values, re-parsed as CLI args.

    This is a source like any other, which is the whole point: ``addopts`` sits
    at its own rung of the precedence ladder (:data:`Precedence.ADDOPTS`, above
    files and the environment, below typed arguments) instead of being spliced
    into ``argv``. Splicing made an injected option indistinguishable from one
    the user typed, and pinned it to CLI precedence no matter what the
    ``addopts_field`` marker asked for.

    Tokens accumulate: several config files, or several ConfigParts, may each
    contribute. Later contributions win, matching the parser's own rule.
    """

    def __init__(self, *, precedence: int = Precedence.ADDOPTS) -> None:
        super().__init__(precedence=precedence)
        self._tokens: list[str] = []

    @property
    def tokens(self) -> list[str]:
        return self._tokens

    def extend(self, addopts: str | list[str]) -> list[str]:
        """Append addopts, splitting a string the way a shell would.

        Returns the tokens that were added, which is what the caller needs in
        order to report on them.
        """
        if isinstance(addopts, str):
            try:
                tokens = shlex.split(addopts)
            except ValueError:
                tokens = addopts.split()
        else:
            tokens = [str(item) for item in addopts]

        self._tokens.extend(tokens)
        return tokens

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Name the option, and say that nobody typed it.

        An option injected through ``addopts`` looks identical to a typed one
        once parsed, which is exactly the confusion this reports away: an
        option nobody typed is the hardest kind to debug.
        """
        names = _names_by_path(part_type).get(path)
        if names is None:
            return None
        return Origin(
            kind="addopts",
            location=f"addopts {self._option_display(names)}",
            precedence=self._precedence,
        )


class EnvSource:
    """Load configuration from environment variables.

    Supports TOML parsing for complex values:
        APP_DATABASE='host = "localhost"\\nport = 5432'

    When parse_toml=True, values that look like TOML (contain = or start with
    [ or {) are parsed as TOML. This allows setting nested config from a single
    env var.
    """

    def __init__(
        self,
        prefix: str = "",
        *,
        precedence: int = Precedence.ENV,
        environ: dict[str, str] | None = None,
        parse_toml: bool = False,
    ) -> None:
        """
        Create an environment variable configuration source.

        Args:
            prefix: Prefix for environment variables (e.g., "APP" -> APP_*).
                A ConfigPart's own ``prefix=`` is appended to this one, so an
                application can namespace every variable it reads.
            precedence: Higher values override lower values
            environ: Environment dict to use (defaults to os.environ)
            parse_toml: If True, attempt to parse values as TOML for complex types
        """
        self._prefix = prefix.upper()
        self._precedence = precedence
        self._environ = environ if environ is not None else os.environ
        self._parse_toml = parse_toml

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def prefix(self) -> str:
        return self._prefix

    def effective_prefix(self, part_type: type[ConfigPart]) -> str:
        """The variable prefix for one ConfigPart: source prefix, then part prefix.

        The two compose rather than one shadowing the other. ``EnvSource("APP")``
        reading a part declared ``prefix="log"`` looks at ``APP_LOG_*``: an
        application that namespaces its environment keeps that namespace even
        for parts that name a config-file section of their own.
        """
        segments = [
            segment for segment in (self._prefix, part_prefix(part_type)) if segment
        ]
        return "_".join(segments).upper()

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type from environment.

        Maps environment variables to field names:
        - PREFIX_FIELD_NAME -> field_name
        - PREFIX_NESTED_FIELD -> {"nested": {"field": value}}
        - Handles type conversion based on annotations
        - If parse_toml=True, values can be TOML for complex types
        """
        result: dict[str, Any] = {}
        effective_prefix = self.effective_prefix(part_type)

        for field, field_names in named_leaf_fields(part_type):
            env_name = _field_to_env_name(field_names.env, effective_prefix)
            if env_name in self._environ:
                raw_value = self._environ[env_name]
                set_path(
                    result,
                    field.path,
                    self._parse_value(raw_value, field.annotation),
                )

        return result

    def describe_origin(
        self, part_type: type[ConfigPart], path: tuple[str, ...]
    ) -> Origin | None:
        """Name the environment variable a value came from."""
        names = _names_by_path(part_type).get(path)
        if names is None:
            return None
        return Origin(
            kind="env",
            location=_field_to_env_name(names.env, self.effective_prefix(part_type)),
            precedence=self._precedence,
        )

    def _parse_value(self, raw_value: str, field_type: Any) -> Any:
        """Parse a value, optionally trying TOML parsing first."""
        if self._parse_toml and self._looks_like_toml(raw_value):
            try:
                # Wrap in a key to make it valid TOML
                parsed = tomllib.loads(f"value = {raw_value}")
                return parsed.get("value", raw_value)
            except Exception:
                pass
        return coerce(raw_value, field_type)

    def _looks_like_toml(self, value: str) -> bool:
        """Check if a value looks like it might be TOML."""
        value = value.strip()
        # Check for inline table, array, or quoted string
        return (
            value.startswith("{")
            or value.startswith("[")
            or value.startswith('"')
            or value.startswith("'")
            or "=" in value
        )


def _field_to_env_name(field_name: str, prefix: str) -> str:
    """Convert a field name to an environment variable name."""
    env_name = field_name.upper()
    if prefix:
        return f"{prefix.upper()}_{env_name}"
    return env_name


def _short_option_of(annotation: Any) -> str | None:
    """Extract the short option character from an annotation, if marked."""
    for marker in markers_of(annotation):
        if isinstance(marker, ShortMarker):
            return marker.char
    return None


def _names_by_path(part_type: type[ConfigPart]) -> dict[tuple[str, ...], FieldNames]:
    """Index a ConfigPart's leaf field names by structural path."""
    return {field.path: names for field, names in named_leaf_fields(part_type)}


def _file_origin(
    path: Path,
    part_type: type[ConfigPart],
    field_path: tuple[str, ...],
    precedence: int,
) -> Origin:
    """Build a file origin naming both the file and the key inside it."""
    names = _names_by_path(part_type).get(field_path)
    key = names.flat if names is not None else ".".join(field_path)
    return Origin(kind="file", location=f"{path}[{key}]", precedence=precedence)


def _help_text_of(field: FieldInfo) -> str | None:
    """Extract the help text from a field, if marked."""
    marker = marker_of(field, HelpMarker)
    return marker.help if marker is not None else None


class ConfigFileDiscoverySource:
    """
    Meta-source that discovers config files and delegates to TomlSource/IniSource.

    This source:
    1. Looks for explicit config file from CLI (--config-file) or env (PREFIX_CONFIG)
    2. If not found, discovers config files in invocation_dir and ancestors
    3. Creates appropriate sources (TOML, INI) for found files
    4. Determines rootdir based on config file location

    Example:
        cli = CLISource(args=sys.argv[1:], invocation_dir=Path.cwd())
        env = EnvSource(prefix="PYTEST")
        files = ConfigFileDiscoverySource(
            cli_source=cli,
            env_source=env,
            invocation_dir=cli.invocation_dir,
            filenames=["pyproject.toml", "pytest.ini", "setup.cfg"],
        )
    """

    def __init__(
        self,
        *,
        invocation_dir: Path,
        cli_source: CLISource | None = None,
        env_source: EnvSource | None = None,
        filenames: list[str] | None = None,
        config_file_cli_arg: str = "config_file",
        config_file_env_var: str | None = None,
        precedence: int = Precedence.FILE,
    ) -> None:
        """
        Create a config file discovery source.

        Args:
            invocation_dir: Directory to start searching from
            cli_source: CLI source to check for --config-file
            env_source: Env source to check for CONFIG env var
            filenames: Config filenames to look for (default: pyproject.toml, setup.cfg)
            config_file_cli_arg: CLI arg name for explicit config file
            config_file_env_var: Env var name for explicit config file
            precedence: Higher values override lower values
        """
        self._invocation_dir = invocation_dir
        self._cli_source = cli_source
        self._env_source = env_source
        self._filenames = filenames or ["pyproject.toml", "setup.cfg"]
        self._config_file_cli_arg = config_file_cli_arg
        self._config_file_env_var = config_file_env_var
        self._precedence = precedence
        self._discovered_source: TomlSource | IniSource | None = None
        self._rootdir: Path | None = None
        self._config_file: Path | None = None

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def rootdir(self) -> Path | None:
        """The determined rootdir (directory containing config file)."""
        self._ensure_discovered()
        return self._rootdir

    @property
    def config_file(self) -> Path | None:
        """The discovered or specified config file path."""
        self._ensure_discovered()
        return self._config_file

    def _ensure_discovered(self) -> None:
        """Discover config file if not already done."""
        if self._discovered_source is not None or self._config_file is not None:
            return

        # 1. Check CLI for explicit config file
        config_path = self._get_config_from_cli()

        # 2. Check env for explicit config file
        if config_path is None:
            config_path = self._get_config_from_env()

        # 3. Auto-discover config file
        if config_path is None:
            config_path = self._discover_config_file()

        if config_path is not None:
            self._config_file = config_path
            self._rootdir = config_path.parent
            self._discovered_source = self._create_source(config_path)

    def _get_config_from_cli(self) -> Path | None:
        """Get config file path from CLI args."""
        if self._cli_source is None:
            return None

        # Get config file value from CLI
        value = self._cli_source.get_raw_value(self._config_file_cli_arg)
        if value is not None:
            path = Path(value)
            if not path.is_absolute():
                path = self._invocation_dir / path
            if not path.exists():
                raise FileNotFoundError(
                    f"Config file not found: {path} "
                    f"(specified via --{self._config_file_cli_arg.replace('_', '-')})"
                )
            return path
        return None

    def _get_config_from_env(self) -> Path | None:
        """Get config file path from environment variable."""
        if self._env_source is None or self._config_file_env_var is None:
            return None

        value = self._env_source._environ.get(self._config_file_env_var)
        if value is not None:
            path = Path(value)
            if not path.is_absolute():
                path = self._invocation_dir / path
            if not path.exists():
                raise FileNotFoundError(
                    f"Config file not found: {path} "
                    f"(specified via {self._config_file_env_var})"
                )
            return path
        return None

    def _discover_config_file(self) -> Path | None:
        """Search for config file in invocation_dir and ancestors."""
        current = self._invocation_dir
        while True:
            for filename in self._filenames:
                candidate = current / filename
                if candidate.exists():
                    return candidate

            parent = current.parent
            if parent == current:  # Reached root
                break
            current = parent

        return None

    def _create_source(self, path: Path) -> TomlSource | IniSource:
        """Create appropriate source for the config file type."""
        if path.suffix in (".ini", ".cfg"):
            return IniSource(path, precedence=self._precedence)
        # Default to TOML for .toml and unknown extensions
        return TomlSource(path, precedence=self._precedence)

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """Load configuration from discovered config file."""
        self._ensure_discovered()
        if self._discovered_source is None:
            return {}
        return self._discovered_source.load(part_type)


__all__ = [
    "AddoptsSource",
    "CLISource",
    "ConfigFileDiscoverySource",
    "EnvSource",
    "IniSource",
    "TomlSource",
]
