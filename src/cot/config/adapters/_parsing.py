"""Private parsing utilities for environment variable values."""

from __future__ import annotations

from typing import Any


class ParseError(ValueError):
    """Raised when a value cannot be parsed in the expected format."""

    pass


def parse_boolean(value: str) -> bool | None:
    """
    Parse boolean value using common string representations.

    Uses the same logic as configparser for consistency with stdlib.

    :param value: String value to parse
    :returns: True, False, or None if not a boolean string
    """
    value_lower = value.lower()
    if value_lower in ("true", "yes", "1", "on"):
        return True
    elif value_lower in ("false", "no", "0", "off"):
        return False
    return None


def parse_int(value: str) -> int:
    """
    Parse integer value from string.

    :param value: String value to parse
    :returns: Integer value
    :raises ParseError: If value is not a valid integer
    """
    try:
        return int(value)
    except ValueError as e:
        raise ParseError(f"Invalid integer: {e}") from e


def parse_float(value: str) -> float:
    """
    Parse float value from string.

    :param value: String value to parse
    :returns: Float value
    :raises ParseError: If value is not a valid float
    """
    try:
        return float(value)
    except ValueError as e:
        raise ParseError(f"Invalid float: {e}") from e


def parse_toml(value: str) -> Any:
    """
    Parse value as TOML.

    Wraps the value in a TOML key-value format for parsing.

    :param value: String value to parse
    :returns: Parsed value
    :raises ParseError: If value is not valid TOML
    """
    try:
        import tomllib

        # TOML requires key-value format
        toml_str = f"value = {value}"
        parsed = tomllib.loads(toml_str)
        return parsed.get("value")
    except Exception as e:
        raise ParseError(f"Invalid TOML: {e}") from e


def parse_list(value: str) -> list[str]:
    """
    Parse delimited list from string.

    Splits on comma or semicolon and strips whitespace from items.

    :param value: String value to parse
    :returns: List of string items
    """
    # Split by comma or semicolon
    if "," in value:
        return [v.strip() for v in value.split(",")]
    elif ";" in value:
        return [v.strip() for v in value.split(";")]
    else:
        return [value]
