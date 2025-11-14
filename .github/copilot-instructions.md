# cot.config.ingest AI Coding Agent Instructions

## Project Overview

This is an **experimental** Python library for type-safe configuration management. It enables declarative configuration through dataclass-like `Config` classes that can ingest values from multiple sources (CLI args, environment variables, config files) with automatic merging and origin tracking.

**Key inspiration**: Solving pytest's configuration complexity where CLI args and ini options are handled differently, making it difficult to add `pyproject.toml` support.

## Architecture

### Core Design Pattern: Three-Phase Initialization

The `Config` class uses `__init_subclass__` with a three-phase instance initialization:

1. **Phase 1**: Initialize regular fields (non-subconfigs) from kwargs or defaults
2. **Phase 2**: Initialize sub-configs AFTER parent fields exist (enables `from_parent` propagation)
3. **Phase 3**: Set any additional kwargs not defined as fields

This phase separation is **critical** - sub-configs need parent field values available for `from_parent` inheritance.

### Field Descriptors vs. Actual Values

**Important**: `field()` and `sub_config()` return descriptor objects at class definition time, NOT the actual field values. The `__init_subclass__` method collects these descriptors into `__fields_config` (a `FieldsConfig` dict). Instance attributes are created in `__init__`.

### Name Mapping Convention

The library uses consistent name transformations across sources:

- **Python fields**: `snake_case` (e.g., `log_level`)
- **CLI args**: `--kebab-case` with optional prefix (e.g., `--app-log-level`)
- **Environment vars**: `UPPER_SNAKE_CASE` with optional prefix (e.g., `APP_LOG_LEVEL`)
- **Sub-config fields**: underscore-prefixed (e.g., `db_host` for `database.host`)

See `src/cot/config/_name_mapping.py` for transformation functions.

### Adapters Pattern

Each source type has an adapter (in `src/cot/config/adapters/`):

- **`EnvironmentAdapter`**: Extracts config from env vars, handles parsing (bool, int, float, TOML-inline, lists)
- **`ConfigToArgparseAdapter`**: Registers config with `ArgumentParser`, extracts values from `Namespace`
- **`PytestAdapter`**: Specialized for pytest's config/parser integration

Adapters use `extract_config()` to return a dict that can be passed to `Config(**dict)`.

## Critical Developer Workflows

### Running Tests

```bash
# Use hatch, not pytest directly
hatch test testing/                      # All tests
hatch test testing/test_basic_usage.py  # Single file
hatch test testing/ -k test_name        # Specific test
```

**Why hatch**: Manages Python environment and dependencies automatically. Never run `pytest` bare in terminal.

### Code Quality

```bash
pre-commit run -a     # Run all checks (ruff, mypy, etc.)
```

The project uses:
- **ruff**: Linting and formatting (configured in `pyproject.toml`)
- **mypy**: Type checking with `strict = true`
- **pytest-cov**: Coverage tracking

### Type Checking Patterns

The codebase is **fully type-annotated** with `mypy --strict`. Common patterns:

- `from __future__ import annotations` at top of every file (enables forward refs)
- `if TYPE_CHECKING:` blocks for import-only types
- Extensive use of `TypeAlias`, `TypeVar`, `Generic` for generic config classes
- `dataclass_transform()` decorator on `Config` class for editor support

## Project-Specific Conventions

### The `from_parent` Feature

Sub-configs can inherit field values from parent configs using the `from_parent` marker:

```python
class LogConfig(Config):
    level: str = field(from_parent, default="INFO")  # Gets value from parent's 'level' field

class AppConfig(Config):
    level: str = field(default="DEBUG")
    logging: LogConfig = sub_config(LogConfig)
```

**Implementation**: `Config._merge_parent_values()` looks for fields with `from_parent=True` and copies values from parent instance during Phase 2 initialization. Test coverage in `testing/test_from_parent_values.py`.

### ConfigLoader: The Recommended Loading Pattern

Don't use `Config.from_data()` directly for complex scenarios. Use `ConfigLoader`:

```python
loader = ConfigLoader(AppConfig, env_prefix="APP", debug=True)
loader.load_file("config.toml")
loader.load_env()
loader.load_cli()
config = loader.build()
```

**Why**: `ConfigLoader` provides:
- **Source tracking**: Records where each value came from (file line, env var, CLI arg)
- **Correct merge order**: file → env → code → CLI (CLI has highest precedence)
- **Debug info**: Attach provenance metadata with `debug=True`
- **Nested field tracking**: Tracks `db.host` separately from `db.port` for sub-configs

See `src/cot/config/loader.py` for implementation details.

### Deep Merge Semantics

When merging dicts from multiple sources, the library does **deep recursive merge**, not shallow replace:

```python
source1 = {"database": {"host": "localhost", "port": 5432}}
source2 = {"database": {"port": 3306}}  # Only overrides port, keeps host
```

**Critical implementation detail**: `ConfigLoader._merge_data()` has special handling for sub-config instances (converts them to dicts) and treats explicit `None` values carefully to avoid wiping file data. See `_track_source_values()` for the mirrored provenance tracking.

### Debug and Provenance

When `debug=True` is enabled, config instances get a `_debug_info` attribute (private). Access via helper functions in `src/cot/config/debug.py`:

```python
from cot.config.debug import get_config_report, get_value_source, get_override_chain

report = get_config_report(config)  # Human-readable report
source = get_value_source(config, "db.host")  # SourceInfo for specific field
chain = get_override_chain(config, "port")  # List of all overrides
```

**Nested provenance**: Uses dotted paths like `"db.host"` for sub-config fields. Tests in `testing/test_provenance.py`.

## Common Patterns

### Defining a Config Class

```python
from cot.config import Config, field, sub_config, from_parent

class DatabaseConfig(Config):
    host: str = field(default="localhost", help="Database host")
    port: int = field(default=5432)

class AppConfig(Config, prefix="app"):  # prefix for CLI/env names
    debug: bool = field(default=False, action="store_true")  # Boolean CLI flag
    paths: list[str] = field(default_factory=list, action="append")  # Multi-value
    database: DatabaseConfig = sub_config(DatabaseConfig, primary="host")  # primary field
```

### Testing Configs

Test files are in `testing/` (not `tests/`). Common patterns:

- `tmp_path` fixture for file-based tests
- Mock `environ` dicts (don't modify `os.environ`)
- Use `argparse.Namespace` objects for CLI testing
- Check equality with `assert config1 == config2` (implements `__eq__`)

## Integration Points

### External Dependencies

- **Required**: `typing-extensions>=4` (for `@dataclass_transform`, backports)
- **Optional**: `PyYAML` (for YAML config files), `tomli_w` (for TOML writing)
- **Built-in**: `tomllib` (Python 3.11+ for reading TOML)

### File Loaders

`src/cot/config/loaders.py` provides format detection by extension:
- `.json` → `load_json()`
- `.toml` → `load_toml()`
- `.yaml`, `.yml` → `load_yaml()` (requires PyYAML)

Auto-detection via `load_file(path)` checks `path.suffix`.

## Important Constraints

1. **No multiple inheritance for field merging**: Sub-configs inherit fields via `__mro__`, but complex MI can cause issues. Keep inheritance simple.

2. **Prefix handling**: Config classes can have a `prefix` parameter in definition. Both adapters respect this, but it's applied differently:
   - CLI: `--prefix-field-name`
   - Env: `PREFIX_FIELD_NAME`

3. **Sub-config kwargs**: When passing sub-config data as dict to parent `__init__`, it auto-converts to sub-config instance during Phase 2. Test this pattern in `testing/test_field_features.py`.

4. **Type annotations required**: Fields MUST have type annotations. The `field()` descriptor doesn't infer types.

## Current Implementation Status

✅ **Implemented**: Core Config class, field descriptors, sub-configs, from_parent, argparse/env/pytest adapters, JSON/TOML/YAML loaders, ConfigLoader with provenance

⚠️ **Experimental**: API may change. Not recommended for production use yet.

🔜 **Future work**: Better TOML/YAML nested structure handling, validation, CLI sub-commands, backward compatibility layers
