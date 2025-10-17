# Configuration Fragments: Design Specification

## Overview

This document describes the **design** of the configuration fragments system for origin tracking and debugging.

## Three-Phase Architecture

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
  - **Mappers query the field configuration API for name mappings**
  - `EnvFieldMapper`: asks field for env name → `("database", "host")` → `"APP_DATABASE_HOST"`
  - `ArgparseFieldMapper`: asks field for CLI name → `("database", "host")` → `"database-host"`
  - `NestedFieldMapper`: uses field name directly from structure
- Result: `ConfigFragment` with nested `field_values` showing which Config fields this loader provides

### Phase 3: Merging
**Merge fragments in priority order (first wins) to produce final config:**
- Priority order: CLI → ENV → FILE → DEFAULTS
- Deep merge: first fragment with a value wins
- `MergedFragment` tracks which loader provided each final value
- Complete audit trail: field path → loader → original value

### Key Insight
The Config class structure and field configuration drive the transformation. Mappers don't invent conventions; they query the field API for the proper name in each namespace.

---

## Core Data Structures

### LoadedData

Raw configuration data from a single loader instance.

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
```

### LoaderInfo

Metadata about a loader instance.

```python
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
```

### ConfigFragment

A structured view of which config fields came from a specific loader.

```python
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

---

## Field Path Mapping

### FieldPath

Represents a path to a config field and how to locate it in loader data.

```python
@dataclass
class FieldPath:
    """
    Represents a path to a config field and how to locate it in loader data.

    The Config class structure determines the field path.
    Each loader's mapper knows how to find this field in its data
    by querying the field configuration API.
    """

    # Canonical field path in Config structure
    # e.g., ("database", "host") for config.database.host
    path: tuple[str, ...]

    # How this field maps in the loader's namespace
    # Obtained by asking the field descriptor
    # e.g., "APP_DATABASE_HOST" for env, "--database-host" for CLI
    loader_key: str

    # The field descriptor this came from
    field_descriptor: FieldDescriptor

    def __str__(self) -> str:
        return ".".join(self.path)
```

### FieldExtractor

Extracts config field values from loader data.

```python
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
        2. For each field path, ask mapper to get loader key from field API
        3. Extract value if present in loaded_data
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
        The mapper queries each field's configuration to determine
        how to find it in the loader's data.
        """
        result = {}
        fields = getattr(config_class, "__config_fields__", {})

        for field_name, field_descriptor in fields.items():
            field_path = path_prefix + (field_name,)

            # Ask mapper to get lookup key from field configuration
            # The mapper will query the field_descriptor for its name
            # in the mapper's namespace (env var name, CLI name, etc.)
            lookup_key = self.mapper.get_lookup_key(field_path, field_descriptor)

            # Try to find value in data
            value = self._lookup_value(data, lookup_key)

            if value is MISSING:
                continue  # This loader doesn't have this field

            # Handle nested Config fields
            if isinstance(value, dict) and self._is_config_class(field_descriptor):
                nested_result = self._extract_fields(
                    field_descriptor.config_class,
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
    def _is_config_class(field_descriptor: Any) -> bool:
        """Check if field descriptor is for a nested Config."""
        return isinstance(field_descriptor, SubConfigDescriptor)
```

### FieldPathMapper Protocol

Protocol for mapping Config field paths to loader keys by querying field configuration.

```python
class FieldPathMapper(Protocol):
    """
    Protocol for mapping Config field paths to loader keys.

    Each loader type provides an implementation that knows how to
    query the field configuration API to get the appropriate name.
    """

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_descriptor: FieldDescriptor | SubConfigDescriptor
    ) -> str:
        """
        Get the key to look up in loader data for this field.

        Queries the field configuration to determine the proper name
        in this loader's namespace.

        Examples:
            EnvFieldMapper: queries field API → "APP_DATABASE_HOST"
            ArgparseFieldMapper: queries field API → "--database-host"
            NestedFieldMapper: uses field name → "host"
        """
        ...
```

### Built-in Mappers

```python
class EnvFieldMapper:
    """
    Maps Config fields to environment variable names.

    Queries the field configuration or uses naming conventions
    to determine ENV var names.
    """

    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_descriptor: FieldDescriptor | SubConfigDescriptor
    ) -> str:
        """
        Build ENV var name by querying field configuration.

        Uses field_to_env_name() from the name mapping API,
        applying the prefix configuration.
        """
        from ._name_mapping import field_to_env_name

        # For nested fields, construct the full path
        field_name = "_".join(field_path)

        # Query field configuration for ENV name
        # (or use naming convention if field doesn't specify)
        env_name = field_to_env_name(field_name, prefix=self.prefix)

        return env_name


class ArgparseFieldMapper:
    """
    Maps Config fields to CLI argument names.

    Queries the field configuration or uses naming conventions
    to determine CLI arg names.
    """

    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_descriptor: FieldDescriptor | SubConfigDescriptor
    ) -> str:
        """
        Build CLI arg name by querying field configuration.

        Uses field_to_cli_name() from the name mapping API,
        applying the prefix configuration.
        """
        from ._name_mapping import field_to_cli_name

        # For nested fields, construct the full path
        field_name = "_".join(field_path)

        # Query field configuration for CLI name
        # (or use naming convention if field doesn't specify)
        cli_name = field_to_cli_name(field_name, prefix=self.prefix)

        # Return without the -- prefix for lookup
        return cli_name.lstrip("-")


class NestedFieldMapper:
    """
    Maps Config fields for already-nested data (TOML, JSON, YAML).

    For nested data, just uses the immediate field name since
    the FieldExtractor handles traversing the nested structure.
    """

    def get_lookup_key(
        self,
        field_path: tuple[str, ...],
        field_descriptor: FieldDescriptor | SubConfigDescriptor
    ) -> str:
        """
        For nested data, return the immediate field name.

        The FieldExtractor handles traversing nested dicts,
        so we only need the current level's field name.
        """
        return field_path[-1] if field_path else ""
```

---

## Fragment Merging

### merge_fragments Function

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
```

### MergedFragment Class

```python
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

## Design Principles

1. **Separation of Concerns**
   - Loaders only know how to load data from their source
   - Config classes define structure and field configuration
   - Mappers bridge between loader namespace and Config structure by querying field API

2. **Config-Driven Transformation**
   - Config class structure determines field paths
   - Field configuration provides name mappings for each namespace
   - Mappers query the field API, don't invent conventions

3. **Extensibility**
   - New loader types just need a FieldPathMapper implementation
   - LoaderInfo uses actual loader type, not enum
   - Custom mappers can query field API for any namespace format

4. **Immutability**
   - LoadedData is immutable after creation
   - ConfigFragment is immutable
   - Transformations create new objects

5. **Debuggability**
   - Every value traced to its loader
   - Complete override chains preserved
   - Human-readable loader descriptions

---

## Benefits

1. **Load once, transform many times**: Same LoadedData can be transformed against different Config schemas
2. **Clear separation**: Loaders don't need to know about Config structure; mappers query field API
3. **Powerful debugging**: Each fragment shows exactly which Config fields came from which loader
4. **Extensible**: New loader types just need a FieldPathMapper implementation
5. **Traceable**: Complete audit trail from loader → field path → final value
6. **Configuration-driven**: Field mappings come from field configuration, not hardcoded conventions
7. **Better debugging** - Immediately see where every value came from
8. **Configuration auditing** - Know what sources were consulted
9. **Validation** - Detect conflicts, missing required values
10. **Documentation** - Auto-generate "effective configuration" docs
11. **Testing** - Easier to test configuration merging logic
12. **Diff tools** - Compare configs across environments
13. **Change detection** - Know what changed between runs

---

## Open Questions

1. **Field API Extension**: Should fields expose explicit mapping methods for each namespace?
   - e.g., `field.get_env_name()`, `field.get_cli_name()`
   - Or continue using the naming convention functions?

2. **Performance**: Should fragments be created eagerly or lazily?
   - Trade-off: memory vs. debugging capability

3. **Serialization**: Should fragments be JSON-serializable?
   - Use case: save debug info with config snapshots

4. **Field Paths**: How to represent nested field paths consistently?
   - Currently using tuples: `("logging", "cli", "level")`
   - String form for output: `"logging.cli.level"`

5. **Fragment Equality**: When are two fragments "the same"?
   - Important for change detection and caching

6. **Thread Safety**: Should fragments be immutable?
   - Currently planned as immutable (safer for concurrent access)

7. **API Design**: Should fragments be opt-in or default?
   - Could impact performance if always enabled
