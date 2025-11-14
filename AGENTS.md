# AI Coding Agent Instructions

## Project Overview

This is an **experimental** Python library for type-safe configuration management. It enables declarative configuration through dataclass-like `Config` classes that can ingest values from multiple sources (CLI args, environment variables, config files) with automatic merging and origin tracking.

**Key inspiration**: Solving pytest's configuration complexity where CLI args and ini options are handled differently, making it difficult to add `pyproject.toml` support.

## Project Status: ARCHITECTURE REBUILD IN PROGRESS

🚧 **CRITICAL**: The project is currently undergoing a complete architectural redesign. All previous adapter code has been removed. We are rebuilding from scratch with a new design:

### New Architecture (In Progress)

**Core Concept**: Origins → Fragments → Config

1. **ConfigFragment**: Represents a single configuration value with metadata
   - `field_path`: Dotted path (e.g., "database.host")
   - `value`: The actual value
   - `origin_type`: "file", "env", "cli", "code"
   - `origin_location`: Where it came from (e.g., "config.toml:line 5", "DB_HOST")

2. **Origins**: Data loaders that produce fragments
   - `FileOrigin(filename)`: Loads from config files
   - `EnvOrigin(prefix)`: Loads from environment variables
   - `CLIOrigin(prefix, args)`: Loads from command-line arguments
   - Each has a `load() -> list[Fragment]` method

3. **Adapters**: Bidirectional name mapping
   - Maps between origin-specific names and config field paths
   - `env_name_to_field_path("APP_DB_HOST")` → `"database.host"`
   - `field_path_to_env_name("database.host")` → `"APP_DB_HOST"`
   - Origins use adapters during `load()` to create properly mapped fragments

4. **ConfigLoader**: Orchestrates origins and fragments
   - Registers multiple origins
   - Collects all fragments
   - Provides views: get all fragments, get final value (handles precedence)
   - Builds final Config instance

### Current State

- ✅ All old code removed (`src/cot/config/` is empty)
- ✅ All old tests removed (`testing/` is empty)
- 🚧 Ready to implement new architecture
- 🚧 No existing code to reference - build from scratch

## Critical Developer Workflows

### Running Tests

```bash
# Use hatch, not pytest directly
hatch test testing/                      # All tests
hatch test testing/test_basic_usage.py  # Single file
hatch test testing/ -- -k test_name     # Specific test
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

The codebase should be **fully type-annotated** with `mypy --strict`. Common patterns:

- `from __future__ import annotations` at top of every file (enables forward refs)
- `if TYPE_CHECKING:` blocks for import-only types
- Extensive use of `TypeAlias`, `TypeVar`, `Generic` for generic config classes
- `dataclass_transform()` decorator on `Config` class for editor support

## Integration Points

### External Dependencies

- **Required**: `typing-extensions>=4` (for `@dataclass_transform`, backports)
- **Optional**: `PyYAML` (for YAML config files), `tomli_w` (for TOML writing)
- **Built-in**: `tomllib` (Python 3.11+ for reading TOML)

## Important Constraints

1. **Type annotations required**: Fields MUST have type annotations. The `field()` descriptor doesn't infer types.

2. **Test location**: Test files go in `testing/` (not `tests/`)

3. **No multiple inheritance for field merging**: Sub-configs inherit fields via `__mro__`, but complex MI can cause issues. Keep inheritance simple.

## Implementation Status

⚠️ **EXPERIMENTAL**: Complete architectural redesign in progress. API will change significantly.

🔜 **Next steps**: Implement ConfigFragment, Origins, Adapters, and ConfigLoader with the new architecture
