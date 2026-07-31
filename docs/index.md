# cot.config.ingest

Type-safe configuration management with multi-source ingestion.

## Overview

`cot.config.ingest` is an experimental Python library that simplifies configuration management by providing a unified way to ingest configuration from:

- **CLI arguments** (built-in parser, no argparse required)
- **Environment variables**
- **Configuration files** (TOML, INI)

The library uses dataclass-like `ConfigPart` classes to define configuration structure, then automatically handles loading and merging from multiple sources.

## Key Features

- **Type-safe configuration** with Python type hints
- **Multiple sources** with automatic merging and precedence
- **Origin tracking** to debug where values come from
- **Hierarchical configs** with SubConfig composition
- **Value cascade** from parent config to sub-configs via `from_parent`
- **Bootstrap feedback** — config files and `addopts` discovered from earlier stages

> Not implemented yet: plugin discovery, list append/reset merge semantics, change
> notification and hot reload. Those appear in the design documents as intent only.

## Quick Example

```python
import sys
from typing import Annotated

from cot.config import (
    CLISource, ConfigManager, ConfigPart, EnvSource, SubConfig, from_parent,
)

class DatabaseConfig(SubConfig):
    host: Annotated[str, from_parent] = "localhost"
    port: int = 5432

class AppConfig(ConfigPart, prefix="app"):
    debug: bool = False
    database: DatabaseConfig

manager = ConfigManager(sources=[
    CLISource(sys.argv[1:]),
    EnvSource("APP"),
])
config = manager.register_fragment_type(AppConfig)

print(f"Connecting to {config.database.host}:{config.database.port}")
```

`register_fragment_type()` returns the loaded instance; `manager.get_fragment(AppConfig)`
retrieves it again later.

## Project Status

**Experimental**: the API is still moving. See `AGENTS.md` for the as-built architecture.

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
