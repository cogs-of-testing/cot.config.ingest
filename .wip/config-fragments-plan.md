# Configuration Fragments: Origin Tracking and Debugging

## Motivation

When building configurations from multiple sources (CLI args, env vars, config files), we need to:

1. **Track origins** - Know exactly where each value came from
2. **Debug merging** - Understand how values were combined/overridden
3. **Express partial configs** - Represent incomplete configuration from a single source
4. **Trace inheritance** - Show how `from_parent` values propagate
5. **Explain resolution** - Show the sequence of overrides that led to final value

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

1. **No fragment representation** - Can't represent partial/incomplete configs
2. **Limited inheritance tracking** - Doesn't show `from_parent` propagation
3. **No merge visualization** - Hard to see how fragments combine
4. **Single-field focus** - Tracks fields independently, not as coherent fragments
5. **No structured API** - Debug info is mainly for reporting, not programmatic use
6. **No diff support** - Can't compare fragments or show what changed

---

## Proposed Design: Configuration Fragments

### Core Concept

A **ConfigFragment** represents a partial configuration obtained from a single source, with full metadata about its origin and how it should merge with other fragments.

```python
@dataclass
class ConfigFragment:
    """A partial configuration from a single source."""

    # What values this fragment contains
    data: dict[str, Any]

    # Where this fragment came from
    origin: FragmentOrigin

    # How this fragment should merge with others
    merge_mode: MergeMode = MergeMode.OVERRIDE

    # Parent fragment that spawned this (for sub-configs)
    parent: ConfigFragment | None = None

    # Path in the config hierarchy (e.g., "logging.cli")
    path: tuple[str, ...] = ()

    # Metadata
    timestamp: datetime = field(default_factory=datetime.now)
    source_hash: str | None = None  # for change detection
```

### Fragment Origins

```python
class FragmentOriginType(Enum):
    """Type of origin for a configuration fragment."""

    # Direct sources
    CLI_ARGS = "cli_args"
    ENV_VARS = "env_vars"
    CONFIG_FILE = "config_file"
    CODE = "code"

    # Computed sources
    DEFAULT_VALUES = "defaults"
    FROM_PARENT = "from_parent"
    MERGED = "merged"

    # Special
    OVERRIDE = "override"
    FALLBACK = "fallback"

@dataclass
class FragmentOrigin:
    """Detailed origin information for a fragment."""

    origin_type: FragmentOriginType

    # Specific location details
    location: str | None = None  # file path, env prefix, etc.
    line_range: tuple[int, int] | None = None  # for files
    timestamp: datetime | None = None

    # For merged fragments
    source_fragments: list[ConfigFragment] = field(default_factory=list)

    # For inherited values
    inherited_from: str | None = None  # field path

    def __str__(self) -> str:
        if self.location:
            if self.line_range:
                return f"{self.origin_type.value}:{self.location}:{self.line_range[0]}-{self.line_range[1]}"
            return f"{self.origin_type.value}:{self.location}"
        return self.origin_type.value
```

### Merge Modes

```python
class MergeMode(Enum):
    """How a fragment should be merged with others."""

    OVERRIDE = "override"      # Replace existing values
    MERGE_DEEP = "merge_deep"  # Deep merge dicts, concat lists
    APPEND = "append"          # Only for list values
    REQUIRE = "require"        # Must be set (validation)
    FALLBACK = "fallback"      # Only use if not already set
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
