"""Name mapping utilities for converting between different naming conventions."""

from __future__ import annotations


def snake_to_kebab(name: str) -> str:
    """Convert snake_case to kebab-case."""
    return name.replace("_", "-")


def kebab_to_snake(name: str) -> str:
    """Convert kebab-case to snake_case."""
    return name.replace("-", "_")


def snake_to_upper(name: str) -> str:
    """Convert snake_case to UPPER_CASE."""
    return name.upper()


def field_to_cli_name(field_name: str, prefix: str | None = None) -> str:
    """
    Convert a field name to CLI option name.

    :param field_name: The field name to convert
    :param prefix: Optional prefix to add
    :returns: CLI option name with -- prefix
    """
    if prefix:
        field_name = f"{prefix}_{field_name}"
    return f"--{snake_to_kebab(field_name)}"


def field_to_env_name(field_name: str, prefix: str | None = None) -> str:
    """
    Convert a field name to environment variable name.

    :param field_name: The field name to convert
    :param prefix: Optional prefix to add
    :returns: Environment variable name in UPPER_CASE
    """
    if prefix:
        field_name = f"{prefix}_{field_name}"
    return snake_to_upper(field_name)
