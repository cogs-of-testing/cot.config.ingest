# Config Manager Design

## Overview

The Config Manager is responsible for orchestrating the loading of configuration from multiple sources while maintaining proper precedence, supporting plugin discovery, and handling complex override semantics.

## Core Responsibilities

### 1. Source Management

The Config Manager coordinates multiple configuration sources in precedence order:

```
1. Default values (lowest precedence)
2. Config files (TOML/YAML/JSON)
3. INI files (pytest-style)
4. Environment variables
5. Command-line arguments (highest precedence)
```

### 2. Configuration Loading Process

*To be designed*

### 3. Type Model to Format Mapping

#### To Structured Formats (TOML/YAML/JSON)

```python
ConfigPart -> nested dict structure
  field: str = "value"           -> {"field": "value"}
  sub: SubConfig                 -> {"sub": {...}}
  items: list[str]               -> {"items": ["a", "b"]}
```

**Mapping Rules:**
- Flat fields map directly to keys
- SubConfig instances become nested dicts
- Lists serialize as arrays
- Type annotations guide parsing direction

#### To CLI Sequences

```python
ConfigPart fields -> CLI arguments
  field: str                     -> --field VALUE
  flag: bool                     -> --flag / --no-flag
  items: list[str]               -> --items A --items B
  
With prefix="app":
  field: str                     -> --app-field VALUE
```

**Mapping Rules:**
- Field names converted to kebab-case with optional prefix
- Boolean fields get flag variants
- Lists support multiple invocations OR comma-separated
- SubConfig fields flattened with underscore: `database_host` -> `--database-host`

### 4. Override Semantics

#### Simple Override
```
file:    field = "a"
cli:     --field b
result:  field = "b"
```

#### Nested Override (Deep Merge)
```
file:    database = {host: "localhost", port: 5432}
cli:     --database-port 3306
result:  database = {host: "localhost", port: 3306}
```

#### List Handling

**Three modes:**

1. **Append Mode** (default for lists)
```
file:    items = ["a", "b"]
cli:     --items c
result:  items = ["a", "b", "c"]
```

2. **Replace Mode** (explicit reset)
```
file:    items = ["a", "b"]
cli:     --items-reset --items c
result:  items = ["c"]
```

3. **Extend Mode** (pytest addopts-style)
```
file:    addopts = "-v"
cli:     --addopts "-x"
result:  addopts = "-v -x"  # string concatenation
```

**List Override Strategies:**
- `append`: Add to existing list (default)
- `replace`: Replace entire list
- `extend`: String concatenation for space-separated options
- `reset`: CLI provides `--field-reset` to clear before appending

### 5. Special Features

#### addopts Support (pytest-style)

```python
class PytestConfig(ConfigPart):
    addopts: str = ""  # Special: space-separated options
    
# Behavior:
# pytest.ini:  addopts = -v --tb=short
# pyproject.toml: addopts = "-x"
# Result:      "-v --tb=short -x"
# 
# Note: addopts is only used in config files, not CLI
# CLI can directly specify options instead
```

#### INI File Integration

Support pytest-style ini files where:
- Section headers define groups
- Keys can be boolean flags or values
- Some keys have special parsing (e.g., `addopts`)

```ini
[pytest]
addopts = -v
testpaths = tests
python_files = test_*.py
```

Maps to:
```python
class PytestConfig(ConfigPart):
    addopts: str = ""
    testpaths: list[str] = []
    python_files: list[str] = []
```

## Architecture Components

### ConfigManager

```python
class ConfigManager:
    """Two-phase configuration manager."""
    
    def __init__(self):
        self.config_parts: dict[str, type[ConfigPart]] = {}
        self.bootstrap_config: dict[str, Any] = {}
        self.sources: list[ConfigSource] = []
    
    def register_part(self, part_class: type[ConfigPart]) -> None:
        """Register a ConfigPart class."""
        name = part_class.__name__
        self.config_parts[name] = part_class
    
    def bootstrap(
        self, 
        args: list[str],
        bootstrap_parts: list[type[ConfigPart]],
    ) -> dict[str, Any]:
        """Phase 1: Bootstrap configuration."""
        # (Implementation shown above)
        pass
    
    def load_full(self) -> None:
        """Phase 2: Full configuration load."""
        # (Implementation shown above)
        pass
    
    def build(self) -> dict[str, ConfigPart]:
        """
        Build final config instances.
        
        Returns dict mapping ConfigPart names to instances.
        """
        if not self.sources:
            raise RuntimeError("Must call load_full() before build()")
        
        # Merge all sources
        merged = {}
        for source in self.sources:
            data = source.load(self.config_parts)
            self._merge_data(merged, data)
        
        # Build instances
        instances = {}
        for name, part_class in self.config_parts.items():
            part_data = merged.get(name, {})
            instances[name] = part_class(**part_data)
        
        return instances
    
    def _merge_data(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        """Deep merge source into target."""
        # (same as before)
        pass
```

### TypeMapper

```python
class TypeMapper:
    """Maps between type model and various formats."""
    
    def to_dict(self, config: ConfigPart) -> dict[str, Any]:
        """Convert config to dict (for serialization)."""
        
    def from_dict(self, data: dict[str, Any], config_class: type[ConfigPart]) -> ConfigPart:
        """Convert dict to config instance."""
        
    def to_cli_args(self, config: ConfigPart, prefix: str | None = None) -> list[str]:
        """Generate CLI args from config."""
        
    def cli_arg_name(self, field_path: str, prefix: str | None = None) -> str:
        """Convert field path to CLI arg name."""
        
    def env_var_name(self, field_path: str, prefix: str | None = None) -> str:
        """Convert field path to env var name."""
```

### OverrideHandler

```python
class OverrideHandler:
    """Handles complex override semantics."""
    
    def merge(self, base: dict[str, Any], override: dict[str, Any], 
              config_class: type[ConfigPart]) -> dict[str, Any]:
        """Deep merge with field-specific rules."""
        
    def merge_list(self, base: list[Any], override: list[Any], 
                   mode: ListMergeMode) -> list[Any]:
        """Merge lists according to mode."""
        
    def handle_reset(self, field_name: str, value: Any) -> tuple[bool, Any]:
        """Check for reset markers and return (was_reset, value)."""
```

### PluginDiscovery

```python
class PluginDiscovery:
    """Discovers and loads plugin-contributed config parts."""
    
    def discover_entry_points(self, group: str = "cot.config.plugins") -> list[type[ConfigPart]]:
        """Discover config parts via entry points."""
        
    def discover_from_module(self, module_name: str) -> list[type[ConfigPart]]:
        """Discover config parts from a module."""
```

## Usage Examples

*To be designed*

### Dynamic Part Registration

```python
# Can add parts at any time
manager = ConfigManager()
manager.add_source(FileSource(Path("config.toml")))

# Initially just one part
manager.register_part(AppConfig)

# Load discovers plugins field
manager.discover()

# Plugin system adds more parts dynamically
plugin = load_plugin("pytest")
manager.register_part(plugin.PytestConfig)

# All sources are re-evaluated with new parts
config = manager.build()
```

### List Override Examples

```python
# File: config.toml
# plugins = ["pytest_cov", "pytest_xdist"]

# CLI 1: Append
# --plugins pytest_timeout
# Result: ["pytest_cov", "pytest_xdist", "pytest_timeout"]

# CLI 2: Replace
# --plugins-reset --plugins pytest_timeout
# Result: ["pytest_timeout"]

# CLI 3: Multiple values
# --plugins pytest_timeout --plugins pytest_html
# Result: ["pytest_cov", "pytest_xdist", "pytest_timeout", "pytest_html"]
```

### addopts Style

```python
class PytestConfig(ConfigPart):
    addopts: str @ help("Additional pytest options")

# pytest.ini:       addopts = -v --tb=short
# pyproject.toml:   addopts = "-x --pdb"
# Result:           addopts = "-v --tb=short -x --pdb"
#
# Note: addopts only exists in config files for convenience
# It allows accumulating options across multiple config files
# CLI doesn't need --addopts since it can directly use the options
# Implementation treats this as string concat with space separator
```

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] ConfigManager basic structure with bootstrap
- [ ] ConfigPart discovery hooks (discover_config_locations, discover_plugins)
- [ ] TypeMapper for dict conversion
- [ ] Simple file loading (TOML/JSON)
- [ ] Basic CLI mapping

### Phase 2: Discovery Process
- [ ] Multi-phase bootstrap implementation
- [ ] Config file discovery (pytest-style directory walking)
- [ ] Plugin loading mechanism
- [ ] Plugin entry point discovery

### Phase 3: Override Semantics
- [ ] Deep merge for nested configs
- [ ] List handling (append/replace modes)
- [ ] Reset marker support
- [ ] Environment variable loading

### Phase 4: Advanced Features
- [ ] INI file support
- [ ] addopts-style string concat
- [ ] Full argparse integration
- [ ] Environment variable loading

### Phase 5: Polish
- [ ] Error messages and validation
- [ ] Provenance tracking (which source set each value)
- [ ] Debug mode for config inspection
- [ ] Documentation and examples

## Open Questions

1. **List merge default**: Should lists append by default, or require explicit `action="append"` marker?

2. **Reset syntax**: Should reset be `--field-reset` flag, or `--field=[]` value?

3. **Type validation**: When should type checking happen? At load time or build time?

4. **Nested prefix handling**: How should prefixes work for nested SubConfigs?
   ```python
   class AppConfig(ConfigPart, prefix="app"):
       db: DatabaseConfig  # Do db fields get "app_db_" prefix?
   ```

5. **Plugin ordering**: If two plugins provide conflicting defaults, who wins?

6. **INI special syntax**: Should we support pytest's `key =` (empty value) meaning "remove from list"?
