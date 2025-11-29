# Bootstrap Process

## Overview

The bootstrap process determines HOW to load configuration by progressively building up configuration context through feedback loops.

## Core Concept

Configuration loading happens in stages where ConfigParts can be:

1. **Passed at construction** - Bootstrap fragments provided when creating ConfigManager
2. **Registered later** - ConfigPart types registered after construction

Each ConfigPart can have an optional `discover()` method that:
- Takes the ConfigManager instance
- Returns input data for constructing the ConfigPart
- Enables dynamic discovery based on existing config

## ConfigPart Discovery Method

### Basic Pattern

```python
class ConfigFileConfig(ConfigPart, bootstrap=True):
    config: Path | None = None
    config_files: list[Path] = []
    
    def discover(self, manager: ConfigManager) -> Self:
        """
        Discover config files and return updated instance.
        
        Args:
            manager: ConfigManager with access to existing fragments
        
        Returns:
            Updated copy of self with discovered values
        """
        # Access previously registered fragments
        invocation = manager.get_fragment(InvocationConfig)
        
        # Manager handles CLI parsing, we just get clean values
        # Load from manager's sources (CLI + files)
        loaded = manager.load_for_part(type(self))
        
        # Discover files if not explicit
        config = loaded.get("config") or self.config
        if config:
            config_files = [config]
        else:
            config_files = discover_config_files(invocation.invocation_dir)
        
        # Return updated copy
        return replace(self, config=config, config_files=config_files)
```

### Discovery Flow

```
1. ConfigPart registered with manager
2. Manager creates default instance: ConfigPart()
3. Manager calls instance.discover(manager) if method exists
4. discover() returns updated copy of instance
5. Manager stores the updated instance
```

## Initial Config Fragments

### Bootstrap vs Regular Fragments

The distinction between bootstrap and regular ConfigParts is **when they're provided**:

**Bootstrap Fragments** - Passed at manager construction:
```python
class InvocationConfig(ConfigPart):
    invocation_dir: Path
    invocation_args: list[str]
    plugins: list[str] = []

# Create instance and pass to manager
invocation = InvocationConfig(
    invocation_dir=Path.cwd(),
    invocation_args=sys.argv[1:],
    plugins=[],
)

# Bootstrap fragments passed at construction
manager = ConfigManager(bootstrap_fragments=[invocation])
```

**Regular Fragments** - Registered after construction:
```python
class ConfigFileConfig(ConfigPart):
    config: Path | None = None
    config_files: list[Path] = []
    
    @classmethod
    def discover(cls, manager: ConfigManager) -> dict[str, Any]:
        # Discover and return construction data
        invocation = manager.get_fragment(InvocationConfig)
        return {"config_files": discover_files(invocation.invocation_dir)}

# Register type, manager calls discover() and constructs instance
manager.register_fragment_type(ConfigFileConfig)
```

The `bootstrap=True` marker is **optional metadata** - the real distinction is construction vs registration.

## Bootstrap Flow

### Stage 1: Manager Construction with Bootstrap Fragments

```python
class InvocationConfig(ConfigPart):
    invocation_dir: Path
    invocation_args: list[str]
    plugins: list[str] = []

# Create bootstrap fragments
invocation = InvocationConfig(
    invocation_dir=Path.cwd(),
    invocation_args=sys.argv[1:],
    plugins=[],
)

# Pass at construction
manager = ConfigManager(bootstrap_fragments=[invocation])
```

**No discovery method** - data already provided.

### Stage 2: Config File Discovery via Registration

```python
class ConfigFileConfig(ConfigPart, discover_files=True):
    config: Path | None = None
    config_files: list[Path] = []
    
    def discover(self, manager: ConfigManager) -> Self:
        """Discover config files from invocation data."""
        invocation = manager.get_fragment(InvocationConfig)
        
        # Manager handles parsing, just load values
        loaded = manager.load_for_part(type(self))
        config = loaded.get("config") or self.config
        
        # Discover files if not explicit
        if config:
            config_files = [config]
        else:
            config_files = discover_config_files(invocation.invocation_dir)
        
        return replace(self, config=config, config_files=config_files)

# Register type - triggers discovery
manager.register_fragment_type(ConfigFileConfig)

# Manager:
# 1. Creates default instance: ConfigFileConfig()
# 2. Calls instance.discover(manager)
# 3. Gets updated instance
# 4. Stores updated instance
# 5. If discover_files=True, adds FileSource for each config_file
```

**Feedback Loop 1**: `discover_files=True` triggers FileSource addition, making files available for subsequent fragments.

### Stage 3: Additional Config via Registration

```python
class AddoptsConfig(ConfigPart):
    addopts: str = ""
    
    def discover(self, manager: ConfigManager) -> Self:
        """Load addopts from available sources."""
        # Manager loads from:
        # 1. invocation.invocation_args (CLI)
        # 2. Config files (now available from Stage 2!)
        # Manager handles merging automatically
        loaded = manager.load_for_part(type(self))
        return replace(self, **loaded)

class EnvironmentConfig(ConfigPart):
    env_prefix: str = "APP"
    
    def discover(self, manager: ConfigManager) -> Self:
        """Load environment settings from available sources."""
        loaded = manager.load_for_part(type(self))
        return replace(self, **loaded)

# Register types
manager.register_fragment_type(AddoptsConfig)
manager.register_fragment_type(EnvironmentConfig)

# Manager:
# 1. Creates default instances: AddoptsConfig(), EnvironmentConfig()
# 2. Calls instance.discover(manager) for each
# 3. Gets updated instances
# 4. Stores updated instances
```

**Key insight**: Later fragments use `manager.load_for_part()` to leverage all active sources.

## Feedback Mechanisms

### 1. Source Addition Feedback

When a ConfigPart has `discover_files=True`:
- The `discover()` method returns config file paths
- Manager automatically adds FileSource for each file
- Subsequent `register_fragment_type()` calls can load from these files

```python
class ConfigFileConfig(ConfigPart, discover_files=True):
    config_files: list[Path] = []
    
    @classmethod
    def discover(cls, manager: ConfigManager) -> dict[str, Any]:
        return {"config_files": [...]}

# Manager sees discover_files=True and adds:
for file in config_files:
    manager.sources.append(FileSource(file))
```

### 2. ConfigPart Registration Feedback

When plugins are discovered:
```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []
    
    @classmethod
    def discover(cls, manager: ConfigManager) -> dict[str, Any]:
        data = manager.load_from_sources(cls)
        
        # Side effect: register plugin ConfigParts
        for plugin_name in data.get("plugins", []):
            plugin = load_plugin(plugin_name)
            manager.register_part(plugin.ConfigPart)
        
        return data
```

### 3. Manager State Feedback

`discover()` methods can access manager state:
- Previous fragments: `manager.get_fragment(ConfigType)`
- Load from sources: `manager.load_for_part(type(self))`
- Registered parts: `manager.config_parts`

## Bootstrap API (Draft)

```python
from dataclasses import replace
from typing import Self

class ConfigManager:
    def __init__(self, bootstrap_fragments: list[ConfigPart] | None = None):
        """
        Create ConfigManager with initial bootstrap fragments.
        
        Args:
            bootstrap_fragments: Pre-built ConfigPart instances
        """
        self.fragments: dict[type[ConfigPart], ConfigPart] = {}
        self.sources: list[ConfigSource] = []
        self.config_parts: dict[str, type[ConfigPart]] = {}
        
        # Store bootstrap fragments
        if bootstrap_fragments:
            for fragment in bootstrap_fragments:
                self.fragments[type(fragment)] = fragment
    
    def register_fragment_type(
        self,
        fragment_type: type[ConfigPart],
    ) -> ConfigPart:
        """
        Register a ConfigPart type - manager will discover it.
        
        Process:
        1. Create default instance: fragment_type()
        2. Call instance.discover(self) if method exists
        3. If no discover(), call self.load_for_part() and update instance
        4. Store instance
        5. If discover_files=True, add FileSource for discovered files
        
        Args:
            fragment_type: ConfigPart class to register
        
        Returns:
            Discovered/loaded ConfigPart instance
        """
        # Create default instance
        instance = fragment_type()
        
        # Call discover if available
        if hasattr(instance, 'discover'):
            instance = instance.discover(self)
        else:
            # Default: load from active sources
            loaded = self.load_for_part(fragment_type)
            instance = replace(instance, **loaded)
        
        # Store
        self.fragments[fragment_type] = instance
        
        # Handle file discovery feedback
        if self._has_discover_files(fragment_type):
            config_files = getattr(instance, 'config_files', [])
            for file in config_files:
                self.sources.append(FileSource(file))
        
        return instance
    
    def get_fragment(self, fragment_type: type[ConfigPart]) -> ConfigPart:
        """Get a stored fragment by type."""
        return self.fragments[fragment_type]
    
    def load_for_part(self, fragment_type: type[ConfigPart]) -> dict[str, Any]:
        """
        Load ConfigPart data from all active sources.
        
        Merges data from all sources in precedence order.
        Manager handles CLI parsing, file parsing, env parsing.
        
        Args:
            fragment_type: ConfigPart class to load data for
        
        Returns:
            Dict of field values to update instance with
        """
        merged = {}
        for source in self.sources:
            data = source.load({fragment_type.__name__: fragment_type})
            self._merge_data(merged, data)
        return merged.get(fragment_type.__name__, {})


class ConfigPart:
    """Base class with optional discover method."""
    
    def discover(self, manager: ConfigManager) -> Self:
        """
        Optional method to discover and return updated instance.
        
        Args:
            manager: ConfigManager with access to existing fragments
        
        Returns:
            Updated copy of self with discovered values
        """
        # Default implementation: load from sources
        loaded = manager.load_for_part(type(self))
        return replace(self, **loaded)
```

## Example Bootstrap Sequence

```python
from cot.config import ConfigPart, ConfigManager
from pathlib import Path

# Step 1: Define bootstrap ConfigParts

class InvocationConfig(ConfigPart):
    """Bootstrap fragment - passed at construction."""
    invocation_dir: Path
    invocation_args: list[str]
    plugins: list[str] = []


class ConfigFileConfig(ConfigPart, discover_files=True):
    """Registered fragment - discovers config files."""
    config: Path | None = None
    config_files: list[Path] = []
    
    def discover(self, manager: ConfigManager) -> Self:
        invocation = manager.get_fragment(InvocationConfig)
        
        # Manager handles CLI parsing, we get clean values
        loaded = manager.load_for_part(type(self))
        config = loaded.get("config") or self.config
        
        # Discover or use explicit
        if config:
            config_files = [config]
        else:
            config_files = discover_config_files(invocation.invocation_dir)
        
        return replace(self, config=config, config_files=config_files)


class AddoptsConfig(ConfigPart):
    """Registered fragment - loaded from sources."""
    addopts: str = ""
    
    # No discover() - uses default (load_for_part + replace)


class EnvironmentConfig(ConfigPart):
    """Registered fragment - loaded from sources."""
    env_prefix: str = "APP"
    
    # No discover() - uses default (load_for_part + replace)


# Step 2: Create manager with bootstrap fragments

invocation = InvocationConfig(
    invocation_dir=Path.cwd(),
    invocation_args=["--debug", "--config", "app.toml"],
    plugins=[],
)

manager = ConfigManager(bootstrap_fragments=[invocation])

# Step 3: Register fragment types

# Register ConfigFileConfig - triggers discovery
config_files = manager.register_fragment_type(ConfigFileConfig)
# Manager:
# - Creates default: ConfigFileConfig()
# - Calls instance.discover(manager)
# - Gets back updated instance with config_files filled
# - Sees discover_files=True, adds FileSource("app.toml")

# Register AddoptsConfig - loads from sources
addopts = manager.register_fragment_type(AddoptsConfig)
# Manager:
# - Creates default: AddoptsConfig()
# - No discover(), uses default (load_for_part + replace)
# - Loads from CLI args + app.toml (now available!)
# - Returns updated instance

# Register EnvironmentConfig - loads from sources
env_config = manager.register_fragment_type(EnvironmentConfig)
# Manager:
# - Creates default: EnvironmentConfig()
# - No discover(), uses default (load_for_part + replace)
# - Loads from CLI args + app.toml
# - Returns updated instance

# Step 4: Access fragments

print(f"Config files: {config_files.config_files}")
print(f"Addopts: {addopts.addopts}")
print(f"Env prefix: {env_config.env_prefix}")

# Bootstrap complete!
# Manager has all sources configured for full config load
```

## Design Questions

1. **Error Handling**: What if `discover()` raises an exception?
2. **Ordering**: Can fragments be registered in any order, or must dependencies come first?
3. **Validation**: When should discovered data be validated (during discover or after)?
4. **Caching**: Should `get_fragment()` results be cached?
5. **Side Effects**: Should `discover()` be allowed to have side effects (like registering plugins)?
6. **Immutability**: Should we enforce that `discover()` doesn't mutate self?

## To Be Designed

- Detailed feedback result structure
- Error handling and recovery
- Fragment validation rules
- Async/streaming support for discovery
- Plugin loading protocol
