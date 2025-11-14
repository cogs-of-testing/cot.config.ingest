"""File loaders for different configuration formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path | str) -> dict[str, Any]:
    """
    Load configuration from a JSON file.

    :param path: Path to JSON file
    :returns: Parsed configuration dictionary
    """
    path = Path(path)
    with path.open("r") as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_toml(path: Path | str) -> dict[str, Any]:
    """
    Load configuration from a TOML file.

    :param path: Path to TOML file
    :returns: Parsed configuration dictionary
    """
    import tomllib

    path = Path(path)
    with path.open("rb") as f:
        return tomllib.load(f)  # type: ignore[no-any-return]


def load_yaml(path: Path | str) -> dict[str, Any]:
    """
    Load configuration from a YAML file.

    :param path: Path to YAML file
    :returns: Parsed configuration dictionary
    :raises ImportError: If PyYAML is not installed
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load YAML files. "
            "Install it with: pip install PyYAML"
        ) from exc

    path = Path(path)
    with path.open("r") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def load_file(path: Path | str) -> dict[str, Any]:
    """
    Load configuration from a file, detecting format by extension.

    :param path: Path to configuration file
    :returns: Parsed configuration dictionary
    :raises ValueError: If file format is not supported
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".json":
        return load_json(path)
    elif suffix == ".toml":
        return load_toml(path)
    elif suffix in (".yaml", ".yml"):
        return load_yaml(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def save_json(data: dict[str, Any], path: Path | str, indent: int = 2) -> None:
    """
    Save configuration to a JSON file.

    :param data: Configuration dictionary
    :param path: Path to save to
    :param indent: Indentation level
    """
    path = Path(path)
    with path.open("w") as f:
        json.dump(data, f, indent=indent)


def save_toml(data: dict[str, Any], path: Path | str) -> None:
    """
    Save configuration to a TOML file.

    :param data: Configuration dictionary
    :param path: Path to save to
    :raises ImportError: If tomli_w is not installed
    """
    try:
        import tomli_w
    except ImportError as exc:
        raise ImportError(
            "tomli_w is required to save TOML files. "
            "Install it with: pip install tomli_w"
        ) from exc

    path = Path(path)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def save_yaml(data: dict[str, Any], path: Path | str) -> None:
    """
    Save configuration to a YAML file.

    :param data: Configuration dictionary
    :param path: Path to save to
    :raises ImportError: If PyYAML is not installed
    """
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to save YAML files. "
            "Install it with: pip install PyYAML"
        ) from exc

    path = Path(path)
    with path.open("w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
