# ConfigPart Specification

## Overview

ConfigParts are the fundamental building blocks of the configuration system. They define the structure, types, and metadata for configuration data.

## Basic ConfigPart

```python
from cot.config import ConfigPart

class LogConfig(ConfigPart):
    """Logging configuration."""
    level: str = "INFO"
    file: str | None = None
    format: str = "%(levelname)s: %(message)s"
```

ConfigParts are:
- **Type-annotated**: All fields must have type hints
- **Frozen**: Immutable after creation
- **Composable**: Can contain other ConfigParts as SubConfigs

## Field Types

### Supported Types

| Python Type | CLI | Config File | Environment |
|-------------|-----|-------------|-------------|
| `str` | `--field value` | `"value"` | `FIELD=value` |
| `int` | `--field 42` | `42` | `FIELD=42` |
| `float` | `--field 3.14` | `3.14` | `FIELD=3.14` |
| `bool` | `--field` / `--no-field` | `true`/`false` | `FIELD=1`/`0` |
| `Path` | `--field /path` | `"/path"` | `FIELD=/path` |
| `list[T]` | `--field a --field b` | `["a", "b"]` | `FIELD=a,b` |
| `T \| None` | Optional | `null` or value | Empty or value |

### Required vs Optional Fields

```python
class DatabaseConfig(ConfigPart):
    host: str                    # Required - no default
    port: int = 5432             # Optional - has default
    ssl: bool = False            # Optional - has default
    timeout: float | None = None # Optional - nullable
```

## SubConfig Composition

ConfigParts can nest other configurations:

```python
class ServerConfig(SubConfig):
    host: str = "localhost"
    port: int = 8000

class DatabaseConfig(SubConfig):
    host: str = "localhost"
    port: int = 5432

class AppConfig(ConfigPart):
    debug: bool = False
    server: ServerConfig
    database: DatabaseConfig
```

**Note**: Use `SubConfig` for nested configurations, `ConfigPart` for top-level fragments.

## Prefixes

Prefixes control how field names map to CLI args and environment variables.

### Class-Level Prefix

```python
class DatabaseConfig(ConfigPart, prefix="db"):
    host: str = "localhost"
    port: int = 5432

# Results in:
# CLI: --db-host, --db-port
# Env: DB_HOST, DB_PORT
```

### Field-Level Prefix

```python
from cot.config._annotations import PrefixMarker

class AppConfig(ConfigPart):
    database: DatabaseConfig @ PrefixMarker("db")
```

See [Name Matching](name-matching.md) for full mapping rules.

## Field Annotations

### Help Text

```python
from cot.config._annotations import help

class ServerConfig(ConfigPart):
    host: str @ help("Server hostname") = "localhost"
    port: int @ help("Server port number") = 8000
    workers: int @ help("Number of worker processes") = 4
```

### From Parent

Fields can inherit values from parent context:

```python
from cot.config._annotations import from_parent

class SubConfig(ConfigPart):
    root_dir: Path @ from_parent  # Populated from parent's context
    name: str
```

## The `discover()` Protocol

ConfigParts can implement `discover()` to customize their initialization during bootstrap.

### Basic Pattern

```python
from dataclasses import replace
from typing import Self

class ConfigFileConfig(ConfigPart):
    config: Path | None = None
    config_files: list[Path] = []

    def discover(self, manager: ConfigManager) -> Self:
        """
        Discover configuration and return updated instance.

        Args:
            manager: ConfigManager with access to fragments and sources

        Returns:
            Updated copy of self (ConfigParts are frozen)
        """
        invocation = manager.get(InvocationConfig)
        loaded = manager.load_for_part(type(self))

        config = loaded.get("config") or self.config
        if config:
            config_files = [config]
        else:
            config_files = discover_config_files(invocation.invocation_dir)

        return replace(self, config=config, config_files=config_files)
```

### How `discover()` Works

1. Manager creates default instance: `ConfigFileConfig()`
2. Manager calls `instance.discover(manager)`
3. `discover()` accesses other fragments via `manager.get()`
4. `discover()` loads from sources via `manager.load_for_part()`
5. `discover()` returns updated copy via `replace(self, ...)`
6. Manager stores the returned instance

### When to Use `discover()`

Use `discover()` when you need to:
- Access other ConfigParts to make decisions
- Perform file system operations (finding config files)
- Have side effects (registering plugins)
- Implement custom loading logic

### Default Behavior (No `discover()`)

If `discover()` is not defined, the manager uses default loading:

```python
# Manager does this automatically:
loaded = manager.load_for_part(ConfigType)
instance = replace(ConfigType(), **loaded)
```

See [Bootstrap Process](bootstrap-process.md) for how discovery fits into staged loading.

## Frozen Behavior

ConfigParts are **immutable after creation**:

```python
config = AppConfig(debug=True)
config.debug = False  # AttributeError: Cannot modify frozen attribute
```

To "modify" a ConfigPart, create a new instance:

```python
from dataclasses import replace

new_config = replace(config, debug=False)
```

## Class Markers

ConfigParts can have class-level markers that control behavior:

```python
class ConfigFileConfig(ConfigPart, prefix="cfg", discover_files=True):
    ...
```

| Marker | Purpose |
|--------|---------|
| `prefix="..."` | Set prefix for CLI/env name mapping |
| `discover_files=True` | Manager adds discovered files as sources |
| `bootstrap=True` | Marker for documentation (no runtime effect) |

## Validation

*To be designed*

Planned features:
- Field-level validators
- Cross-field validation
- Validation timing (during discover vs after build)

## Examples

### Simple Application Config

```python
class AppConfig(ConfigPart):
    name: str = "myapp"
    debug: bool = False
    log_level: str = "INFO"
```

### Nested Configuration

```python
class DatabaseConfig(SubConfig, prefix="db"):
    host: str = "localhost"
    port: int = 5432
    name: str = "app_db"

class CacheConfig(SubConfig, prefix="cache"):
    enabled: bool = True
    ttl: int = 3600

class AppConfig(ConfigPart):
    app_name: str = "myapp"
    database: DatabaseConfig
    cache: CacheConfig
```

### With Discovery

```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []

    def discover(self, manager: ConfigManager) -> Self:
        loaded = manager.load_for_part(type(self))
        plugins = loaded.get("plugins", [])

        # Register plugin-provided ConfigParts
        for plugin_name in plugins:
            plugin = import_plugin(plugin_name)
            if hasattr(plugin, "Config"):
                manager.declare(plugin.Config)

        return replace(self, plugins=plugins)
```

## Related Documents

- [Bootstrap Process](bootstrap-process.md) - Staged loading and discovery
- [ConfigManager](config-manager.md) - Manager API
- [Name Matching](name-matching.md) - Field name mapping rules
