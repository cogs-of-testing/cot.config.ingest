# Bootstrap Process

> **Status: design intent, partly built.** Stages 1 and 2 exist in a different
> shape: there are no bootstrap fragments, and `InvocationConfig` was removed —
> `CLISource(args=, invocation_dir=)` carries the invocation context, and config
> files are found by `ConfigFileDiscoverySource` plus the `config_source` marker.
> Stage 3 (plugin discovery) is **not implemented**; `discover()` exists on the
> `Discoverable` protocol as a `classmethod` returning `None`, not an instance
> method returning a copy. See `AGENTS.md` for the as-built flow.

## Overview

The bootstrap process determines **how** to load configuration before loading the configuration itself. It progressively builds up configuration context through staged loading and feedback loops.

**Key insight**: You can't know where config files are until you've loaded enough config to find them. Bootstrap solves this chicken-and-egg problem.

## Core Concept

Configuration loading happens in **stages**. Early stages provide context (where to look, what args were passed) that later stages use to discover and load more configuration.

```
Stage 1: Invocation     → "I was invoked from /project with args [--config, app.toml]"
Stage 2: File Discovery → "Found config files: [app.toml, pyproject.toml]"
Stage 3: Full Config    → Load all ConfigParts from all discovered sources
```

## Bootstrap vs Regular ConfigParts

The distinction is **when and how** the ConfigPart is provided:

| Aspect | Bootstrap ConfigParts | Regular ConfigParts |
|--------|----------------------|---------------------|
| When created | Before ConfigManager | After ConfigManager |
| How provided | Passed as instance | Registered as type |
| Discovery | Already complete | Manager calls `discover()` |
| Purpose | Provide initial context | Define app configuration |

### Bootstrap ConfigParts (passed at construction)

```python
# Created by the application before ConfigManager exists
invocation = InvocationConfig(
    invocation_dir=Path.cwd(),
    invocation_args=sys.argv[1:],
)

# Passed to ConfigManager at construction
manager = ConfigManager(bootstrap_fragments=[invocation])
```

### Regular ConfigParts (registered after construction)

```python
# Type registered - manager handles instantiation and discovery
manager.register_fragment_type(AddoptsConfig)
```

See [ConfigParts](config-parts.md) for full ConfigPart specification.

## Bootstrap Stages

### Stage 1: Invocation Context

The application provides invocation context as a bootstrap fragment:

```python
class InvocationConfig(ConfigPart):
    """Bootstrap fragment - provides invocation context."""
    invocation_dir: Path      # Where the app was invoked
    invocation_args: list[str]  # CLI arguments passed
    plugins: list[str] = []   # Early plugin list (if known)
```

This fragment is **pre-built** - no discovery needed.

### Stage 2: Config File Discovery

A ConfigPart with a `discover()` method uses invocation context to find config files:

```python
class ConfigFileConfig(ConfigPart):
    """Discovers where config files are located."""
    config: Path | None = None    # Explicit --config path
    config_files: list[Path] = []  # Discovered files

    def discover(self, manager: ConfigManager) -> Self:
        invocation = manager.get_fragment(InvocationConfig)

        # Check for explicit --config argument
        loaded = manager.load_for_part(type(self))
        config = loaded.get("config")

        if config:
            config_files = [config]
        else:
            # Search standard locations
            config_files = discover_config_files(invocation.invocation_dir)

        return replace(self, config=config, config_files=config_files)
```

**Feedback**: When `config_files` is populated, the manager adds them as sources for subsequent loading.

### Stage 3: Plugin Discovery

Plugins may contribute additional ConfigParts:

```python
class PluginConfig(ConfigPart):
    """Discovers and loads plugins."""
    plugins: list[str] = []

    def discover(self, manager: ConfigManager) -> Self:
        loaded = manager.load_for_part(type(self))
        plugins = loaded.get("plugins", [])

        # Side effect: register plugin-provided ConfigParts
        for plugin_name in plugins:
            plugin = load_plugin(plugin_name)
            if hasattr(plugin, "ConfigPart"):
                manager.register_fragment_type(plugin.ConfigPart)

        return replace(self, plugins=plugins)
```

### Stage 4: Full Configuration

All remaining ConfigParts are registered. They can now load from all discovered sources:

```python
# These load from: CLI args + discovered config files + env vars
manager.register_fragment_type(LoggingConfig)
manager.register_fragment_type(DatabaseConfig)
manager.register_fragment_type(ServerConfig)
```

## The `discover()` Method

ConfigParts can optionally implement `discover()` to customize how they're initialized:

```python
def discover(self, manager: ConfigManager) -> Self:
    """
    Discover configuration and return updated instance.

    Args:
        manager: ConfigManager with access to existing fragments and sources

    Returns:
        Updated copy of self with discovered values
    """
```

**When `discover()` is called:**
1. Manager creates default instance: `MyConfig()`
2. Manager calls `instance.discover(manager)`
3. `discover()` returns updated copy via `replace(self, ...)`
4. Manager stores the returned instance

**When `discover()` is NOT defined:**
- Manager loads from active sources via `load_for_part()`
- Updates instance with loaded values

See [ConfigParts](config-parts.md) for more on the `discover()` protocol.

## Feedback Mechanisms

The bootstrap process uses feedback loops to progressively build up sources:

### Source Addition Feedback

When a ConfigPart discovers config files, the manager adds them as sources:

```python
# ConfigFileConfig.discover() returns config_files = [Path("app.toml")]
# Manager sees this and adds:
manager.sources.append(FileSource(Path("app.toml")))
# Now subsequent ConfigParts can load from app.toml
```

### Part Registration Feedback

Plugin discovery can register new ConfigPart types:

```python
# PluginConfig.discover() finds plugins = ["pytest"]
# It registers pytest's ConfigPart:
manager.register_fragment_type(PytestConfig)
# Now PytestConfig is available for full config load
```

See [Feedback Loops](feedback-loops.md) for detailed loop mechanics.

## Example Bootstrap Sequence

```python
from pathlib import Path
import sys

# Stage 1: Create bootstrap fragment
invocation = InvocationConfig(
    invocation_dir=Path.cwd(),
    invocation_args=sys.argv[1:],
)

# Create manager with bootstrap
manager = ConfigManager(bootstrap_fragments=[invocation])

# Stage 2: Discover config files
manager.register_fragment_type(ConfigFileConfig)
# → discover() finds app.toml
# → manager adds FileSource("app.toml")

# Stage 3: Discover plugins
manager.register_fragment_type(PluginConfig)
# → discover() finds plugins = ["myPlugin"]
# → registers myPlugin.ConfigPart

# Stage 4: Load full configuration
manager.register_fragment_type(LoggingConfig)
manager.register_fragment_type(DatabaseConfig)
# → loads from CLI + app.toml + env vars

# Access final configuration
logging = manager.get_fragment(LoggingConfig)
database = manager.get_fragment(DatabaseConfig)
```

## Design Decisions

### Why stages instead of single-pass?

Single-pass loading requires knowing all sources upfront. But:
- Config file location may come from CLI args
- Plugin list may come from config files
- Plugin config schemas come from plugins

Staged loading lets each piece discover the next.

### Why `discover()` returns a copy?

ConfigParts are **frozen** after creation. The `discover()` method can't mutate `self`, so it returns an updated copy via `dataclasses.replace()`.

### Why bootstrap fragments vs registered types?

Bootstrap fragments are created **before** the manager exists. They provide the initial context the manager needs to function. Regular types are registered **with** the manager, which handles their lifecycle.

## Open Questions

1. **Error Handling**: What happens if `discover()` fails? Continue with defaults or abort?
2. **Ordering**: Must fragments be registered in dependency order?
3. **Re-discovery**: Can `discover()` be called multiple times if sources change?
4. **Validation**: When should discovered values be validated?

## Related Documents

- [ConfigParts](config-parts.md) - ConfigPart specification and markers
- [ConfigManager](config-manager.md) - Manager API and responsibilities
- [Feedback Loops](feedback-loops.md) - How loops cooperate
- [Name Matching](name-matching.md) - Field name to source name mapping
