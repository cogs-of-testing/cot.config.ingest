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

## ConfigPart Features

### 1. Type Annotations

All fields must have type annotations that guide:
- Parsing from different sources (CLI, files, env)
- Validation
- Serialization

```python
class DatabaseConfig(ConfigPart):
    host: str                    # Required field
    port: int = 5432            # Optional with default
    ssl: bool = False           # Boolean flag
    options: list[str] = []     # List field
    timeout: float | None = None  # Optional nullable
```

### 2. SubConfig Composition

ConfigParts can contain other ConfigParts:

```python
class ServerConfig(ConfigPart):
    host: str = "localhost"
    port: int = 8000

class AppConfig(ConfigPart):
    debug: bool = False
    server: ServerConfig
    database: DatabaseConfig
```

### 3. Prefixes

ConfigParts can have prefixes for CLI args and env vars:

```python
class DatabaseConfig(ConfigPart, prefix="db"):
    """
    Fields become:
    - CLI: --db-host, --db-port
    - Env: DB_HOST, DB_PORT
    """
    host: str = "localhost"
    port: int = 5432
```

### 4. Help Text

Fields can include help text for CLI generation:

```python
from cot.config._annotations import help

class AppConfig(ConfigPart):
    debug: bool @ help("Enable debug mode") = False
    verbose: int @ help("Verbosity level (0-3)") = 0
```

### 5. From Parent Values

Sub-configs can inherit values from parent context:

```python
from cot.config._annotations import from_parent

class SubConfig(ConfigPart):
    # This field will be populated from parent's context
    root_dir: Path @ from_parent
    name: str
```

## Special ConfigParts

### Bootstrap ConfigParts

Bootstrap ConfigParts are loaded early to determine HOW to load the rest of configuration:

```python
class InvocationConfig(ConfigPart, bootstrap=True):
    """Loaded first with invocation parameters."""
    invocation_dir: Path
    invocation_args: list[str]
    plugins: list[str] = []
```

### File Discovery ConfigParts

These trigger reconfiguration when config files are discovered:

```python
class ConfigFileConfig(ConfigPart, bootstrap=True, discover_files=True):
    """Discovering config files triggers loader reconfiguration."""
    config: Path | None = None
    config_files: list[Path] = []
```

## Field Types

### Supported Types

| Python Type | CLI Representation | File Format | Environment |
|------------|-------------------|-------------|-------------|
| `str` | `--field value` | `"value"` | `FIELD=value` |
| `int` | `--field 42` | `42` | `FIELD=42` |
| `float` | `--field 3.14` | `3.14` | `FIELD=3.14` |
| `bool` | `--field` / `--no-field` | `true` / `false` | `FIELD=1` / `FIELD=0` |
| `Path` | `--field /path` | `"/path"` | `FIELD=/path` |
| `list[T]` | `--field a --field b` | `["a", "b"]` | `FIELD=a,b` |
| `T \| None` | Optional flag | `null` or value | Empty or value |

### List Handling

Lists support multiple modes:

```python
class Config(ConfigPart):
    # Default: append mode
    items: list[str] = []
    
    # CLI: --items a --items b --items c
    # File1: items = ["a"]
    # File2: items = ["b"] 
    # Result: ["a", "b", "c"]
```

## Metadata and Markers

ConfigParts use markers for field-level metadata:

```python
from cot.config._annotations import help, from_parent, PrefixMarker

class ExampleConfig(ConfigPart):
    # Help text
    debug: bool @ help("Enable debugging") = False
    
    # Inherit from parent
    root: Path @ from_parent
    
    # Custom prefix for sub-config
    database: DatabaseConfig @ PrefixMarker("db")
```

## Frozen Behavior

ConfigParts are **immutable after creation**:

```python
config = AppConfig(debug=True)
config.debug = False  # ❌ AttributeError: Cannot modify frozen attribute
```

This ensures configuration remains consistent once loaded.

## Validation

*To be designed: validation hooks, custom validators*

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
class DatabaseConfig(ConfigPart, prefix="db"):
    host: str = "localhost"
    port: int = 5432
    name: str = "app_db"

class CacheConfig(ConfigPart, prefix="cache"):
    enabled: bool = True
    ttl: int = 3600

class AppConfig(ConfigPart):
    app_name: str = "myapp"
    database: DatabaseConfig
    cache: CacheConfig
```

### With Help Text

```python
class ServerConfig(ConfigPart):
    host: str @ help("Server hostname") = "localhost"
    port: int @ help("Server port number") = 8000
    workers: int @ help("Number of worker processes") = 4
```
