"""Configuration management core classes."""

from __future__ import annotations

from ._annotations import (
    addopts_field,
    bootstrap_only,
    config_source,
    from_parent,
    help,
    short,
)
from ._bases import ConfigPart, InvocationConfig, SubConfig
from ._manager import ConfigManager, ConfigSource, Discoverable
from ._sources import (
    CLISource,
    ConfigFileDiscoverySource,
    EnvSource,
    IniSource,
    TomlSource,
)

__all__ = [
    # Base classes
    "ConfigPart",
    "SubConfig",
    "InvocationConfig",
    # Manager
    "ConfigManager",
    "ConfigSource",
    "Discoverable",
    # Sources
    "TomlSource",
    "IniSource",
    "CLISource",
    "EnvSource",
    "ConfigFileDiscoverySource",
    # Annotations
    "help",
    "from_parent",
    "config_source",
    "bootstrap_only",
    "addopts_field",
    "short",
]
