# ConfigManager

## Overview

The ConfigManager orchestrates configuration loading from multiple sources. It coordinates the bootstrap process, manages sources, and builds final ConfigPart instances.

## Core Responsibilities

1. **Manage sources** - Track active configuration sources (files, env, CLI)
2. **Register ConfigParts** - Handle type registration and discovery
3. **Load and merge** - Load data from sources with proper precedence
4. **Build instances** - Create final ConfigPart instances

## API

### Construction

```python
class ConfigManager:
    def __init__(
        self,
        sources: Sequence[ConfigSource] = (),
    ) -> None:
        """
        Create ConfigManager with sources.

        Args:
            sources: Configuration sources (CLI, env, files, ...).
                Kept sorted by precedence; higher precedence wins.
        """
```

**Example:**
```python
cli = CLISource(sys.argv[1:], invocation_dir=Path.cwd())
manager = ConfigManager(sources=[cli, EnvSource("APP")])
```

Sources carry all the context the manager needs — `CLISource` owns both the
argument list and the invocation directory. There is no separate bootstrap
fragment; an earlier design passed pre-built instances via `bootstrap_fragments=`,
and that parameter no longer exists.

### Registering ConfigParts

```python
def register_fragment_type(
    self,
    fragment_type: type[ConfigPart],
) -> ConfigPart:
    """
    Register a ConfigPart type and return the discovered instance.

    Process:
    1. Create default instance: fragment_type()
    2. If instance has discover(), call it and use returned instance
    3. Otherwise, load from sources and update instance
    4. Store and return the final instance

    Args:
        fragment_type: ConfigPart class to register

    Returns:
        Discovered/loaded ConfigPart instance
    """
```

**Example:**
```python
# Register and get instance in one call
config_files = manager.register_fragment_type(ConfigFileConfig)
logging = manager.register_fragment_type(LoggingConfig)
```

### Accessing Fragments

```python
def get_fragment(self, fragment_type: type[T]) -> T:
    """
    Get a stored fragment by type.

    Args:
        fragment_type: ConfigPart class to retrieve

    Returns:
        The stored ConfigPart instance

    Raises:
        KeyError: If fragment type not registered
    """
```

**Example:**
```python
logging = manager.get_fragment(LoggingConfig)
print(f"Level: {logging.level}")
```

### Loading from Sources

```python
def load_for_part(
    self,
    fragment_type: type[ConfigPart],
) -> dict[str, Any]:
    """
    Load data for a ConfigPart from all active sources.

    Merges data from all sources in precedence order.
    Used by discover() methods to get source data.

    Args:
        fragment_type: ConfigPart class to load data for

    Returns:
        Dict of field names to values
    """
```

**Example:**
```python
class MyConfig(ConfigPart):
    def discover(self, manager: ConfigManager) -> Self:
        # Load what sources have for this ConfigPart
        loaded = manager.load_for_part(type(self))
        return replace(self, **loaded)
```

## Source Management

### Source Types

The manager coordinates multiple source types:

| Source | Description | Precedence |
|--------|-------------|------------|
| `DefaultSource` | Field defaults from ConfigPart | Lowest |
| `FileSource` | Config files (TOML, JSON, YAML) | Low |
| `EnvSource` | Environment variables | Medium |
| `CLISource` | Command-line arguments | Highest |

### Adding Sources

Sources are typically added through the bootstrap process:

```python
# Manager adds sources automatically when ConfigParts discover files
class ConfigFileConfig(ConfigPart):
    config_files: list[Path] = []

    def discover(self, manager: ConfigManager) -> Self:
        # ... discover files ...
        return replace(self, config_files=found_files)

# When discover_files=True marker is set, manager adds FileSource
# for each file in config_files
```

### Precedence Order

When the same field is set in multiple sources, higher precedence wins:

```
1. Default values      (lowest)
2. System config files
3. User config files
4. Local config files
5. Environment variables
6. CLI arguments       (highest)
```

## Override Semantics

### Simple Override

```python
# config.toml: debug = false
# CLI: --debug
# Result: debug = true (CLI wins)
```

### Deep Merge for Nested Config

```python
# config.toml:
#   [database]
#   host = "localhost"
#   port = 5432

# CLI: --database-port 3306

# Result:
#   database.host = "localhost"  (from file)
#   database.port = 3306         (from CLI)
```

### List Handling

> **Not implemented yet.** Lists are currently replaced wholesale by the
> highest-precedence source. The modes below are design intent.

Lists support multiple merge modes:

**Append (default):**
```python
# config.toml: plugins = ["a", "b"]
# CLI: --plugins c
# Result: plugins = ["a", "b", "c"]
```

**Replace (with reset):**
```python
# config.toml: plugins = ["a", "b"]
# CLI: --plugins-reset --plugins c
# Result: plugins = ["c"]
```

**Extend (string concat for addopts-style):**
```python
# pytest.ini: addopts = "-v"
# pyproject.toml: addopts = "-x"
# Result: addopts = "-v -x"
```

## Type Mapping

The manager handles mapping between ConfigPart field names and source-specific names:

| ConfigPart Field | CLI Argument | Environment Variable | Config File Key |
|------------------|--------------|---------------------|-----------------|
| `log_level` | `--log-level` | `LOG_LEVEL` | `log_level` |
| `debug_mode` | `--debug-mode` | `DEBUG_MODE` | `debug_mode` |

With prefix `app`:
| ConfigPart Field | CLI Argument | Environment Variable |
|------------------|--------------|---------------------|
| `log_level` | `--app-log-level` | `APP_LOG_LEVEL` |

See [Name Matching](name-matching.md) for full mapping rules.

## Internal State

```python
class ConfigManager:
    fragments: dict[type[ConfigPart], ConfigPart]  # Stored instances
    sources: list[ConfigSource]                     # Active sources
    config_parts: dict[str, type[ConfigPart]]      # Registered types
```

## Usage Patterns

### Basic Bootstrap Sequence

```python
from pathlib import Path
import sys

# 1. Build the sources — they carry the invocation context
cli = CLISource(sys.argv[1:], invocation_dir=Path.cwd())
files = ConfigFileDiscoverySource(invocation_dir=cli.invocation_dir, cli_source=cli)

# 2. Create manager
manager = ConfigManager(sources=[cli, EnvSource("APP"), files])

# 3. Register application ConfigParts (returns the loaded instance)
logging = manager.register_fragment_type(LoggingConfig)
database = manager.register_fragment_type(DatabaseConfig)

# 4. Or retrieve them again later
logging = manager.get_fragment(LoggingConfig)
```

### With Plugin Discovery

> **Not implemented yet.** The `Discoverable` protocol exists, but nothing
> implements it and no plugin loading happens.

```python
# After config files discovered
manager.register_fragment_type(PluginConfig)
# PluginConfig.discover() registers plugin ConfigParts

# Plugin configs now available
pytest_config = manager.get_fragment(PytestConfig)
```

### Dynamic Registration

```python
# ConfigParts can be registered at any time
manager.register_fragment_type(AppConfig)

# New sources are re-evaluated for all parts
manager.register_fragment_type(NewPluginConfig)
```

## Error Handling

*To be designed*

Considerations:
- What if `discover()` raises an exception?
- What if a required field has no value from any source?
- What if type conversion fails?

## Related Documents

- [Bootstrap Process](bootstrap-process.md) - How bootstrap stages work
- [ConfigParts](config-parts.md) - ConfigPart specification
- [Feedback Loops](feedback-loops.md) - Source addition feedback
- [Name Matching](name-matching.md) - Field to source name mapping
