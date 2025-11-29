# Name Matching and Resolution

## Overview

Name matching connects field names in ConfigParts to:
- CLI argument names
- Environment variable names
- Config file keys
- Nested paths

## Name Transformation Rules

### 1. Field Name to CLI Argument

Python field name → CLI argument:

```python
class AppConfig(ConfigPart):
    log_level: str     # → --log-level
    debug_mode: bool   # → --debug-mode / --no-debug-mode
    max_workers: int   # → --max-workers
```

**Rules:**
- Snake case → kebab case
- Prefix with `--`
- Boolean fields get `--no-` variant

### 2. Field Name to Environment Variable

Python field name → environment variable:

```python
class AppConfig(ConfigPart):
    log_level: str     # → APP_LOG_LEVEL
    debug_mode: bool   # → APP_DEBUG_MODE
    max_workers: int   # → APP_MAX_WORKERS
```

**Rules:**
- Snake case → upper case with underscores
- Add prefix if specified
- Nested fields use underscore separator

### 3. Field Name to Config File Key

Python field name → config file key:

```toml
[AppConfig]
log_level = "INFO"      # Exact match
debug_mode = true       # Exact match
max_workers = 4         # Exact match
```

**Rules:**
- Exact match (preserve snake_case)
- Nested as sections or dot notation

## Prefixes

### ConfigPart-Level Prefix

```python
class DatabaseConfig(ConfigPart, prefix="db"):
    host: str = "localhost"
    port: int = 5432

# Results in:
# CLI: --db-host, --db-port
# Env: DB_HOST, DB_PORT
# File: [DatabaseConfig] or db.host in flat notation
```

### Field-Level Prefix

```python
from cot.config._annotations import PrefixMarker

class AppConfig(ConfigPart):
    database: DatabaseConfig @ PrefixMarker("db")
    
# Nested field access:
# CLI: --db-host
# Env: DB_HOST
```

## Nested Field Resolution

### Path Notation

```python
class ServerConfig(ConfigPart):
    host: str
    port: int

class AppConfig(ConfigPart):
    server: ServerConfig

# Access paths:
# - server.host
# - server.port
```

### Flattening Strategies

#### 1. Underscore Flattening (CLI/Env)

```python
# server.host → --server-host
# server.port → --server-port
# server.host → SERVER_HOST (with prefix)
```

#### 2. Section Flattening (Config Files)

```toml
[AppConfig.server]
host = "localhost"
port = 8000

# OR dot notation:
[AppConfig]
server.host = "localhost"
server.port = 8000
```

## Name Collision Handling

### Explicit Naming

```python
class Config(ConfigPart):
    # Override default name transformation
    @field(cli_name="--verbose", env_name="VERBOSE")
    verbosity: int
```

### Disambiguation

When multiple ConfigParts have same field names:

```python
class Database1Config(ConfigPart, prefix="db1"):
    host: str

class Database2Config(ConfigPart, prefix="db2"):
    host: str

# CLI: --db1-host vs --db2-host
# Env: DB1_HOST vs DB2_HOST
```

## Case Sensitivity

### File Formats

- **TOML**: Case-sensitive
- **JSON**: Case-sensitive
- **INI**: Case-insensitive (by convention)
- **YAML**: Case-sensitive

### Normalization

```python
# Environment variables: normalize to upper case
env_name = field_name.upper().replace("-", "_")

# CLI args: normalize to lowercase
cli_name = field_name.lower().replace("_", "-")
```

## Special Names

### Reserved Names

Avoid using these as field names:
- `help` (conflicts with CLI help)
- `version` (conflicts with version flag)
- `config` (conflicts with config file flag)

### Aliasing

```python
class Config(ConfigPart):
    @field(aliases=["v", "verbosity"])
    verbose: int
    
# CLI: --verbose, -v, --verbosity all work
```

## Design Questions

1. **Alias Syntax**: How to declare field aliases?
2. **Name Conflicts**: Hard error or warning?
3. **Custom Transformers**: Allow user-defined name transformation?
4. **Backwards Compatibility**: Support legacy naming schemes?
5. **Validation**: Check for name collisions at registration time?

## Examples

### Simple Prefix

```python
class LogConfig(ConfigPart, prefix="log"):
    level: str = "INFO"
    file: Path | None = None

# CLI: --log-level INFO --log-file app.log
# Env: LOG_LEVEL=INFO LOG_FILE=app.log
# File: [LogConfig] level = "INFO"
```

### Nested with Prefix

```python
class DatabaseConfig(ConfigPart, prefix="db"):
    host: str = "localhost"
    port: int = 5432

class AppConfig(ConfigPart, prefix="app"):
    name: str = "myapp"
    database: DatabaseConfig

# CLI: --app-name myapp --db-host localhost --db-port 5432
# Env: APP_NAME=myapp DB_HOST=localhost DB_PORT=5432
```

### Multiple Levels

```python
class PoolConfig(ConfigPart):
    size: int = 10

class DatabaseConfig(ConfigPart, prefix="db"):
    host: str
    pool: PoolConfig

class AppConfig(ConfigPart):
    database: DatabaseConfig

# CLI: --db-host localhost --db-pool-size 20
# Path: database.pool.size
```
