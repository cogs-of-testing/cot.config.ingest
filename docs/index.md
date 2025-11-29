# cot.config.ingest

Type-safe configuration management with multi-source ingestion.

## Overview

`cot.config.ingest` is an experimental Python library that simplifies configuration management by providing a unified way to ingest configuration from:

- **CLI arguments** (via argparse/click/others)
- **Environment variables**
- **Configuration files** (JSON, TOML, YAML)

The library uses dataclass-like `ConfigPart` classes to define configuration structure, then automatically handles loading and merging from multiple sources.

## Key Features

- **Type-safe configuration** with Python type hints
- **Multiple sources** with automatic merging and precedence
- **Origin tracking** to debug where values come from
- **Hierarchical configs** with SubConfig composition
- **Bootstrap process** for staged configuration discovery
- **Plugin support** for extensible configuration schemas

## Quick Example

```python
from cot.config import ConfigPart, ConfigManager
from pathlib import Path

class DatabaseConfig(ConfigPart, prefix="db"):
    host: str = "localhost"
    port: int = 5432

class AppConfig(ConfigPart):
    debug: bool = False
    database: DatabaseConfig

# Bootstrap and load
invocation = InvocationConfig(invocation_dir=Path.cwd(), invocation_args=sys.argv[1:])
manager = ConfigManager(bootstrap_fragments=[invocation])
manager.register_fragment_type(AppConfig)

config = manager.get_fragment(AppConfig)
print(f"Connecting to {config.database.host}:{config.database.port}")
```

## Project Status

**Experimental**: Architecture rebuild in progress. API will change.

## Documentation

### Getting Started

- [Inspiration](getting-started/inspiration.md) - Why this project exists

### Design Documents

Core concepts:

| Document | Description |
|----------|-------------|
| [ConfigParts](design/config-parts.md) | ConfigPart specification, fields, annotations, `discover()` protocol |
| [ConfigManager](design/config-manager.md) | Manager API, source management, override semantics |
| [Bootstrap Process](design/bootstrap-process.md) | Staged loading, discovery, bootstrap vs regular fragments |

Supporting concepts:

| Document | Description |
|----------|-------------|
| [Name Matching](design/name-matching.md) | Field name to CLI/env/file key mapping |
| [Feedback Loops](design/feedback-loops.md) | How configuration loops cooperate |
| [Change Notifications](design/change-notifications.md) | Dependencies and hot reload (future) |

### Reading Order

For understanding the system:

1. **[ConfigParts](design/config-parts.md)** - What configuration looks like
2. **[Bootstrap Process](design/bootstrap-process.md)** - How configuration is discovered
3. **[ConfigManager](design/config-manager.md)** - How it all fits together
4. **[Name Matching](design/name-matching.md)** - How names map between sources

For implementing features:

1. Start with [ConfigParts](design/config-parts.md) for the data model
2. Review [ConfigManager](design/config-manager.md) for the API
3. Check [Feedback Loops](design/feedback-loops.md) for advanced patterns
