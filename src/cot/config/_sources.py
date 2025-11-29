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

from ._annotations import PrefixMarker

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


class EnvSource:
    """Load configuration from environment variables."""

    def __init__(
        self,
        prefix: str = "",
        *,
        precedence: int = 20,
        environ: dict[str, str] | None = None,
    ) -> None:
        """
        Create an environment variable configuration source.

        Args:
            prefix: Prefix for environment variables (e.g., "APP" -> APP_*)
            precedence: Higher values override lower values (default: 20)
            environ: Environment dict to use (defaults to os.environ)
        """
        self._prefix = prefix.upper()
        self._precedence = precedence
        self._environ = environ if environ is not None else os.environ

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
                result[field_name] = _parse_env_value(raw_value, field_type)

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
                result[field_name] = _parse_env_value(raw_value, field_type)

        # Recursively handle nested SubConfigs
        for field_name, field_type in type_hints.items():
            if isinstance(field_type, type) and issubclass(field_type, SubConfig):
                nested_prefix = _field_to_env_name(field_name, prefix)
                nested_data = self._load_nested(field_type, nested_prefix)
                if nested_data:
                    result[field_name] = nested_data

        return result


def _get_resolved_type_hints(cls: type[Any]) -> dict[str, Any]:
    """Get resolved type hints for a class."""
    try:
        return get_type_hints(cls)
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


__all__ = [
    "TomlSource",
    "IniSource",
    "EnvSource",
]
