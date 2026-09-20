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
from ._bases import ConfigPart
from ._errors import ConfigDeclarationError, ConfigError
from ._manager import (
    ConfigLifecycleError,
    ConfigManager,
    ConfigSource,
    DeclaringSource,
    Discoverable,
    UnknownConfigKeyWarning,
)
from ._origins import Origin, OriginAware, OriginKind
from ._precedence import Precedence
from ._sources import (
    AddoptsSource,
    CLISource,
    ConfigFileDiscoverySource,
    EnvSource,
    IniSource,
    TomlSource,
)

__all__ = [
    # Base classes
    "ConfigPart",
    # Manager
    "ConfigManager",
    "ConfigSource",
    "DeclaringSource",
    "Discoverable",
    "ConfigLifecycleError",
    "UnknownConfigKeyWarning",
    # Diagnostics
    "ConfigError",
    "ConfigDeclarationError",
    # Provenance
    "Origin",
    "OriginAware",
    "OriginKind",
    # Precedence
    "Precedence",
    # Sources
    "TomlSource",
    "IniSource",
    "CLISource",
    "AddoptsSource",
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
