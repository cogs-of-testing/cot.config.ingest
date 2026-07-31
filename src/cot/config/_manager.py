"""ConfigManager for orchestrating configuration loading."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import (
    Any,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from ._annotations import (
    AddoptsMarker,
    BootstrapOnlyMarker,
    ConfigSourceMarker,
    FromParentMarker,
)
from ._bases import ConfigPart, SubConfig
from ._fields import (
    MISSING,
    field_defaults,
    fields_of,
    has_marker,
    leaf_fields,
    marker_of,
)
from ._origins import Origin, default_origin, generic_origin

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

    The ConfigManager coordinates sources and builds final ConfigPart instances.
    Sources handle all context (invocation_dir, args, env vars, config files).

    Example:
        cli = CLISource(args=sys.argv[1:], invocation_dir=Path.cwd())
        env = EnvSource(prefix="MYAPP")
        files = ConfigFileDiscoverySource(
            invocation_dir=cli.invocation_dir,
            cli_source=cli,
        )
        manager = ConfigManager(sources=[cli, env, files])
        config = manager.register_fragment_type(MyConfig)
    """

    def __init__(
        self,
        sources: Sequence[ConfigSource] = (),
    ) -> None:
        """
        Create ConfigManager with sources.

        Args:
            sources: Configuration sources (CLI, env, files, etc.)
                Sources are sorted by precedence. Higher precedence wins.

        Note: CLISource should be passed in directly if CLI args are needed.
        The ConfigManager no longer creates sources automatically.
        """
        from ._sources import CLISource

        self._fragments: dict[type[ConfigPart], ConfigPart] = {}
        self._sources: list[ConfigSource] = []
        self._cli_source: CLISource | None = None
        self._origins: dict[type[ConfigPart], dict[str, Origin]] = {}

        # Add all sources
        for source in sources:
            self.add_source(source)
            # Track CLI source for registration and addopts
            if isinstance(source, CLISource):
                self._cli_source = source

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
        1. Register fragment type with CLI source (adds fields to parser)
        2. Load bootstrap fields from CLI (config_source, etc.)
        3. If type has discover(), call it to add sources
        4. Process config_source markers to add config files
        5. Load from file/env sources to get addopts
        6. Prepend addopts to CLI source
        7. Load final values from all sources + CLI
        8. Build instance with defaults merged with loaded data
        9. Store and return the final instance

        Args:
            fragment_type: ConfigPart class to register

        Returns:
            Loaded ConfigPart instance
        """
        # Get field defaults from type annotations
        defaults = field_defaults(fragment_type)

        # Register with CLI source and load CLI args if available
        cli_data: dict[str, Any] = {}
        if self._cli_source is not None:
            self._cli_source.register_fragment_type(fragment_type)
            cli_data = self._cli_source.load(fragment_type)

        # Call discover if available (adds sources before loading)
        discover_method = getattr(fragment_type, "discover", None)
        if discover_method is not None and callable(discover_method):
            discover_method(self)

        # Check for config_source markers in CLI data and add sources
        bootstrap_merged = {**defaults, **cli_data}
        self._process_config_source_fields(fragment_type, bootstrap_merged)

        # Load from file/env sources to get addopts
        loaded = self.load_for_part(fragment_type)

        # Process addopts fields - prepend to CLI source (if available)
        self._process_addopts_fields(fragment_type, {**defaults, **loaded, **cli_data})

        # Now load final CLI data (includes addopts) if CLI source available
        if self._cli_source is not None:
            cli_data = self._cli_source.load(fragment_type)

        # Merge: defaults < sources < cli (cli has highest precedence).
        # This must be a deep merge: CLI and file sources both produce nested
        # dicts for SubConfigs, and a shallow update would let `--log-file-level`
        # from the CLI wipe `log_file` from the config file.
        #
        # Provenance rides along with the merge: whichever source last wrote a
        # path is the one that won it.
        origins: dict[str, Origin] = {}
        merged: dict[str, Any] = {}

        _deep_merge(merged, defaults)
        # Seed every leaf that declares a default, nested ones included, so a
        # value nobody configured still reports *why* it has the value it has.
        for field in leaf_fields(fragment_type):
            if field.default is not MISSING:
                origins[field.dotted] = default_origin(field.dotted)

        for source in self._sources:
            data = source.load(fragment_type)
            _deep_merge(merged, data)
            self._record_origins(origins, source, fragment_type, data)

        if self._cli_source is not None:
            _deep_merge(merged, cli_data)
            self._record_origins(origins, self._cli_source, fragment_type, cli_data)

        self._origins[fragment_type] = origins

        # Keys a source produced that the ConfigPart does not declare are user
        # error in a config file, not programmer error -- warn and drop them
        # rather than letting the constructor reject the whole load.
        merged = _drop_unknown_keys(fragment_type, merged)

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

    def _record_origins(
        self,
        origins: dict[str, Origin],
        source: ConfigSource,
        fragment_type: type[ConfigPart],
        data: dict[str, Any],
    ) -> None:
        """Attribute every path ``data`` supplied to ``source``."""
        describe = getattr(source, "describe_origin", None)
        fallback = generic_origin(source)

        for dotted, path in _dotted_paths(data, with_paths=True):
            origin: Origin | None = None
            if callable(describe):
                origin = describe(fragment_type, path)
            origins[dotted] = origin if origin is not None else fallback

    def format_help(self, *, prog: str | None = None) -> str:
        """
        Render help text for every option registered so far.

        Returns the text; it never prints and never exits. Whether `--help`
        was asked for is `help_requested()`, and what to do about it is the
        application's decision.
        """
        if self._cli_source is None:
            return "options:\n  (no CLI source configured)\n"
        return self._cli_source.format_help(prog=prog)

    def help_requested(self) -> bool:
        """Whether -h/--help appeared in the command line arguments."""
        if self._cli_source is None:
            return False
        return self._cli_source.help_requested()

    def origin_of(self, fragment_type: type[ConfigPart], path: str) -> Origin:
        """
        Report where a field's final value came from.

        Args:
            fragment_type: A registered ConfigPart class.
            path: Dotted field path, e.g. "cli.level".

        Returns:
            The Origin of the winning value.

        Raises:
            KeyError: If the type was never registered, or the path is unknown.
        """
        if fragment_type not in self._origins:
            raise KeyError(f"Fragment type {fragment_type.__name__} not registered")
        origins = self._origins[fragment_type]
        if path not in origins:
            raise KeyError(f"No origin recorded for {fragment_type.__name__}.{path}")
        return origins[path]

    def origins(self, fragment_type: type[ConfigPart]) -> dict[str, Origin]:
        """Every recorded origin for a registered ConfigPart, keyed by path."""
        if fragment_type not in self._origins:
            raise KeyError(f"Fragment type {fragment_type.__name__} not registered")
        return dict(self._origins[fragment_type])

    def explain(self, fragment_type: type[ConfigPart]) -> str:
        """
        Render a table of every field's value and where it came from.

        Intended for `--debug-config` style output: the whole point of merging
        sources is that the winner is not obvious from any single one of them.
        """
        instance = self.get_fragment(fragment_type)
        recorded = self._origins.get(fragment_type, {})

        rows: list[tuple[str, str, str]] = []
        for field in leaf_fields(fragment_type):
            dotted = field.dotted
            value: Any = instance
            for segment in field.path:
                value = getattr(value, segment, None)
            origin = recorded.get(dotted)
            rows.append((dotted, repr(value), str(origin) if origin else "unset"))

        if not rows:
            return f"{fragment_type.__name__}: no fields\n"

        widths = [max(len(row[column]) for row in rows) for column in range(3)]
        header = (
            f"{'field'.ljust(widths[0])}  "
            f"{'value'.ljust(widths[1])}  "
            f"{'origin'.ljust(widths[2])}"
        ).rstrip()

        lines = [f"{fragment_type.__name__}:", header, "-" * len(header)]
        lines.extend(
            f"{name.ljust(widths[0])}  {value.ljust(widths[1])}  {origin}".rstrip()
            for name, value, origin in rows
        )
        return "\n".join(lines) + "\n"

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

        for field in fields_of(fragment_type, recurse=False):
            marker = marker_of(field, ConfigSourceMarker)
            if marker is None:
                continue

            field_name = field.name
            value = data.get(field_name)
            if value is None:
                continue

            # Convert string to Path if needed
            if isinstance(value, str):
                value = Path(value)

            # If it's a relative path, resolve against invocation_dir
            if isinstance(value, Path) and not value.is_absolute():
                invocation_dir = (
                    self._cli_source.invocation_dir
                    if self._cli_source is not None
                    else Path.cwd()
                )
                value = invocation_dir / value

            # Check file exists - error if explicitly specified but missing
            if isinstance(value, Path):
                if not value.exists():
                    raise FileNotFoundError(
                        f"Config file not found: {value} (specified via {field_name})"
                    )
                if value.suffix in (".toml",):
                    self.add_source(TomlSource(value, precedence=marker.precedence))

    def _process_addopts_fields(
        self,
        fragment_type: type[ConfigPart],
        data: dict[str, Any],
    ) -> None:
        """
        Process fields marked with addopts_field annotation.

        For each field with the addopts_field marker, prepend its value
        to the CLI source's args.

        Also validates that no bootstrap_only fields are being set via addopts.

        Args:
            fragment_type: ConfigPart class being registered
            data: Merged data from all sources

        Raises:
            ValueError: If addopts tries to set a bootstrap_only field
        """
        part_fields = fields_of(fragment_type, recurse=False)

        # Find bootstrap_only fields
        bootstrap_only_fields = {
            f.name for f in part_fields if has_marker(f, BootstrapOnlyMarker)
        }

        # Find addopts fields and process them
        for field in part_fields:
            marker = marker_of(field, AddoptsMarker)
            if marker is None:
                continue

            value = data.get(field.name)
            if not value:
                continue

            # Handle both string and list addopts (TOML can have lists)
            addopts: str | list[str]
            if isinstance(value, str | list):
                addopts = value
            else:
                continue

            # Check for bootstrap_only violations before prepending
            # We need to parse to check, but we'll use the CLI source to do it
            import shlex

            if isinstance(addopts, str):
                try:
                    addopts_list = shlex.split(addopts)
                except ValueError:
                    addopts_list = addopts.split()
            else:
                addopts_list = list(addopts)

            # Check each arg for bootstrap_only fields
            for arg in addopts_list:
                if arg.startswith("--"):
                    # Extract field name from --field-name or --field-name=value
                    field_part = arg[2:].split("=")[0]
                    field_as_python = field_part.replace("-", "_")
                    if field_as_python in bootstrap_only_fields:
                        raise ValueError(
                            f"Cannot set bootstrap-only field '{field_as_python}' "
                            f"via addopts. Field '{field_as_python}' must be set "
                            f"via CLI arguments, not in config file addopts."
                        )

            # Prepend addopts to CLI source (if available)
            if self._cli_source is not None:
                self._cli_source.prepend_addopts(addopts)


class UnknownConfigKeyWarning(UserWarning):
    """A source supplied a key the ConfigPart does not declare."""


def _drop_unknown_keys(
    fragment_type: type[ConfigPart],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Drop keys not declared on ``fragment_type``, warning about each."""
    known = {field.name for field in fields_of(fragment_type, recurse=False)}
    unknown = sorted(set(data) - known)
    if unknown:
        warnings.warn(
            f"Unknown config option(s) for {fragment_type.__name__}: "
            f"{', '.join(unknown)}",
            UnknownConfigKeyWarning,
            stacklevel=3,
        )
    return {key: value for key, value in data.items() if key in known}


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
    own_fields = fields_of(cls, recurse=False)
    result = dict(data)

    # Collect parent values that could cascade to children.
    # These are the non-SubConfig fields present in the parent data.
    cascade_values = {
        field.name: result[field.name]
        for field in own_fields
        if not field.is_sub_config and field.name in result
    }

    for field in own_fields:
        if not field.is_sub_config:
            continue

        sub_type: type[SubConfig] = field.type
        value = result.get(field.name)

        if not isinstance(value, dict):
            if value is not None and field.name in result:
                # Already an instance (or something else the caller supplied).
                continue
            value = {}

        # Merge: class defaults < cascaded parent values < explicit values
        merged_value = {
            **field_defaults(sub_type),
            **_apply_cascade(cascade_values, sub_type, value),
        }
        merged_value = _build_nested_subconfigs(sub_type, merged_value)
        result[field.name] = sub_type(**merged_value)

    return result


def _apply_cascade(
    parent_values: dict[str, Any],
    child_type: type[SubConfig],
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
    for field in fields_of(child_type, recurse=False):
        if (
            field.name not in result
            and field.name in parent_values
            and has_marker(field, FromParentMarker)
        ):
            result[field.name] = parent_values[field.name]
    return result


def _dotted_paths(
    data: dict[str, Any],
    *,
    prefix: tuple[str, ...] = (),
    with_paths: bool = False,
) -> list[Any]:
    """Every leaf path in a nested dict, as dotted strings.

    With ``with_paths``, yields ``(dotted, path_tuple)`` pairs instead, which
    is what origin lookup needs.
    """
    result: list[Any] = []
    for key, value in data.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            result.extend(_dotted_paths(value, prefix=path, with_paths=with_paths))
        else:
            dotted = ".".join(path)
            result.append((dotted, path) if with_paths else dotted)
    return result


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
