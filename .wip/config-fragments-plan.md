# Configuration Fragments: Origin Tracking and Debugging

## Design Summary (Refined)

This plan proposes a **three-phase fragment system** for configuration loading with complete origin tracking:

### Phase 1: Loading
**Loaders produce `LoadedData` instances** containing raw data in their native format:
- CLI adapter → flat dict with dash-separated keys (`{"debug": True, "database-host": "..."}`)
- ENV adapter → flat dict with underscore-separated keys (`{"APP_DATABASE_HOST": "..."}`)
- File loader → nested dict matching file structure (`{"database": {"host": "..."}}`)
- Defaults extractor → nested dict from Config field defaults

Each `LoadedData` includes `LoaderInfo` metadata (loader type, location, etc.)

### Phase 2: Transformation
**Transform `LoadedData` → `ConfigFragment` using Config class structure:**
- `FieldExtractor` walks the Config class to discover field paths
- `FieldPathMapper` (provided by loader/adapter) translates Config field paths to loader keys
  - `EnvFieldMapper`: `("database", "host")` → `"APP_DATABASE_HOST"`
  - `ArgparseFieldMapper`: `("database", "host")` → `"database-host"`
  - `NestedFieldMapper`: `("database", "host")` → lookup in `data["database"]["host"]`
- Result: `ConfigFragment` with nested `field_values` showing which Config fields this loader provides

### Phase 3: Merging
**Merge fragments in priority order (first wins) to produce final config:**
- Priority order: CLI → ENV → FILE → DEFAULTS
- Deep merge: first fragment with a value wins
- `MergedFragment` tracks which loader provided each final value
- Complete audit trail: field path → loader → original value

### Key Insight
The Config class structure drives the transformation. Mappers don't parse strings; they use the known field paths to construct lookup keys in the loader's namespace.

---

## Motivation

When building configurations from multiple sources (CLI args, env vars, config files), we need to:

1. **Track origins** - Know exactly where each value came from
2. **Debug merging** - Understand how values were combined in load order
3. **Express partial configs** - Represent incomplete configuration from a single loader
4. **Explain resolution** - Show which loader provided the final value

Note: `from_parent` inheritance is a Config initialization concern, not a fragment concern.

## Current State

### Existing Implementation ✅

The project already has basic origin tracking in `src/cot/config/source_info.py`:

- **`SourceType`** - Enum for source types (FILE, ENV, CLI, CODE, DEFAULT, etc.)
- **`SourceInfo`** - Metadata about where a value came from
  - Tracks location (file path, env var name, CLI flag)
  - Maintains override chain via `previous_source`
  - Counts overrides
- **`ConfigValue`** - Wrapper pairing a value with its SourceInfo
- **`ConfigDebugInfo`** - Debug report generator for a config instance

### Current Limitations ❌

1. **No fragment representation** - Can't represent partial/incomplete configs from a single loader
2. **No merge visualization** - Hard to see how fragments combine in load order
3. **Single-field focus** - Tracks fields independently, not as coherent fragments
4. **No structured API** - Debug info is mainly for reporting, not programmatic use
5. **No diff support** - Can't compare fragments or show what changed
6. **Enum-based origins** - SourceType enum limits extensibility for custom loaders

---

## Proposed Design: Configuration Fragments

### Core Concept

The fragment system separates **loading** from **transformation** to enable powerful debugging and origin tracking:

**Key insight:** Instead of loaders directly producing config-ready data, they produce `LoadedData` (raw data + metadata). This raw data is then **transformed** into `ConfigFragment` instances using the Config class structure as a guide.

#### Two-Phase Process

1. **Loading Phase**: Each loader (CLI, ENV, FILE, DEFAULTS) produces `LoadedData`
   - Contains raw data in the loader's native format (flat ENV vars, nested TOML, etc.)
   - Includes metadata about the loader instance and source location
   - Happens once per source

2. **Transform Phase**: Given a Config class, transform `LoadedData` → `ConfigFragment`
   - Uses a `FieldExtractor` that walks the Config class structure
   - A `FieldPathMapper` (provided by the loader/adapter) translates Config field paths to loader keys
   - Produces nested `field_values` dict showing which Config fields this loader provides
   - Results in a list of fragments, one per loader

3. **Merge Phase**: Merge fragments in priority order (first wins) to produce final config data

#### Benefits

- **Load once, transform many times**: Same LoadedData can be transformed against different Config schemas
- **Clear separation**: Loaders don't need to know about Config structure; mappers handle the translation
- **Powerful debugging**: Each fragment shows exactly which Config fields came from which loader
- **Extensible**: New loader types just need a FieldPathMapper implementation
- **Traceable**: Complete audit trail from loader → field path → final value

```python
@dataclass
class LoadedData:
    """
    Raw configuration data from a single loader instance.

    This is what loaders produce - the data they extracted
    and metadata about where it came from.
    """

    # Raw nested data (dicts, lists, primitives)
    data: dict[str, Any]

    # Metadata about this loader instance
    loader: LoaderInfo

    # When this was loaded
    timestamp: datetime = field(default_factory=datetime.now)

    # Hash of source for change detection (optional)
    source_hash: str | None = None


@dataclass
class LoaderInfo:
    """Information about a loader instance."""

    # The loader class type (not an enum - use actual class)
    loader_type: type

    # Specific source location
    location: str | None = None  # file path, env prefix, CLI command, etc.

    # Additional source-specific metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # Optional: reference to loader instance for introspection
    loader_instance: Any = None

    def __str__(self) -> str:
        """Human-readable loader description."""
        name = self.loader_type.__name__
        if self.location:
            return f"{name}:{self.location}"
        return name


@dataclass
class ConfigFragment:
    """
    A structured view of which config fields came from a specific loader.

    Created by transforming LoadedData against a Config class definition.
    Maps config field paths to their values, showing exactly which fields
    this loader provided.
    """

    # Nested mapping: field path -> value
    # Only contains fields present in the loader's data
    field_values: dict[str, Any]

    # Which loader this came from
    loader: LoaderInfo

    # The config class this fragment represents
    config_class: type
```

### Field Path Mapping

The Config class structure determines field paths. A mapper uses this structure to extract values from loader data:

```python
@dataclass
class FieldPath:
    """
    Represents a path to a config field and how to locate it in loader data.

    The Config class structure determines the field path.
    Each loader's mapper knows how to find this field in its data.
    """

    # Canonical field path in Config structure
    # e.g., ("database", "host") for config.database.host
    path: tuple[str, ...]

    # How this field maps in the loader's namespace
    # e.g., "APP_DATABASE_HOST" for env, "--database-host" for CLI
    loader_key: str

    # The Config field this came from
    field_type: type

    def __str__(self) -> str:
        return ".".join(self.path)


class FieldExtractor:
    """
    Extracts config field values from loader data.

    Walks the Config class structure to build field paths,
    then uses loader-specific mapping to find values.
    """

    def __init__(
        self,
        config_class: type[Config],
        loader: LoaderInfo,
        mapper: "FieldPathMapper"
    ):
        self.config_class = config_class
        self.loader = loader
        self.mapper = mapper

    def extract_fragment(self, loaded_data: LoadedData) -> ConfigFragment:
        """
        Extract a fragment by walking Config structure and finding values.

        Process:
        1. Walk config_class fields to discover field paths
        2. For each field path, ask mapper where to find it in loaded_data
        3. Extract value if present
        4. Build nested field_values dict
        """
        field_values = self._extract_fields(
            self.config_class,
            loaded_data.data,
            path_prefix=()
        )

        return ConfigFragment(
            field_values=field_values,
            loader=loaded_data.loader,
            config_class=self.config_class
        )

    def _extract_fields(
        self,
        config_class: type[Config],
        data: dict[str, Any],
        path_prefix: tuple[str, ...]
    ) -> dict[str, Any]:
        """
        Recursively extract fields from data based on config structure.

        The config_class defines what fields exist.
        The mapper tells us how to find them in data.
        """
        result = {}
        fields = getattr(config_class, "__config_fields__", {})

        for field_name, field_info in fields.items():
            field_path = path_prefix + (field_name,)

            # Ask mapper where to find this field in the data
            lookup_key = self.mapper.get_lookup_key(field_path, field_info)

            # Try to find value in data
            value = self._lookup_value(data, lookup_key)

            if value is MISSING:
                continue  # This loader doesn't have this field

            # Handle nested Config fields
            if isinstance(value, dict) and self._is_config_class(field_info.type):
                nested_result = self._extract_fields(
                    field_info.type,
                    value,
                    path_prefix=field_path
                )
                if nested_result:
                    result[field_name] = nested_result
            else:
                result[field_name] = value

        return result

    def _lookup_value(self, data: dict[str, Any], key: str) -> Any:
        """Look up a value using the mapper's key format."""
        return data.get(key, MISSING)

    @staticmethod
    def _is_config_class(type_hint: Any) -> bool:
        try:
            return issubclass(type_hint, Config)
        except (TypeError, AttributeError):
            return False


class FieldPathMapper(Protocol):
    """
    Protocol for mapping Config field paths to loader keys.

    Each loader type provides an implementation that knows how to
    construct lookup keys in its namespace.
    """

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_info: Any
    ) -> str:
        """
        Given a config field path, return the key to look up in loader data.

        Examples:
            EnvMapper: ("database", "host") -> "DATABASE_HOST" (with prefix handling)
            ArgparseMapper: ("database", "host") -> "database-host"
            NestedMapper: ("database", "host") -> "host" (looks in data["database"])
        """
        ...


class EnvFieldMapper:
    """Maps Config fields to environment variable names."""

    def __init__(self, prefix: str = "", separator: str = "_"):
        self.prefix = prefix
        self.separator = separator

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_info: Any
    ) -> str:
        """
        Build ENV var name from field path.

        ("database", "host") -> "APP_DATABASE_HOST"
        """
        parts = [p.upper() for p in field_path]
        key = self.separator.join(parts)
        if self.prefix:
            key = f"{self.prefix}{self.separator}{key}"
        return key


class ArgparseFieldMapper:
    """Maps Config fields to CLI argument names."""

    def __init__(self, separator: str = "-"):
        self.separator = separator

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_info: Any
    ) -> str:
        """
        Build CLI arg name from field path.

        ("database", "host") -> "database-host"
        """
        return self.separator.join(field_path)


class NestedFieldMapper:
    """Maps Config fields for already-nested data (TOML, JSON, YAML)."""

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_info: Any
    ) -> str:
        """
        For nested data, just use the immediate field name.

        The FieldExtractor handles traversing nested dicts.
        """
        return field_path[-1] if field_path else ""
```

### Fragment Workflow: Load → Transform → Merge

The complete workflow:

```python
# 1. Define loaders with their mappers
loaders_with_mappers = [
    (cli_adapter, ArgparseFieldMapper()),
    (env_adapter, EnvFieldMapper(prefix="APP")),
    (file_loader, NestedFieldMapper()),
    (defaults_extractor, DefaultsMapper()),  # Always last
]

# 2. Load data from each source
loaded_data_list: list[LoadedData] = []
for loader, _ in loaders_with_mappers:
    loaded = loader.load()  # Returns LoadedData
    loaded_data_list.append(loaded)

# 3. Transform each LoadedData to ConfigFragment
fragments: list[ConfigFragment] = []
for loaded, (_, mapper) in zip(loaded_data_list, loaders_with_mappers):
    extractor = FieldExtractor(AppConfig, loaded.loader, mapper)
    fragment = extractor.extract_fragment(loaded)
    fragments.append(fragment)

# 4. Merge fragments (first wins)
merged_data = merge_fragments(fragments)

# 5. Create config from merged data
config = AppConfig.from_data(merged_data)

# 6. Attach fragment info for debugging
config._fragments = fragments
config._merged_fragment = create_merged_fragment(fragments)
```

### Merging Strategy (First Wins)

**Fragments are merged in priority order where FIRST wins. Defaults come LAST.**

Load order: **CLI → ENV → FILE → DEFAULTS**

```python
def merge_fragments(fragments: list[ConfigFragment]) -> dict[str, Any]:
    """
    Deep merge fragments where FIRST fragment wins.

    Args:
        fragments: List in priority order (highest priority first)

    Returns:
        Merged nested dict ready for Config.from_data()
    """
    # Process from last to first, so first wins
    result: dict[str, Any] = {}

    for fragment in reversed(fragments):
        result = _deep_merge_into(fragment.field_values, result)

    return result


def _deep_merge_into(
    source: dict[str, Any],
    target: dict[str, Any]
) -> dict[str, Any]:
    """
    Recursively merge source into target, source takes precedence.

    Args:
        source: Higher priority dict (wins conflicts)
        target: Lower priority dict (gets overridden)

    Returns:
        Merged dict
    """
    result = target.copy()

    for key, value in source.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Both are dicts - recurse
            result[key] = _deep_merge_into(value, result[key])
        else:
            # source wins
            result[key] = value

    return result


class MergedFragment:
    """
    Tracks the result of merging multiple fragments.

    Preserves which loader provided each final value.
    """

    def __init__(self, fragments: list[ConfigFragment]):
        self.fragments = fragments
        self.data = merge_fragments(fragments)
        self._field_origins = self._build_field_origins()

    def _build_field_origins(self) -> dict[str, LoaderInfo]:
        """
        Build mapping of field path -> loader that provided it.

        For each field in final data, record which fragment (loader)
        provided the winning value.
        """
        origins = {}

        # Walk the merged data and track first fragment with each field
        for fragment in self.fragments:
            for field_path, value in self._flatten_fields(fragment.field_values):
                if field_path not in origins:
                    # This is the first fragment with this field
                    origins[field_path] = fragment.loader

        return origins

    def _flatten_fields(
        self,
        data: dict[str, Any],
        prefix: str = ""
    ) -> list[tuple[str, Any]]:
        """Flatten nested dict to list of (path, value) tuples."""
        result = []
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                result.extend(self._flatten_fields(value, prefix=path))
            else:
                result.append((path, value))
        return result

    def get_origin(self, field_path: str) -> LoaderInfo | None:
        """Get the loader that provided this field's value."""
        return self._field_origins.get(field_path)

    def get_all_origins(self, field_path: str) -> list[tuple[LoaderInfo, Any]]:
        """
        Get all loaders that had a value for this field (override chain).

        Returns list of (loader, value) tuples in priority order.
        """
        chain = []
        for fragment in self.fragments:
            value = self._get_nested_value(fragment.field_values, field_path)
            if value is not MISSING:
                chain.append((fragment.loader, value))
        return chain

    def _get_nested_value(self, data: dict[str, Any], path: str) -> Any:
        """Navigate nested dict using dot-separated path."""
        parts = path.split(".")
        current = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return MISSING
        return current
```

---

## Complete Example

Here's a complete example showing the workflow:

```python
from dataclasses import dataclass
from cot.config import Config, field


# 1. Define Config structure
class DatabaseConfig(Config):
    host: str = field(default="localhost")
    port: int = field(default=5432)
    name: str = field()


class AppConfig(Config):
    debug: bool = field(default=False)
    database: DatabaseConfig = field()


# 2. Setup loaders with mappers
# Each loader knows how to load data, mapper knows how to find fields in that data

## CLI Loader
cli_data = LoadedData(
    data={"debug": True, "database-host": "prod.db.com"},
    loader=LoaderInfo(
        loader_type=ArgparseAdapter,
        location="--debug --database-host prod.db.com"
    )
)
cli_mapper = ArgparseFieldMapper(separator="-")

## ENV Loader
env_data = LoadedData(
    data={"APP_DATABASE_PORT": "3306", "APP_DATABASE_NAME": "myapp"},
    loader=LoaderInfo(
        loader_type=EnvironmentAdapter,
        location="APP_*"
    )
)
env_mapper = EnvFieldMapper(prefix="APP", separator="_")

## File Loader (TOML)
file_data = LoadedData(
    data={
        "debug": False,
        "database": {
            "host": "staging.db.com",
            "port": 5432,
            "name": "staging_db"
        }
    },
    loader=LoaderInfo(
        loader_type=TomlFileLoader,
        location="/etc/app/config.toml"
    )
)
file_mapper = NestedFieldMapper()

## Defaults (from Config class)
defaults_data = LoadedData(
    data={
        "debug": False,
        "database": {
            "host": "localhost",
            "port": 5432
        }
    },
    loader=LoaderInfo(
        loader_type=DefaultsExtractor,
        location="AppConfig field defaults"
    )
)
defaults_mapper = NestedFieldMapper()


# 3. Transform each LoadedData to ConfigFragment
extractor_cli = FieldExtractor(AppConfig, cli_data.loader, cli_mapper)
fragment_cli = extractor_cli.extract_fragment(cli_data)
# fragment_cli.field_values = {
#     "debug": True,
#     "database": {"host": "prod.db.com"}
# }

extractor_env = FieldExtractor(AppConfig, env_data.loader, env_mapper)
fragment_env = extractor_env.extract_fragment(env_data)
# fragment_env.field_values = {
#     "database": {"port": 3306, "name": "myapp"}
# }

extractor_file = FieldExtractor(AppConfig, file_data.loader, file_mapper)
fragment_file = extractor_file.extract_fragment(file_data)
# fragment_file.field_values = {
#     "debug": False,
#     "database": {"host": "staging.db.com", "port": 5432, "name": "staging_db"}
# }

extractor_defaults = FieldExtractor(AppConfig, defaults_data.loader, defaults_mapper)
fragment_defaults = extractor_defaults.extract_fragment(defaults_data)
# fragment_defaults.field_values = {
#     "debug": False,
#     "database": {"host": "localhost", "port": 5432}
# }


# 4. Merge fragments (CLI > ENV > FILE > DEFAULTS)
fragments = [fragment_cli, fragment_env, fragment_file, fragment_defaults]
merged_data = merge_fragments(fragments)
# merged_data = {
#     "debug": True,                    # from CLI
#     "database": {
#         "host": "prod.db.com",        # from CLI
#         "port": 3306,                 # from ENV
#         "name": "myapp"               # from ENV
#     }
# }


# 5. Create config and track origins
config = AppConfig.from_data(merged_data)
merged_fragment = MergedFragment(fragments)

# 6. Debug: Find where each value came from
print(merged_fragment.get_origin("debug"))
# LoaderInfo(loader_type=ArgparseAdapter, location="--debug ...")

print(merged_fragment.get_origin("database.host"))
# LoaderInfo(loader_type=ArgparseAdapter, location="--debug ...")

print(merged_fragment.get_origin("database.port"))
# LoaderInfo(loader_type=EnvironmentAdapter, location="APP_*")

print(merged_fragment.get_origin("database.name"))
# LoaderInfo(loader_type=EnvironmentAdapter, location="APP_*")

# 7. Debug: See full override chain
print(merged_fragment.get_all_origins("database.host"))
# [
#     (LoaderInfo(ArgparseAdapter), "prod.db.com"),    # CLI wins
#     (LoaderInfo(TomlFileLoader), "staging.db.com"),  # FILE overridden
#     (LoaderInfo(DefaultsExtractor), "localhost")     # DEFAULT overridden
# ]
```

---

## Key Use Cases

### Use Case 1: Single Source Fragment

Represent configuration from one source (e.g., environment variables):

```python
# From environment
env_fragment = ConfigFragment(
    data={
        "database": {
            "host": "db.prod.com",
            "port": 5432
        },
        "debug": False
    },
    origin=FragmentOrigin(
        origin_type=FragmentOriginType.ENV_VARS,
        location="APP_*"
    )
)
```

### Use Case 2: Tracking Override Chain

Multiple fragments that override each other:

```python
# Priority: CLI > ENV > FILE > DEFAULTS

default_fragment = ConfigFragment(
    data={"log_level": "INFO", "log_format": "%(message)s"},
    origin=FragmentOrigin(origin_type=FragmentOriginType.DEFAULT_VALUES)
)

file_fragment = ConfigFragment(
    data={"log_level": "WARNING"},
    origin=FragmentOrigin(
        origin_type=FragmentOriginType.CONFIG_FILE,
        location="config.toml",
        line_range=(5, 7)
    )
)

env_fragment = ConfigFragment(
    data={"log_level": "DEBUG"},
    origin=FragmentOrigin(
        origin_type=FragmentOriginType.ENV_VARS,
        location="LOG_LEVEL"
    )
)

# Merge them
final = merge_fragments([default_fragment, file_fragment, env_fragment])

# final.log_level == "DEBUG"
# final.origin_chain["log_level"] == [env_fragment, file_fragment, default_fragment]
```

### Use Case 3: Tracking from_parent Inheritance

Show how values propagate from parent to child configs:

```python
# Parent config fragment
parent_fragment = ConfigFragment(
    data={"level": "DEBUG", "format": "[%(levelname)s] %(message)s"},
    origin=FragmentOrigin(origin_type=FragmentOriginType.CLI_ARGS),
    path=()
)

# Child inherits via from_parent
child_fragment = ConfigFragment(
    data={
        "level": "DEBUG",       # from parent
        "format": "[%(levelname)s] %(message)s",  # from parent
        "enabled": True         # own value
    },
    origin=FragmentOrigin(
        origin_type=FragmentOriginType.FROM_PARENT,
        inherited_from="level,format"
    ),
    parent=parent_fragment,
    path=("logging", "cli")
)

# Can trace: cli.level came from parent's level field
```

### Use Case 4: Merged Fragment with Full History

After merging multiple sources, preserve complete history:

```python
merged = ConfigFragment(
    data={"level": "DEBUG", "format": "%(message)s", "enabled": True},
    origin=FragmentOrigin(
        origin_type=FragmentOriginType.MERGED,
        source_fragments=[cli_fragment, env_fragment, file_fragment, defaults]
    )
)

# Query: where did 'level' come from?
merged.get_field_origin("level")
# -> cli_fragment (highest priority)

# Get full chain for debugging
merged.get_field_chain("level")
# -> [cli_fragment, env_fragment, file_fragment, defaults]
```

### Use Case 5: Validation and Required Values

Mark which values must be explicitly provided:

```python
required_fragment = ConfigFragment(
    data={"database_url": MISSING},
    origin=FragmentOrigin(origin_type=FragmentOriginType.REQUIRE),
    merge_mode=MergeMode.REQUIRE
)

# Later validation checks if all REQUIRE fragments are satisfied
validate_fragments([defaults, file_config, env_config, required_fragment])
# -> Error: "database_url is required but not provided"
```

---

## Proposed API

### Fragment Creation

```python
# From adapters
class ConfigToArgparseAdapter:
    def extract_fragment(self, args: Namespace) -> ConfigFragment:
        """Extract a fragment with full origin metadata."""
        data = self.extract_config(args)
        return ConfigFragment(
            data=data,
            origin=FragmentOrigin(
                origin_type=FragmentOriginType.CLI_ARGS,
                location=" ".join(sys.argv[1:])
            )
        )

class EnvironmentAdapter:
    def extract_fragment(self, environ: dict[str, str] | None = None) -> ConfigFragment:
        """Extract environment variables as a fragment."""
        data = self.extract_config(environ)
        return ConfigFragment(
            data=data,
            origin=FragmentOrigin(
                origin_type=FragmentOriginType.ENV_VARS,
                location=f"{self.env_prefix}_*" if self.env_prefix else "*"
            )
        )
```

### Fragment Merging

```python
def merge_fragments(
    fragments: list[ConfigFragment],
    *,
    strategy: MergeStrategy = MergeStrategy.LAST_WINS
) -> MergedFragment:
    """
    Merge multiple fragments into one.

    Returns a MergedFragment that preserves the origin of each field.
    """
    ...

class MergedFragment(ConfigFragment):
    """A fragment created by merging others."""

    field_origins: dict[str, ConfigFragment]  # which fragment each field came from
    field_chains: dict[str, list[ConfigFragment]]  # full override chain per field

    def get_field_origin(self, field_path: str) -> ConfigFragment:
        """Get the fragment that provided a specific field."""
        ...

    def get_field_chain(self, field_path: str) -> list[ConfigFragment]:
        """Get all fragments that defined this field (override chain)."""
        ...

    def diff(self, other: ConfigFragment) -> ConfigDiff:
        """Show differences between fragments."""
        ...
```

### Fragment Visualization

```python
class FragmentDebugger:
    """Debug and visualize configuration fragments."""

    def explain_field(self, fragment: ConfigFragment, field_path: str) -> str:
        """Explain where a field's value came from."""
        ...

    def show_override_chain(self, fragments: list[ConfigFragment]) -> str:
        """Visualize how fragments override each other."""
        ...

    def show_inheritance_tree(self, fragment: ConfigFragment) -> str:
        """Show parent-child relationships and from_parent propagation."""
        ...

    def generate_report(self, fragment: ConfigFragment) -> str:
        """Generate comprehensive debug report."""
        ...
```

---

## Integration with Current Code

### Phase 1: Add Fragment Support to Adapters

- Add `extract_fragment()` methods to all adapters
- Keep existing `extract_config()` for backward compatibility
- Fragment methods call `extract_config()` and wrap in Fragment

### Phase 2: Fragment-Aware Config Initialization

```python
class Config:
    @classmethod
    def from_fragments(
        cls,
        *fragments: ConfigFragment,
        debug: bool = False
    ) -> tuple[Self, MergedFragment]:
        """
        Create config from fragments, returning both the config
        and the merged fragment for debugging.
        """
        merged = merge_fragments(list(fragments))
        config = cls(**merged.data)

        if debug:
            # Attach fragment debug info
            object.__setattr__(config, "_fragment_debug", merged)

        return config, merged
```

### Phase 3: Enhanced from_parent Tracking

When propagating parent values, create a fragment to track it:

```python
def _merge_parent_values(self, sub_kwargs, sub_config_class):
    result = sub_kwargs.copy()
    inherited = {}

    for field_name, field_obj in sub_config_class.__config_fields__.items():
        if field_obj.from_parent and field_name not in result:
            if hasattr(self, field_name):
                inherited[field_name] = getattr(self, field_name)
                result[field_name] = inherited[field_name]

    # Track what was inherited
    if hasattr(self, "_fragment_debug"):
        parent_fragment = self._fragment_debug
        child_fragment = ConfigFragment(
            data=inherited,
            origin=FragmentOrigin(
                origin_type=FragmentOriginType.FROM_PARENT,
                inherited_from=",".join(inherited.keys())
            ),
            parent=parent_fragment
        )
        # Attach to sub-config

    return result
```

---

## Example Debug Output

```
Configuration Debug Report
==========================================================

Final Configuration:
  level: "DEBUG"
  format: "[%(levelname)s] %(message)s"
  logging.cli.level: "DEBUG" (inherited)
  logging.cli.format: "[%(levelname)s] %(message)s" (inherited)
  logging.cli.enabled: True
  logging.file.path: "/var/log/app.log"

Fragment Load Order:
  1. defaults (from Config class definitions)
  2. config_file:/etc/app/config.toml
  3. env_vars:APP_*
  4. cli_args:--level DEBUG --log-file-path /var/log/app.log

Field Origins:
  level:
    current: "DEBUG"
    from: cli_args (--level)
    chain: cli_args → env_vars → defaults
           "DEBUG"  → "INFO"    → "WARNING"

  logging.cli.level:
    current: "DEBUG"
    from: from_parent (inherited from parent 'level' field)
    parent_origin: cli_args (--level)
    chain: from_parent → [parent: cli_args → env_vars → defaults]

  logging.file.path:
    current: "/var/log/app.log"
    from: cli_args (--log-file-path)
    chain: cli_args → defaults
           "/var/log/app.log" → None

Inheritance Tree:
  LoggingConfig (from cli_args, env_vars, config_file, defaults)
    ├─ level: "DEBUG" (from cli_args)
    ├─ format: "[%(levelname)s] %(message)s" (from env_vars)
    │
    ├─ cli: LogCliConfig (sub-config)
    │   ├─ level: "DEBUG" ← from parent.level
    │   ├─ format: "[%(levelname)s] %(message)s" ← from parent.format
    │   └─ enabled: True (from cli_args)
    │
    └─ file: LogFileConfig (sub-config)
        ├─ level: "DEBUG" ← from parent.level
        ├─ format: "[%(levelname)s] %(message)s" ← from parent.format
        └─ path: "/var/log/app.log" (from cli_args)
```

---

## Benefits

1. **Better Debugging** - Immediately see where every value came from
2. **Configuration Auditing** - Know what sources were consulted
3. **Validation** - Detect conflicts, missing required values
4. **Documentation** - Auto-generate "effective configuration" docs
5. **Testing** - Easier to test configuration merging logic
6. **Diff Tools** - Compare configs across environments
7. **Change Detection** - Know what changed between runs

---

## Implementation Phases

### Phase 1: Core Fragment Types ✨
- [ ] Define `ConfigFragment`, `FragmentOrigin`, `MergeMode` dataclasses
- [ ] Implement basic fragment creation
- [ ] Add tests for fragment construction

### Phase 2: Adapter Integration ✨
- [ ] Add `extract_fragment()` to ArgparseAdapter
- [ ] Add `extract_fragment()` to EnvironmentAdapter
- [ ] Add `extract_fragment()` to PytestAdapter
- [ ] Add file loader fragment support

### Phase 3: Fragment Merging ✨
- [ ] Implement `merge_fragments()` function
- [ ] Create `MergedFragment` class with field tracking
- [ ] Handle different merge modes
- [ ] Track override chains per field

### Phase 4: Config Integration ✨
- [ ] Add `Config.from_fragments()` class method
- [ ] Enhance `from_parent` to create fragments
- [ ] Attach fragment debug info to config instances
- [ ] Maintain backward compatibility with existing APIs

### Phase 5: Debug Visualization ✨
- [ ] Create `FragmentDebugger` class
- [ ] Implement `explain_field()` method
- [ ] Implement `show_override_chain()` visualization
- [ ] Implement `show_inheritance_tree()` visualization
- [ ] Generate comprehensive reports

### Phase 6: Advanced Features ✨
- [ ] Fragment diffing
- [ ] Change detection via source hashing
- [ ] Required value validation
- [ ] Fragment serialization (save/load)
- [ ] Interactive fragment explorer CLI

---

## Open Questions

1. **Performance**: Should fragments be created eagerly or lazily?
   - Trade-off: memory vs. debugging capability

2. **Serialization**: Should fragments be JSON-serializable?
   - Use case: save debug info with config snapshots

3. **Field Paths**: How to represent nested field paths consistently?
   - Options: "logging.cli.level" vs. ("logging", "cli", "level")

4. **Fragment Equality**: When are two fragments "the same"?
   - Important for change detection and caching

5. **Thread Safety**: Should fragments be immutable?
   - Safer for concurrent access, but less flexible

6. **API Design**: Should fragments be opt-in or default?
   - Could impact performance if always enabled

---

## Related Features

This fragment system could enable:

- **Configuration schema validation** - Check fragments against schema
- **Hot reload** - Detect when source files change
- **A/B testing** - Apply different fragment sets
- **Configuration diff tool** - `config diff prod.toml staging.toml`
- **Provenance tracking** - Audit trail for compliance
- **Auto-documentation** - Generate config docs from fragments

---

## Success Criteria

The fragment system is successful when:

1. ✅ Every config value can be traced to its origin
2. ✅ Override chains are clear and visualizable
3. ✅ from_parent inheritance is tracked and debuggable
4. ✅ Merging behavior is predictable and documented
5. ✅ Performance impact is negligible when debugging is off
6. ✅ API is intuitive and well-documented
7. ✅ Integration with existing code is clean

---

## Next Steps

1. Review this plan with project maintainers
2. Decide on implementation priority
3. Create proof-of-concept for core fragment types
4. Validate API design with example use cases
5. Begin Phase 1 implementation
