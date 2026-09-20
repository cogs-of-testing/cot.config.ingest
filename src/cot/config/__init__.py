"""Configuration management core classes."""

from __future__ import annotations

from ._annotations import (
    bootstrap_only,
    config_source,
    counted,
    env_named,
    form,
    formerly,
    from_env,
    from_parent,
    help,
    injected_args,
    named,
    no_cli,
    no_ini,
    short,
)
from ._bases import ConfigPart
from ._errors import ConfigCollisionError, ConfigDeclarationError, ConfigError
from ._index import SpellingIndex, SpellingTarget
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
from ._specs import CliForm, EnvSpelling, FieldSpec, field_specs

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
    "ConfigCollisionError",
    # Specs and the index
    "FieldSpec",
    "CliForm",
    "EnvSpelling",
    "field_specs",
    "SpellingIndex",
    "SpellingTarget",
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
    "injected_args",
    "short",
    "named",
    "no_cli",
    "no_ini",
    "from_env",
    "env_named",
    "formerly",
    "counted",
    "form",
]
