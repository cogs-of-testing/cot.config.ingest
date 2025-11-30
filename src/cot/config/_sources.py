"""Configuration sources for loading from files and environment."""

from __future__ import annotations

import configparser
import os
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union, get_origin, get_type_hints

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

from ._annotations import PrefixMarker, ShortMarker

if TYPE_CHECKING:
    from ._bases import ConfigPart, SubConfig


class TomlSource:
    """Load configuration from a TOML file."""

    def __init__(self, path: Path, *, precedence: int = 10) -> None:
        """
        Create a TOML configuration source.

        Args:
            path: Path to the TOML file
            precedence: Higher values override lower values (default: 10)
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

        Looks for a section matching the ConfigPart class name.
        """
        data = self._load_file()
        section_name = _get_section_name(part_type)
        return dict(data.get(section_name, {}))


class IniSource:
    """Load configuration from an INI file (pytest-style)."""

    def __init__(self, path: Path, *, precedence: int = 10) -> None:
        """
        Create an INI configuration source.

        Args:
            path: Path to the INI file
            precedence: Higher values override lower values (default: 10)
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
        Handles INI-specific parsing:
        - Boolean values: true/false, yes/no, on/off, 1/0
        - Lists: newline-separated values
        """
        parser = self._load_file()
        section_name = _get_section_name(part_type)

        # INI sections are case-insensitive
        section_lower = section_name.lower()
        for section in parser.sections():
            if section.lower() == section_lower:
                return self._parse_section(parser[section], part_type)

        return {}

    def _parse_section(
        self,
        section: configparser.SectionProxy,
        part_type: type[ConfigPart],
    ) -> dict[str, Any]:
        """Parse an INI section with type-aware conversion."""
        result: dict[str, Any] = {}
        type_hints = _get_resolved_type_hints(part_type)

        for key, raw_value in section.items():
            field_type = type_hints.get(key)
            result[key] = _parse_ini_value(raw_value, field_type)

        return result


class CLISource:
    """
    Load configuration from command-line arguments.

    CLISource manages CLI argument parsing with support for:
    - Initial args and invocation_dir passed directly to constructor
    - Addopts prepended from config files/env
    - Dynamic field registration from ConfigPart types
    - Generic -o/--override for any config option
    - Tracking of unknown/unconsumed args

    Flow:
    1. Create CLISource with args and invocation_dir
    2. register_fragment_type() for each ConfigPart (adds fields to parser)
    3. prepend_addopts() after loading config files
    4. freeze_sources() to prevent further addopts
    5. load() to get values for each fragment type
    6. get_unknown_args() to get unconsumed args

    Override mechanism:
    Use -o/--override for options that don't have dedicated CLI flags:
        -o log.cli.level=DEBUG -o cache.dir=/tmp/cache
    """

    def __init__(
        self,
        args: list[str] | None = None,
        *,
        invocation_dir: Path | None = None,
        precedence: int = 25,
    ) -> None:
        """
        Create a CLI argument source.

        Args:
            args: Command line arguments (defaults to empty list)
            invocation_dir: Directory where command was invoked (defaults to cwd)
            precedence: Higher values override lower values (default: 25)
        """
        from ._cli_parser import CLIParser

        self._precedence = precedence
        self._initial_args: list[str] = list(args) if args is not None else []
        self._addopts: list[str] = []
        if invocation_dir is not None:
            self._invocation_dir: Path = invocation_dir
        else:
            self._invocation_dir = Path.cwd()
        self._parser = CLIParser()
        self._registered_fields: dict[str, type[Any]] = {}  # field_name -> field_type
        self._sources_frozen: bool = False

    def prepend_addopts(self, addopts: str | list[str]) -> None:
        """
        Prepend addopts to the argument list (like pytest's PYTEST_ADDOPTS).

        Args:
            addopts: Additional options as string or list

        Raises:
            RuntimeError: If called after sources are frozen
        """
        if self._sources_frozen:
            raise RuntimeError("Cannot add addopts after config sources are frozen")

        if isinstance(addopts, str):
            import shlex

            try:
                parsed = shlex.split(addopts)
            except ValueError:
                parsed = addopts.split()
            self._addopts = parsed + self._addopts
        else:
            self._addopts = list(addopts) + self._addopts

    def freeze_sources(self) -> None:
        """
        Freeze config sources - no more addopts can be added after this.

        Called after bootstrap phase is complete.
        """
        self._sources_frozen = True

    def register_fragment_type(self, part_type: type[ConfigPart]) -> None:
        """
        Register a ConfigPart type's fields with the parser.

        This adds the type's fields to the parser so they can be
        parsed from CLI args. Fields are registered dynamically and
        the parser re-parses on each load() call.

        Args:
            part_type: ConfigPart class to register
        """
        type_hints = _get_resolved_type_hints(part_type)

        for field_name, field_type in type_hints.items():
            if field_name in self._registered_fields:
                # Already registered (possibly from another fragment)
                continue

            # Handle Optional types to get actual type
            actual_type = _unwrap_optional(field_type)

            # Extract short option from annotations if present
            short_opt = _get_short_option(field_type)

            # Register with parser
            self._parser.add_field(field_name, actual_type, short=short_opt)
            self._registered_fields[field_name] = field_type

    @property
    def precedence(self) -> int:
        return self._precedence

    @property
    def invocation_dir(self) -> Path:
        return self._invocation_dir

    @property
    def args(self) -> list[str]:
        """Final args: addopts prepended to initial args."""
        return self._addopts + self._initial_args

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type from CLI args.

        Parses args fresh each time (no caching) to handle dynamic
        field registration and addopts changes.

        Args:
            part_type: ConfigPart class to load data for

        Returns:
            Dict of field names to values from CLI args
        """
        # Parse args (fresh each time - parser handles field registration)
        parse_result = self._parser.parse(self.args)

        result: dict[str, Any] = {}
        type_hints = _get_resolved_type_hints(part_type)

        # Get prefix for this part type (for -o override matching)
        prefix = _get_part_prefix(part_type)

        # Load from dedicated CLI flags
        for field_name, field_type in type_hints.items():
            if field_name in parse_result.values:
                raw_value = parse_result.values[field_name]
                actual_type = _unwrap_optional(field_type)

                # Convert value if needed (booleans are already converted)
                if actual_type is not bool and isinstance(raw_value, str):
                    result[field_name] = _parse_value(raw_value, actual_type)
                else:
                    result[field_name] = raw_value

        # Apply -o overrides (they have highest precedence)
        self._apply_overrides(result, type_hints, prefix, parse_result.overrides)

        return result

    def _apply_overrides(
        self,
        result: dict[str, Any],
        type_hints: dict[str, Any],
        prefix: str | None,
        overrides: dict[str, str],
    ) -> None:
        """Apply -o overrides to the result dict."""
        for key, raw_value in overrides.items():
            # Handle prefixed keys (e.g., "pytest.verbose" or "log.cli.level")
            parts = key.split(".")

            # Check if first part matches prefix
            if prefix and parts[0] == prefix:
                parts = parts[1:]  # Remove prefix

            if len(parts) == 1:
                # Simple field: -o verbose=true or -o pytest.verbose=true
                field_name = parts[0]
                if field_name in type_hints:
                    field_type = type_hints[field_name]
                    result[field_name] = _parse_value(raw_value, field_type)
            else:
                # Nested field: -o log.cli.level=DEBUG
                # Build nested dict structure
                field_name = parts[0]
                if field_name in type_hints:
                    if field_name not in result:
                        result[field_name] = {}
                    if isinstance(result[field_name], dict):
                        self._set_nested(result[field_name], parts[1:], raw_value)

    def _set_nested(
        self, target: dict[str, Any], parts: list[str], value: str
    ) -> None:
        """Set a nested value in a dict using dotted path parts."""
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = value

    def get_unknown_args(self) -> list[str]:
        """
        Get args not consumed by any registered fragment type.

        Returns:
            List of unconsumed command line arguments
        """
        parse_result = self._parser.parse(self.args)
        return parse_result.unknown_args

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
        parse_result = self._parser.parse(self.args)
        value = parse_result.values.get(field_name)
        if isinstance(value, bool):
            return str(value).lower() if value else None
        return value


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
        precedence: int = 20,
        environ: dict[str, str] | None = None,
        parse_toml: bool = False,
    ) -> None:
        """
        Create an environment variable configuration source.

        Args:
            prefix: Prefix for environment variables (e.g., "APP" -> APP_*)
            precedence: Higher values override lower values (default: 20)
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

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load configuration data for a ConfigPart type from environment.

        Maps environment variables to field names:
        - PREFIX_FIELD_NAME -> field_name
        - PREFIX_NESTED_FIELD -> {"nested": {"field": value}}
        - Handles type conversion based on annotations
        - If parse_toml=True, values can be TOML for complex types
        """
        from ._bases import SubConfig

        result: dict[str, Any] = {}
        type_hints = _get_resolved_type_hints(part_type)

        # Get prefix from ConfigPart class markers if set
        part_prefix = _get_part_prefix(part_type)
        effective_prefix = part_prefix or self._prefix

        # First handle direct fields
        for field_name, field_type in type_hints.items():
            env_name = _field_to_env_name(field_name, effective_prefix)
            if env_name in self._environ:
                raw_value = self._environ[env_name]
                result[field_name] = self._parse_value(raw_value, field_type)

        # Then handle nested SubConfig fields
        for field_name, field_type in type_hints.items():
            if isinstance(field_type, type) and issubclass(field_type, SubConfig):
                nested_prefix = _field_to_env_name(field_name, effective_prefix)
                nested_data = self._load_nested(field_type, nested_prefix)
                if nested_data:
                    if field_name in result:
                        # Merge with existing data
                        result[field_name].update(nested_data)
                    else:
                        result[field_name] = nested_data

        return result

    def _parse_value(self, raw_value: str, field_type: type[Any] | None) -> Any:
        """Parse a value, optionally trying TOML parsing first."""
        if self._parse_toml and self._looks_like_toml(raw_value):
            try:
                # Wrap in a key to make it valid TOML
                toml_str = f"value = {raw_value}"
                parsed = tomllib.loads(toml_str)
                return parsed.get("value", raw_value)
            except Exception:
                # If TOML parsing fails, try as inline table or fall through
                try:
                    # Try parsing the raw value directly if it looks like a table
                    if raw_value.strip().startswith("{"):
                        toml_str = f"value = {raw_value}"
                        parsed = tomllib.loads(toml_str)
                        return parsed.get("value", raw_value)
                except Exception:
                    pass
        # Fall back to standard parsing
        return _parse_env_value(raw_value, field_type)

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

    def _load_nested(
        self, subconfig_type: type[SubConfig], prefix: str
    ) -> dict[str, Any]:
        """Load nested SubConfig fields from environment variables."""
        from ._bases import SubConfig

        result: dict[str, Any] = {}
        type_hints = _get_resolved_type_hints(subconfig_type)

        for field_name, field_type in type_hints.items():
            env_name = _field_to_env_name(field_name, prefix)
            if env_name in self._environ:
                raw_value = self._environ[env_name]
                result[field_name] = self._parse_value(raw_value, field_type)

        # Recursively handle nested SubConfigs
        for field_name, field_type in type_hints.items():
            if isinstance(field_type, type) and issubclass(field_type, SubConfig):
                nested_prefix = _field_to_env_name(field_name, prefix)
                nested_data = self._load_nested(field_type, nested_prefix)
                if nested_data:
                    result[field_name] = nested_data

        return result


def _get_resolved_type_hints(cls: type[Any]) -> dict[str, Any]:
    """Get resolved type hints for a class, preserving Annotated metadata."""
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception:
        # Fallback to raw annotations if resolution fails
        return getattr(cls, "__annotations__", {})


def _get_section_name(part_type: type[ConfigPart]) -> str:
    """Get the section name for a ConfigPart type."""
    # Check for prefix marker on the class
    prefix = _get_part_prefix(part_type)
    if prefix:
        return prefix
    return part_type.__name__


def _get_part_prefix(part_type: type[ConfigPart]) -> str | None:
    """Get the prefix from a ConfigPart's markers."""
    markers = getattr(part_type, "_config_markers", ())
    for marker in markers:
        if isinstance(marker, PrefixMarker):
            return marker.prefix
    return None


def _field_to_env_name(field_name: str, prefix: str) -> str:
    """Convert a field name to an environment variable name."""
    env_name = field_name.upper()
    if prefix:
        return f"{prefix.upper()}_{env_name}"
    return env_name


def _unwrap_optional(field_type: type[Any]) -> type[Any]:
    """Unwrap Optional/Union/Annotated types to get the actual type."""
    from typing import Annotated

    origin = get_origin(field_type)

    # Unwrap Annotated first to get to the inner type
    if origin is Annotated:
        type_args = getattr(field_type, "__args__", ())
        if type_args:
            # First arg is the actual type, rest are annotations
            return _unwrap_optional(type_args[0])

    # Then handle Optional/Union
    if origin is Union or origin is types.UnionType:
        type_args = getattr(field_type, "__args__", ())
        non_none_args = [a for a in type_args if a is not type(None)]
        if non_none_args:
            result: type[Any] = non_none_args[0]
            return result
    return field_type


def _get_short_option(field_type: Any) -> str | None:
    """Extract short option from Annotated type if present."""
    # Check if it's an Annotated type
    origin = get_origin(field_type)
    if origin is not None:
        # For Annotated types, __metadata__ contains the annotations
        metadata = getattr(field_type, "__metadata__", ())
        for item in metadata:
            if isinstance(item, ShortMarker):
                return item.char
    return None


def _parse_value(raw_value: str, field_type: type[Any] | None) -> Any:
    """Parse a string value with type-aware conversion."""
    # Handle None type annotation
    if field_type is None:
        return raw_value

    # Get origin for generic types (e.g., list[str] -> list, str | None -> Union)
    origin = get_origin(field_type)

    # Handle Optional/Union types (str | None)
    if origin is Union or origin is types.UnionType:
        args = getattr(field_type, "__args__", ())
        # Filter out NoneType to get the actual type
        non_none_args = [a for a in args if a is not type(None)]
        if non_none_args:
            return _parse_value(raw_value, non_none_args[0])

    # Handle list types
    if origin is list:
        if not raw_value:
            return []
        # Check if it looks like newline-separated (INI style) or comma-separated
        if "\n" in raw_value:
            lines = [line.strip() for line in raw_value.strip().splitlines()]
            return [line for line in lines if line]
        return [item.strip() for item in raw_value.split(",")]

    # Handle bool
    if field_type is bool:
        return raw_value.lower() in ("true", "yes", "on", "1")

    # Handle int
    if field_type is int:
        return int(raw_value)

    # Handle float
    if field_type is float:
        return float(raw_value)

    # Default: return as string
    return raw_value


def _parse_ini_value(raw_value: str, field_type: type[Any] | None) -> Any:
    """Parse an INI value with type-aware conversion."""
    return _parse_value(raw_value, field_type)


def _parse_env_value(raw_value: str, field_type: type[Any] | None) -> Any:
    """Parse an environment variable value with type-aware conversion."""
    return _parse_value(raw_value, field_type)


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
        precedence: int = 15,
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
            precedence: Higher values override lower values (default: 15)
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
        if path.suffix == ".toml":
            return TomlSource(path, precedence=self._precedence)
        elif path.suffix in (".ini", ".cfg"):
            return IniSource(path, precedence=self._precedence)
        else:
            # Default to TOML for unknown extensions
            return TomlSource(path, precedence=self._precedence)

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """Load configuration from discovered config file."""
        self._ensure_discovered()
        if self._discovered_source is None:
            return {}
        return self._discovered_source.load(part_type)


__all__ = [
    "TomlSource",
    "IniSource",
    "CLISource",
    "EnvSource",
    "ConfigFileDiscoverySource",
]
