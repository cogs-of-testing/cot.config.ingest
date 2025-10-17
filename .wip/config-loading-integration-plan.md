# Configuration Loading and Integration Plan

## Overview

This document describes how the fragment system integrates with Config loading through a coordinated loader that manages multiple sources.

See also:
- [config-fragments-design.md](config-fragments-design.md) - Core fragment design
- [fragments-implementation-plan.md](fragments-implementation-plan.md) - Implementation steps

---

## Core Concept: ConfigLoader

Instead of manually orchestrating loaders, fragments, and merging, a `ConfigLoader` class coordinates the entire workflow:

```python
# Simple, clean API
loader = ConfigLoader(MyConfig)
loader.add_env(prefix="APP")
loader.add_cli(args)
loader.add_file("config.toml")

config = loader.load(debug=True)

# Debug
from cot.config.fragments import get_debug_info
debug = get_debug_info(config)
print(debug.get_origin("database.host"))
```

---

## Debug Info Access

### get_debug_info() Function

Instead of directly attaching debug info to config instances, provide a function to retrieve it:

```python
# Weak reference registry to store debug info
_debug_registry: weakref.WeakKeyDictionary[Config, MergedFragment] = weakref.WeakKeyDictionary()


def get_debug_info(config: Config) -> MergedFragment | None:
    """
    Get fragment debug information for a config instance.

    Args:
        config: Config instance to get debug info for

    Returns:
        MergedFragment with origin tracking, or None if not available

    Example:
        ```python
        config = MyConfig.load(debug=True)

        debug = get_debug_info(config)
        if debug:
            print(debug.get_origin("database.host"))
            print(debug.get_all_origins("debug"))
        ```
    """
    return _debug_registry.get(config)


def attach_debug_info(config: Config, debug_info: MergedFragment) -> None:
    """
    Attach fragment debug info to a config instance.

    This is called internally by ConfigLoader when debug=True.
    Uses weak references to avoid memory leaks.

    Args:
        config: Config instance
        debug_info: MergedFragment to attach
    """
    _debug_registry[config] = debug_info
```

---

## ConfigLoader Design

### Core API

```python
class ConfigLoader:
    """
    Coordinates loading configuration from multiple sources.

    Manages the complete workflow:
    1. Collect loaders/adapters
    2. Load data from each source
    3. Transform to fragments
    4. Merge fragments (first wins)
    5. Create Config instance
    6. Optionally attach debug info
    """

    def __init__(self, config_class: type[Config]):
        """
        Initialize loader for a config class.

        Args:
            config_class: The Config class to load
        """
        self.config_class = config_class
        self._sources: list[tuple[str, Any, FieldPathMapper]] = []

    def add_cli(
        self,
        args: argparse.Namespace | None = None,
        *,
        adapter: ConfigToArgparseAdapter | None = None
    ) -> Self:
        """
        Add CLI arguments as a configuration source.

        Args:
            args: Parsed argparse arguments
            adapter: Optional custom adapter (creates default if not provided)

        Returns:
            self for chaining
        """
        if adapter is None:
            from .adapters.argparse import ConfigToArgparseAdapter
            adapter = ConfigToArgparseAdapter(self.config_class)
            if args is not None:
                adapter.set_parsed_args(args)

        self._sources.append(("cli", adapter, ArgparseFieldMapper()))
        return self

    def add_env(
        self,
        *,
        prefix: str = "",
        environ: dict[str, str] | None = None,
        adapter: EnvironmentAdapter | None = None
    ) -> Self:
        """
        Add environment variables as a configuration source.

        Args:
            prefix: Environment variable prefix (e.g., "APP")
            environ: Optional custom environ dict (uses os.environ if not provided)
            adapter: Optional custom adapter

        Returns:
            self for chaining
        """
        if adapter is None:
            from .adapters.environment import EnvironmentAdapter
            adapter = EnvironmentAdapter(self.config_class, prefix=prefix)
            if environ is not None:
                adapter.set_environ(environ)

        self._sources.append(("env", adapter, EnvFieldMapper(prefix=prefix)))
        return self

    def add_file(
        self,
        path: Path | str,
        *,
        loader_func: Callable[[Path], dict[str, Any]] | None = None
    ) -> Self:
        """
        Add a configuration file as a source.

        Args:
            path: Path to config file (TOML, JSON, or YAML)
            loader_func: Optional custom file loader

        Returns:
            self for chaining
        """
        if loader_func is None:
            from .loaders import load_file
            loader_func = load_file

        # Create a simple wrapper that produces LoadedData
        class FileLoaderWrapper:
            def __init__(self, path: Path | str, loader: Callable):
                self.path = Path(path)
                self.loader = loader

            def load_data(self) -> LoadedData:
                data = self.loader(self.path)
                return LoadedData(
                    data=data,
                    loader=LoaderInfo(
                        loader_type=type(self.loader),
                        location=str(self.path)
                    )
                )

        wrapper = FileLoaderWrapper(path, loader_func)
        self._sources.append(("file", wrapper, NestedFieldMapper()))
        return self

    def add_defaults(self) -> Self:
        """
        Add Config class defaults as a source (lowest priority).

        Returns:
            self for chaining
        """
        # Defaults are added automatically in load(), but can be explicit
        self._sources.append(("defaults", DefaultsExtractor, NestedFieldMapper()))
        return self

    def add_source(
        self,
        name: str,
        loader: Any,
        mapper: FieldPathMapper
    ) -> Self:
        """
        Add a custom configuration source.

        Args:
            name: Descriptive name for this source
            loader: Object with load_data() method returning LoadedData
            mapper: FieldPathMapper for this source's namespace

        Returns:
            self for chaining
        """
        self._sources.append((name, loader, mapper))
        return self

    def load(self, *, debug: bool = False) -> Config:
        """
        Load configuration from all sources.

        Process:
        1. Ensure defaults are last
        2. Load data from each source
        3. Transform each to ConfigFragment
        4. Merge fragments (first wins)
        5. Create Config instance
        6. Optionally attach debug info

        Args:
            debug: If True, attach fragment debug info (accessible via get_debug_info())

        Returns:
            Config instance with values from all sources
        """
        # Ensure defaults are included as last source
        source_names = [name for name, _, _ in self._sources]
        if "defaults" not in source_names:
            self.add_defaults()

        # Load data from each source
        loaded_list: list[tuple[str, LoadedData]] = []
        for name, loader, mapper in self._sources:
            if loader is DefaultsExtractor:
                loaded = loader.extract(self.config_class)
            elif hasattr(loader, 'load_data'):
                loaded = loader.load_data()
            else:
                raise TypeError(f"Loader {name} must have load_data() method")

            loaded_list.append((name, loaded))

        # Transform each LoadedData to ConfigFragment
        fragments: list[ConfigFragment] = []
        for (name, loaded), (_, _, mapper) in zip(loaded_list, self._sources):
            extractor = FieldExtractor(self.config_class, loaded.loader, mapper)
            fragment = extractor.extract_fragment(loaded)
            fragments.append(fragment)

        # Merge fragments (first wins)
        merged_data = merge_fragments(fragments)

        # Create Config instance
        config = self.config_class.from_data(merged_data)

        # Attach debug info if requested
        if debug:
            merged_fragment = MergedFragment(fragments)
            attach_debug_info(config, merged_fragment)

        return config


    @classmethod
    def standard(
        cls,
        config_class: type[Config],
        *,
        cli_args: argparse.Namespace | None = None,
        env_prefix: str | None = None,
        config_file: Path | str | None = None
    ) -> Self:
        """
        Create loader with standard sources in conventional priority order.

        Priority: CLI → ENV → FILE → DEFAULTS

        Args:
            config_class: The Config class to load
            cli_args: Optional CLI arguments
            env_prefix: Optional environment variable prefix
            config_file: Optional config file path

        Returns:
            ConfigLoader with sources added in priority order

        Example:
            ```python
            loader = ConfigLoader.standard(
                MyConfig,
                cli_args=parser.parse_args(),
                env_prefix="APP",
                config_file="config.toml"
            )
            config = loader.load(debug=True)

            debug = get_debug_info(config)
            print(debug.get_origin("database.host"))
            ```
        """
        loader = cls(config_class)

        # Add sources in priority order (highest first)
        if cli_args is not None:
            loader.add_cli(cli_args)

        if env_prefix is not None:
            loader.add_env(prefix=env_prefix)

        if config_file is not None:
            loader.add_file(config_file)

        # Defaults added automatically in load()

        return loader
```

---

## Usage Examples

### Basic Usage with Debug Info

```python
from cot.config import Config, field, ConfigLoader
from cot.config.fragments import get_debug_info

class DatabaseConfig(Config):
    host: str = field(default="localhost")
    port: int = field(default=5432)

class AppConfig(Config):
    debug: bool = field(default=False)
    database: DatabaseConfig = sub_config(DatabaseConfig)

# Simple loading
loader = ConfigLoader.standard(
    AppConfig,
    cli_args=parser.parse_args(),
    env_prefix="APP",
    config_file="config.toml"
)

config = loader.load(debug=True)

# Get debug info
debug = get_debug_info(config)
if debug:
    print(f"database.host from: {debug.get_origin('database.host')}")
    print(f"Override chain: {debug.get_all_origins('debug')}")
```

### Custom Source Order

```python
# Full control over source priority
loader = ConfigLoader(AppConfig)
loader.add_env(prefix="APP")  # Highest priority
loader.add_file("local.toml")
loader.add_file("defaults.toml")
# defaults added automatically

config = loader.load(debug=True)
```

### Testing

```python
# Easy testing with controlled sources
def test_config_loading():
    loader = ConfigLoader(AppConfig)

    # Add test env vars
    test_env = {"APP_DEBUG": "true", "APP_DATABASE_HOST": "testdb"}
    loader.add_env(prefix="APP", environ=test_env)

    config = loader.load(debug=True)

    assert config.debug is True
    assert config.database.host == "testdb"

    # Verify origins
    debug = get_debug_info(config)
    assert debug.get_origin("debug").loader_type == EnvironmentAdapter
```

---

## Config Class Integration

Add convenience methods to Config class:

```python
class Config(metaclass=ConfigMeta):
    """Base class for configuration objects."""

    @classmethod
    def load(
        cls,
        *,
        cli_args: argparse.Namespace | None = None,
        env_prefix: str | None = None,
        config_file: Path | str | None = None,
        debug: bool = False
    ) -> Self:
        """
        Convenience method for standard config loading.

        Args:
            cli_args: Optional CLI arguments
            env_prefix: Optional environment variable prefix
            config_file: Optional config file path
            debug: If True, attach fragment debug info (use get_debug_info() to access)

        Returns:
            Config instance loaded from all sources

        Example:
            ```python
            config = MyConfig.load(
                cli_args=parser.parse_args(),
                env_prefix="MYAPP",
                config_file="config.toml",
                debug=True
            )

            # Access debug info
            from cot.config.fragments import get_debug_info
            debug = get_debug_info(config)
            if debug:
                print(debug.get_origin("database.host"))
            ```
        """
        from .loader import ConfigLoader

        loader = ConfigLoader.standard(
            cls,
            cli_args=cli_args,
            env_prefix=env_prefix,
            config_file=config_file
        )

        return loader.load(debug=debug)

    @classmethod
    def loader(cls) -> ConfigLoader:
        """
        Create a ConfigLoader for this Config class.

        Returns:
            ConfigLoader instance for building custom loading workflow

        Example:
            ```python
            config = (MyConfig.loader()
                .add_cli(args)
                .add_env(prefix="APP")
                .add_file("config.toml")
                .load(debug=True))

            from cot.config.fragments import get_debug_info
            debug = get_debug_info(config)
            ```
        """
        from .loader import ConfigLoader
        return ConfigLoader(cls)
```

---

## Summary

### Key Components

1. **ConfigLoader**: Coordinates multiple sources and manages workflow
2. **get_debug_info()**: Retrieves debug info for config instances
3. **attach_debug_info()**: Internal function to attach debug info (uses weak references)
4. **load_data() on adapters**: Each adapter produces LoadedData
5. **DefaultsExtractor**: Extracts defaults from Config class
6. **Config.load()**: Convenience method for standard loading
7. **Config.loader()**: Factory for custom loading workflows

### Benefits

1. **Simple API**: One class coordinates everything
2. **Clean debug access**: `get_debug_info()` function instead of internal attributes
3. **No memory leaks**: Weak references for debug info
4. **Flexible**: Easy to customize source order and types
5. **Debuggable**: Built-in origin tracking
6. **Testable**: Easy to provide test sources

### Migration Strategy

1. **Phase 1**: Implement ConfigLoader
2. **Phase 2**: Add load_data() to adapters
3. **Phase 3**: Add Config convenience methods
4. **Phase 4**: Document and promote

No breaking changes required!
