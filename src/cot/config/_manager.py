"""ConfigManager for orchestrating configuration loading."""

from __future__ import annotations

from typing import (
    Any,
    Protocol,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
    runtime_checkable,
)

from ._annotations import ConfigSourceMarker, FromParentMarker
from ._bases import ConfigPart, SubConfig

_T = TypeVar("_T", bound=ConfigPart)


@runtime_checkable
class ConfigSource(Protocol):
    """Protocol for configuration sources."""

    @property
    def precedence(self) -> int:
        """Higher values override lower values."""
        ...

    def load(self, part_type: type[ConfigPart]) -> dict[str, Any]:
        """Load configuration data for a ConfigPart type."""
        ...


@runtime_checkable
class Discoverable(Protocol):
    """
    Protocol for ConfigParts that can discover/modify sources before loading.

    The discover classmethod is called BEFORE the instance is created,
    allowing it to add sources (e.g., discovered config files) that will
    be used when loading the final instance.
    """

    @classmethod
    def discover(cls, manager: ConfigManager) -> None:
        """
        Discover and add sources before instance creation.

        This is called before loading data from sources, allowing the
        ConfigPart to inspect bootstrap fragments and add new sources
        (e.g., a config file path from CLI args).

        Args:
            manager: ConfigManager to add sources to
        """
        ...


class ConfigManager:
    """
    Orchestrates configuration loading from multiple sources.

    The ConfigManager coordinates the bootstrap process, manages sources,
    and builds final ConfigPart instances.

    Example:
        manager = ConfigManager(
            invocation_dir=Path.cwd(),
            args=sys.argv[1:],
        )
        manager.register_fragment_type(PytestConfig)
        config = manager.get_fragment(PytestConfig)
    """

    def __init__(
        self,
        invocation_dir: Any | None = None,
        args: list[str] | None = None,
        *,
        bootstrap_fragments: list[ConfigPart] | None = None,
    ) -> None:
        """
        Create ConfigManager with invocation context.

        Args:
            invocation_dir: Directory where command was invoked (for resolving
                relative config file paths). Defaults to current directory.
            args: Command line arguments. Defaults to sys.argv[1:].
            bootstrap_fragments: Pre-built ConfigPart instances that
                provide initial context (e.g., invocation directory, CLI args)
        """
        import sys
        from pathlib import Path

        self._fragments: dict[type[ConfigPart], ConfigPart] = {}
        self._sources: list[ConfigSource] = []

        # Store invocation context
        self._invocation_dir = (
            Path(invocation_dir) if invocation_dir is not None else Path.cwd()
        )
        self._args = args if args is not None else sys.argv[1:]

        # Store bootstrap fragments and process config_source markers
        if bootstrap_fragments:
            for fragment in bootstrap_fragments:
                self._fragments[type(fragment)] = fragment
                self._process_config_sources(fragment)

    @property
    def invocation_dir(self) -> Any:
        """Directory where command was invoked."""
        return self._invocation_dir

    @property
    def args(self) -> list[str]:
        """Command line arguments."""
        return self._args

    def add_source(self, source: ConfigSource) -> None:
        """
        Add a configuration source.

        Sources are kept sorted by precedence (lowest first).
        """
        self._sources.append(source)
        self._sources.sort(key=lambda s: s.precedence)

    def register_fragment_type(
        self,
        fragment_type: type[_T],
    ) -> _T:
        """
        Register a ConfigPart type and return the loaded instance.

        Process:
        1. Load CLI args for this type (highest precedence)
        2. If type has discover(), call it to add sources (e.g., config files)
        3. Load data from all sources + CLI
        4. Process config_source markers to add discovered config files
        5. Re-load with new sources
        6. Build instance with defaults merged with loaded data
        7. Store and return the final instance

        Args:
            fragment_type: ConfigPart class to register

        Returns:
            Loaded ConfigPart instance
        """
        from ._sources import CLISource

        # Load CLI args for this type
        cli_source = CLISource(self._args, precedence=25)
        cli_data = cli_source.load(fragment_type)

        # Call discover if available (adds sources before loading)
        discover_method = getattr(fragment_type, "discover", None)
        if discover_method is not None and callable(discover_method):
            discover_method(self)

        # Load data from all registered sources
        loaded = self.load_for_part(fragment_type)

        # Get field defaults from type annotations
        defaults = _get_field_defaults(fragment_type)

        # Merge: defaults < sources < cli (cli has highest precedence)
        merged = {**defaults, **loaded, **cli_data}

        # Check for config_source markers and add sources
        self._process_config_source_fields(fragment_type, merged)

        # Re-load from sources now that config files may have been added
        loaded = self.load_for_part(fragment_type)
        merged = {**defaults, **loaded, **cli_data}

        # Build nested SubConfigs from type hints
        merged = _build_nested_subconfigs(fragment_type, merged)

        # Create instance
        instance = fragment_type(**merged)

        # Store
        self._fragments[fragment_type] = instance

        return instance

    def get_fragment(self, fragment_type: type[_T]) -> _T:
        """
        Get a stored fragment by type.

        Args:
            fragment_type: ConfigPart class to retrieve

        Returns:
            The stored ConfigPart instance

        Raises:
            KeyError: If fragment type not registered
        """
        if fragment_type not in self._fragments:
            raise KeyError(f"Fragment type {fragment_type.__name__} not registered")
        return self._fragments[fragment_type]  # type: ignore[return-value]

    def load_for_part(
        self,
        fragment_type: type[ConfigPart],
    ) -> dict[str, Any]:
        """
        Load data for a ConfigPart from all active sources.

        Merges data from all sources in precedence order.
        Used by discover() methods to get source data.

        Args:
            fragment_type: ConfigPart class to load data for

        Returns:
            Dict of field names to values
        """
        merged: dict[str, Any] = {}
        for source in self._sources:
            data = source.load(fragment_type)
            _deep_merge(merged, data)
        return merged

    @property
    def sources(self) -> list[ConfigSource]:
        """Get list of registered sources (sorted by precedence)."""
        return list(self._sources)

    def _process_config_source_fields(
        self, fragment_type: type[ConfigPart], data: dict[str, Any]
    ) -> None:
        """
        Process fields marked with config_source annotation from merged data.

        For each field with the config_source marker, if the value is a
        path to a config file, add it as a source.

        This is called during register_fragment_type BEFORE the instance
        is created, using the merged data from defaults + sources + CLI.

        Raises:
            FileNotFoundError: If a config file is specified but doesn't exist
        """
        from pathlib import Path

        from ._sources import TomlSource

        hints = get_type_hints(fragment_type, include_extras=True)

        for field_name, field_type in hints.items():
            marker = _get_config_source_marker(field_type)
            if marker is None:
                continue

            value = data.get(field_name)
            if value is None:
                continue

            # Convert string to Path if needed
            if isinstance(value, str):
                value = Path(value)

            # If it's a relative path, resolve against invocation_dir
            if isinstance(value, Path) and not value.is_absolute():
                value = self._invocation_dir / value

            # Check file exists - error if explicitly specified but missing
            if isinstance(value, Path):
                if not value.exists():
                    raise FileNotFoundError(
                        f"Config file not found: {value} "
                        f"(specified via {field_name})"
                    )
                if value.suffix in (".toml",):
                    self.add_source(TomlSource(value, precedence=marker.precedence))

    def _process_config_sources(self, fragment: ConfigPart) -> None:
        """
        Process fields marked with config_source annotation on a fragment instance.

        For each field with the config_source marker, if the value is a
        valid path to a config file, add it as a source.
        """
        from pathlib import Path

        from ._sources import TomlSource

        hints = get_type_hints(type(fragment), include_extras=True)

        for field_name, field_type in hints.items():
            marker = _get_config_source_marker(field_type)
            if marker is None:
                continue

            value = getattr(fragment, field_name, None)
            if value is None:
                continue

            # Convert string to Path if needed
            if isinstance(value, str):
                value = Path(value)

            # If it's a relative path and we have invocation_dir, resolve it
            if isinstance(value, Path) and not value.is_absolute():
                invocation_dir = getattr(fragment, "invocation_dir", None)
                if invocation_dir is not None:
                    value = invocation_dir / value

            # Add as source if file exists and is a supported type
            if (
                isinstance(value, Path)
                and value.exists()
                and value.suffix in (".toml",)
            ):
                self.add_source(TomlSource(value, precedence=marker.precedence))


def _get_field_defaults(cls: type[ConfigPart]) -> dict[str, Any]:
    """Extract field defaults from a ConfigPart class, including inherited fields."""
    defaults: dict[str, Any] = {}

    # Walk MRO to get all annotations (child classes first, so they override)
    for klass in reversed(cls.__mro__):
        annotations = getattr(klass, "__annotations__", {})
        for field_name in annotations:
            # Skip ClassVar and other special types
            if field_name.startswith("_"):
                continue
            if hasattr(klass, field_name):
                value = getattr(klass, field_name)
                # Don't include class methods or other descriptors
                if not callable(value):
                    defaults[field_name] = value

    return defaults


def _is_subconfig_type(field_type: Any) -> bool:
    """Check if a type annotation is a SubConfig subclass."""
    # Handle raw class types
    return isinstance(field_type, type) and issubclass(field_type, SubConfig)


def _build_nested_subconfigs(
    cls: type[ConfigPart] | type[SubConfig],
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Recursively convert nested dicts to SubConfig instances.

    For each field annotated as a SubConfig type, if the value is a dict,
    convert it to the appropriate SubConfig instance.

    Also handles parent-to-child cascade: if the parent has a field with
    the same name as a SubConfig field (e.g., parent.level), that value
    cascades to children that don't explicitly set it.
    """
    try:
        hints = get_type_hints(cls)
    except Exception:
        hints = getattr(cls, "__annotations__", {})

    result = dict(data)

    # Collect parent values that could cascade to children
    # These are non-SubConfig fields in the parent data
    cascade_values: dict[str, Any] = {}
    for field_name, field_type in hints.items():
        if not _is_subconfig_type(field_type) and field_name in result:
            cascade_values[field_name] = result[field_name]

    for field_name, field_type in hints.items():
        if not _is_subconfig_type(field_type):
            continue

        value = result.get(field_name)

        # Get SubConfig's own field names to know what can cascade
        subconfig_hints = _get_subconfig_hints(field_type)

        if isinstance(value, dict):
            # Get defaults for the SubConfig type
            subconfig_defaults = _get_subconfig_defaults(field_type)
            # Apply cascade: parent values fill in for missing child values
            cascaded = _apply_cascade(cascade_values, subconfig_hints, value)
            # Merge: class defaults < cascade < explicit values
            merged_value = {**subconfig_defaults, **cascaded}
            # Recursively build nested SubConfigs
            merged_value = _build_nested_subconfigs(field_type, merged_value)
            # Create the SubConfig instance
            result[field_name] = field_type(**merged_value)
        elif value is None or field_name not in result:
            # Create with defaults when missing or None
            subconfig_defaults = _get_subconfig_defaults(field_type)
            # Apply cascade even when child section is missing
            cascaded = _apply_cascade(cascade_values, subconfig_hints, {})
            merged_value = {**subconfig_defaults, **cascaded}
            merged_value = _build_nested_subconfigs(field_type, merged_value)
            result[field_name] = field_type(**merged_value)

    return result


def _get_subconfig_hints(cls: type[SubConfig]) -> dict[str, Any]:
    """Get type hints for a SubConfig class, preserving Annotated metadata."""
    try:
        # include_extras=True preserves Annotated wrappers
        return get_type_hints(cls, include_extras=True)
    except Exception:
        return getattr(cls, "__annotations__", {})


def _apply_cascade(
    parent_values: dict[str, Any],
    child_hints: dict[str, Any],
    child_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Apply parent values to child where child doesn't have explicit value.

    Only cascades values for fields that:
    1. Are marked with `from_parent` annotation
    2. Exist in the parent's data
    3. Are not already set in the child's data

    Child's explicit values take precedence over cascaded values.
    """
    result = dict(child_data)
    for field_name, field_type in child_hints.items():
        # Only cascade if field is marked with from_parent and not already set
        if (
            field_name not in result
            and field_name in parent_values
            and _has_from_parent_marker(field_type)
        ):
            result[field_name] = parent_values[field_name]
    return result


def _has_from_parent_marker(field_type: Any) -> bool:
    """Check if a field type has the from_parent marker annotation."""
    from typing import Annotated

    # Check if it's an Annotated type
    if get_origin(field_type) is Annotated:
        args = get_args(field_type)
        # args[0] is the actual type, args[1:] are the annotations
        for arg in args[1:]:
            if isinstance(arg, FromParentMarker):
                return True
    return False


def _get_config_source_marker(field_type: Any) -> ConfigSourceMarker | None:
    """Get the config_source marker from a field type if present."""
    from typing import Annotated

    # Check if it's an Annotated type
    if get_origin(field_type) is Annotated:
        args = get_args(field_type)
        # args[0] is the actual type, args[1:] are the annotations
        for arg in args[1:]:
            if isinstance(arg, ConfigSourceMarker):
                return arg
    return None


def _get_subconfig_defaults(cls: type[SubConfig]) -> dict[str, Any]:
    """Extract field defaults from a SubConfig class, including inherited fields."""
    defaults: dict[str, Any] = {}

    # Walk MRO to get all annotations (child classes first, so they override)
    for klass in reversed(cls.__mro__):
        annotations = getattr(klass, "__annotations__", {})
        for field_name in annotations:
            # Skip ClassVar and other special types
            if field_name.startswith("_"):
                continue
            if hasattr(klass, field_name):
                value = getattr(klass, field_name)
                # Don't include class methods or other descriptors
                if not callable(value):
                    defaults[field_name] = value

    return defaults


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Deep merge source into target, modifying target in place."""
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value


__all__ = [
    "ConfigManager",
    "ConfigSource",
    "Discoverable",
]
