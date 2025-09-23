"""Dictionary manipulation utilities for nested data structures."""

from __future__ import annotations

from typing import Any


def nested_get(data: dict[str, Any], path: str, separator: str = ".") -> Any:
    """
    Get a value from a nested dictionary using a path.

    :param data: The dictionary to search
    :param path: Path to the value (e.g., "logging.level")
    :param separator: Path separator
    :returns: The value at the path or None if not found
    """
    keys = path.split(separator)
    current: Any = data

    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None

    return current


def nested_set(
    data: dict[str, Any], path: str, value: Any, separator: str = "."
) -> None:
    """
    Set a value in a nested dictionary using a path.

    :param data: The dictionary to modify
    :param path: Path to set (e.g., "logging.level")
    :param value: The value to set
    :param separator: Path separator
    """
    keys = path.split(separator)
    current = data

    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        elif not isinstance(current[key], dict):
            # Can't set nested value if parent is not a dict
            return
        current = current[key]

    current[keys[-1]] = value


def flatten_dict(
    data: dict[str, Any], prefix: str = "", separator: str = "_"
) -> dict[str, Any]:
    """
    Flatten a nested dictionary.

    :param data: The dictionary to flatten
    :param prefix: Prefix for keys
    :param separator: Separator between nested levels
    :returns: Flattened dictionary
    """
    result = {}

    for key, value in data.items():
        new_key = f"{prefix}{separator}{key}" if prefix else key

        if isinstance(value, dict):
            result.update(flatten_dict(value, new_key, separator))
        else:
            result[new_key] = value

    return result


def unflatten_dict(data: dict[str, Any], separator: str = "_") -> dict[str, Any]:
    """
    Unflatten a dictionary with separated keys.

    :param data: The flattened dictionary
    :param separator: Separator used in keys
    :returns: Nested dictionary
    """
    result: dict[str, Any] = {}

    for key, value in data.items():
        nested_set(result, key.replace(separator, "."), value)

    return result
