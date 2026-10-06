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
from ._convert import register_conversion
from ._diagnostics import (
    ConfigCollisionError,
    ConfigDeclarationError,
    ConfigError,
    ConfigLifecycleError,
    ConfigUsageError,
    ConfigValueError,
    ConfigWarning,
    DeprecatedNameWarning,
    MissingConfigError,
    RuntimeMutationWarning,
    ShadowedValueWarning,
    UnknownConfigKeyWarning,
    UnknownOverrideKeyWarning,
)
from ._index import SpellingIndex, SpellingTarget
from ._manager import ConfigManager
from ._origins import Origin, OriginKind
from ._precedence import Precedence
from ._projection import Projection, project
from ._reading import (
    BindingSource,
    CLISource,
    ConfigFileDiscoverySource,
    ConfigSource,
    EnvSource,
    IniSource,
    InjectedArgsSource,
    OverrideSource,
    RuntimeSource,
    TomlEnvSource,
    TomlSource,
    source_for_file,
)
from ._specs import CliForm, EnvSpelling, FieldSpec, field_specs
from ._store import (
    FailedValue,
    LayeredStore,
    LayeredValue,
    Reading,
    Unmatched,
)

__all__ = [
    # Base classes
    "ConfigPart",
    # Manager
    "ConfigManager",
    "ConfigSource",
    "BindingSource",
    # Diagnostics
    "ConfigError",
    "ConfigLifecycleError",
    "ConfigDeclarationError",
    "ConfigCollisionError",
    "ConfigUsageError",
    "ConfigValueError",
    "MissingConfigError",
    "ConfigWarning",
    "UnknownConfigKeyWarning",
    "UnknownOverrideKeyWarning",
    "DeprecatedNameWarning",
    "ShadowedValueWarning",
    "RuntimeMutationWarning",
    # Conversion
    "register_conversion",
    # Specs and the index
    "FieldSpec",
    "CliForm",
    "EnvSpelling",
    "field_specs",
    "SpellingIndex",
    "SpellingTarget",
    # The store and the projection
    "Reading",
    "Unmatched",
    "LayeredValue",
    "FailedValue",
    "LayeredStore",
    "Projection",
    "project",
    # Provenance
    "Origin",
    "OriginKind",
    # Precedence
    "Precedence",
    # Sources
    "TomlSource",
    "IniSource",
    "CLISource",
    "InjectedArgsSource",
    "OverrideSource",
    "RuntimeSource",
    "EnvSource",
    "TomlEnvSource",
    "ConfigFileDiscoverySource",
    "source_for_file",
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
