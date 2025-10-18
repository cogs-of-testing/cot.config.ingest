# cot.config.ingest

Type annotations and helpers to ingest configuration from multiple sources.

## Overview

`cot.config.ingest` is an experimental Python library that simplifies configuration management by providing a unified way to ingest configuration from:

- **CLI arguments** (via argparse/click/others)
- **Environment variables**
- **Configuration files** (JSON, TOML, YAML)

The library uses dataclass-like `Config` classes with field descriptors to define configuration structure, then automatically handles loading and merging from multiple sources.

## Key Features

- 🎯 **Type-safe configuration** with Python type hints
- 🔄 **Multiple sources** with automatic merging
- 🔍 **Origin tracking** to debug where values come from
- 🏗️ **Hierarchical configs** with sub-configurations
- 🧬 **Field inheritance** with `from_parent` support
- 🔧 **Adapter pattern** for different configuration sources

## Quick Example

```python
from cot.config import Config, field, sub_config

class DatabaseConfig(Config):
    host: str = field(default="localhost")
    port: int = field(default=5432)
    name: str = field()

class AppConfig(Config):
    debug: bool = field(default=False)
    database: DatabaseConfig = sub_config(DatabaseConfig)

# Load from multiple sources
config = AppConfig.load(
    cli_args=parser.parse_args(),
    env_prefix="APP",
    config_file="config.toml"
)

print(f"Connecting to {config.database.host}:{config.database.port}")
```

## Project Status

⚠️ **Experimental**: This is an early experiment that may undergo significant changes.

Currently implemented:
- ✅ Basic Config class with dataclass-like behavior
- ✅ Field descriptors with metadata
- ✅ Sub-configuration support
- ✅ Field inheritance with `from_parent`
- ✅ Adapters for argparse, environment, pytest
- ✅ File loaders for JSON, TOML, YAML

## Next Steps

- 📖 Check out the [Installation](getting-started/installation.md) guide
- 🚀 Follow the [Quick Start](getting-started/quickstart.md) tutorial
- 💡 Read about the [Inspiration](getting-started/inspiration.md) behind the project