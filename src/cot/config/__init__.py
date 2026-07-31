"""Configuration management core classes."""

from __future__ import annotations

from ._annotations import (
    addopts_field,
    bootstrap_only,
    config_source,
    from_parent,
    help,
    named,
    no_cli,
    short,
)
from ._bases import ConfigPart, SubConfig
from ._manager import (
    ConfigManager,
    ConfigSource,
    Discoverable,
    UnknownConfigKeyWarning,
)
from ._origins import Origin, OriginAware, OriginKind
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
    # Manager
    "ConfigManager",
    "ConfigSource",
    "Discoverable",
    "UnknownConfigKeyWarning",
    # Provenance
    "Origin",
    "OriginAware",
    "OriginKind",
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
    "named",
    "no_cli",
]
