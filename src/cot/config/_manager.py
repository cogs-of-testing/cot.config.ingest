"""ConfigManager for orchestrating configuration loading."""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
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

if TYPE_CHECKING:
    from ._sources import AddoptsSource

_T = TypeVar("_T", bound=ConfigPart)


class ConfigLifecycleError(RuntimeError):
    """A configuration operation happened in the wrong phase."""


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
class DeclaringSource(Protocol):
    """Optional protocol: a source that needs to know about types up front.

    A file or environment source reads whatever names it is asked about, so it
    has nothing to declare. A source backed by an argument parser does: the
    parser has to be told an option exists before it can parse it.
    """

    def declare(self, part_type: type[ConfigPart]) -> None:
        """Register a ConfigPart type's fields as options."""
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
        manager.declare(MyConfig)
        config = manager.get(MyConfig)
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
        self._declared: list[type[ConfigPart]] = []
        self._sources: list[ConfigSource] = []
        self._cli_source: CLISource | None = None
        self._addopts_source: AddoptsSource | None = None
        self._origins: dict[type[ConfigPart], dict[str, Origin]] = {}
        self._resolved = False
        self._resolving = False

        for source in sources:
            self.add_source(source)

    def add_source(self, source: ConfigSource) -> None:
        """
        Add a configuration source.

        Sources are kept sorted by precedence (lowest first). A source added
        after declarations have been made still learns about them, which is
        what lets a config file discovered during resolve() participate.
        """
        from ._sources import AddoptsSource, CLISource

        self._sources.append(source)
        self._sources.sort(key=lambda s: s.precedence)

        # A CLI source is tracked separately: the bootstrap passes have to read
        # it before the full merge exists, to learn which config file to open.
        if isinstance(source, CLISource):
            self._cli_source = source
        if isinstance(source, AddoptsSource):
            self._addopts_source = source

        declare = getattr(source, "declare", None)
        if callable(declare):
            for fragment_type in self._declared:
                declare(fragment_type)

    # -- Phase 1: declaration --------------------------------------------

    def declare(self, fragment_type: type[ConfigPart]) -> None:
        """
        Declare a ConfigPart type and its options. Nothing is loaded yet.

        Declaration is separate from resolution because a host may collect
        declarations from many independent plugins before any of them can be
        resolved. pytest is the motivating case: every plugin's
        `pytest_addoption` runs before a single argument is parsed, so a
        fragment built at declaration time could not see options declared by a
        plugin loaded after it.

        Declaring the same type twice is a no-op.

        Raises:
            ConfigLifecycleError: If called after resolve().
        """
        if self._resolved:
            raise ConfigLifecycleError(
                f"Cannot declare {fragment_type.__name__} after resolve(); "
                f"configuration is already frozen"
            )
        if fragment_type in self._declared:
            return
        self._declared.append(fragment_type)
        self._declare_to_sources(fragment_type)

    @property
    def declared(self) -> list[type[ConfigPart]]:
        """The ConfigPart types declared so far, in declaration order."""
        return list(self._declared)

    def _declare_to_sources(self, fragment_type: type[ConfigPart]) -> None:
        """Let every source that accepts declarations register the type.

        `declare` is optional on the ConfigSource protocol: a file or env
        source has nothing to declare, while CLISource adds parser options and
        the pytest adapter forwards to `parser.addoption`/`addini`.
        """
        for source in self._sources:
            declare = getattr(source, "declare", None)
            if callable(declare):
                declare(fragment_type)

    # -- Phase 2: resolution ---------------------------------------------

    @property
    def resolved(self) -> bool:
        """Whether resolve() has run and the configuration is frozen."""
        return self._resolved

    def resolve(self) -> None:
        """
        Run the bootstrap feedback loops once and build every declared fragment.

        Idempotent, and triggered automatically by the first `get()`. Calling
        it explicitly is how a host pins the moment configuration freezes.

        The staging matters: every declared type contributes config files
        before any type reads them, and every type contributes addopts before
        any type is built. Doing this per-fragment -- as the previous API did
        -- meant a fragment could be built against a source a later fragment
        was about to add.
        """
        if self._resolved or self._resolving:
            return
        self._resolving = True
        try:
            for fragment_type in self._declared:
                self._run_discover(fragment_type)

            # Every config_source field across all fragments, so the files are
            # all present before anything reads them.
            for fragment_type in self._declared:
                self._collect_config_sources(fragment_type)

            # Then every addopts field, so the CLI is complete before parsing.
            for fragment_type in self._declared:
                self._collect_addopts(fragment_type)

            for fragment_type in self._declared:
                self._fragments[fragment_type] = self._build(fragment_type)
        finally:
            self._resolving = False
        self._resolved = True

    def _run_discover(self, fragment_type: type[ConfigPart]) -> None:
        """Call the type's discover() hook, if it implements Discoverable."""
        if issubclass(fragment_type, Discoverable):
            fragment_type.discover(self)

    def _collect_config_sources(self, fragment_type: type[ConfigPart]) -> None:
        """Turn this type's config_source fields into sources.

        Every source that already exists is consulted, not just the CLI: a
        config file named by an environment variable is as explicit a request
        as one named by an argument.
        """
        defaults = field_defaults(fragment_type)
        loaded = self.load_for_part(fragment_type)
        self._process_config_source_fields(fragment_type, {**defaults, **loaded})

    def _collect_addopts(self, fragment_type: type[ConfigPart]) -> None:
        """Feed this type's addopts field into the addopts source."""
        defaults = field_defaults(fragment_type)
        loaded = self.load_for_part(fragment_type)
        self._process_addopts_fields(fragment_type, {**defaults, **loaded})

    def _load_cli(self, fragment_type: type[ConfigPart]) -> dict[str, Any]:
        if self._cli_source is None:
            return {}
        return self._cli_source.load(fragment_type)

    def _build(self, fragment_type: type[ConfigPart]) -> ConfigPart:
        """Merge every source into one instance, recording provenance.

        Sources are already sorted by precedence, and that order is the only
        thing deciding a winner -- no source is special-cased above the ladder.
        """
        defaults = field_defaults(fragment_type)

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

        # Keys a source produced that the ConfigPart does not declare are user
        # error in a config file, not programmer error -- warn and drop them
        # rather than letting the constructor reject the whole load.
        merged = _drop_unknown_keys(fragment_type, merged)

        # Build nested SubConfigs from type hints
        inherited: dict[str, str] = {}
        merged = _build_nested_subconfigs(fragment_type, merged, inherited=inherited)

        # A cascaded value did not come from the child's own default -- it came
        # from wherever the parent got it. Attribute it there, or `--log-level
        # DEBUG` would show `cli.level` as a default.
        for child, parent in inherited.items():
            parent_origin = origins.get(parent)
            if parent_origin is None:
                continue
            origins[child] = Origin(
                kind=parent_origin.kind,
                location=f"inherited from {parent} ({parent_origin.location})",
                precedence=parent_origin.precedence,
            )

        self._origins[fragment_type] = origins

        return fragment_type(**merged)

    # -- Phase 3: access --------------------------------------------------

    def get(self, fragment_type: type[_T]) -> _T:
        """
        Get the built instance of a declared ConfigPart type.

        Resolves first if that has not happened yet, so a host that never
        calls resolve() explicitly still gets a consistent view.

        Raises:
            KeyError: If the type was never declared.
        """
        if not self._resolved:
            self.resolve()
        if fragment_type not in self._fragments:
            raise KeyError(
                f"Fragment type {fragment_type.__name__} was never declared; "
                f"declared: "
                f"{', '.join(t.__name__ for t in self._declared) or '(none)'}"
            )
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
            KeyError: If the type was never declared, or the path is unknown.
        """
        origins = self.origins(fragment_type)
        if path not in origins:
            raise KeyError(f"No origin recorded for {fragment_type.__name__}.{path}")
        return origins[path]

    def origins(self, fragment_type: type[ConfigPart]) -> dict[str, Origin]:
        """Every recorded origin for a declared ConfigPart, keyed by path.

        Resolves first if that has not happened yet, matching `get()`.
        """
        if not self._resolved:
            self.resolve()
        if fragment_type not in self._origins:
            raise KeyError(f"Fragment type {fragment_type.__name__} was never declared")
        return dict(self._origins[fragment_type])

    def explain(self, fragment_type: type[ConfigPart]) -> str:
        """
        Render a table of every field's value and where it came from.

        Intended for `--debug-config` style output: the whole point of merging
        sources is that the winner is not obvious from any single one of them.
        """
        instance = self.get(fragment_type)
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

        This is called during resolve() BEFORE the instance
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

        Each field's value is handed to an :class:`AddoptsSource`, which parses
        it as command-line arguments at its own precedence -- above files and
        the environment, below arguments the user actually typed.

        Also validates that no bootstrap_only fields are being set via addopts.

        Args:
            fragment_type: ConfigPart class being registered
            data: Merged data from all sources

        Raises:
            ValueError: If addopts tries to set a bootstrap_only field
        """
        part_fields = fields_of(fragment_type, recurse=False)

        bootstrap_only_fields = {
            f.name for f in part_fields if has_marker(f, BootstrapOnlyMarker)
        }

        for field in part_fields:
            marker = marker_of(field, AddoptsMarker)
            if marker is None:
                continue

            value = data.get(field.name)
            if not value or not isinstance(value, str | list):
                continue

            source = self._ensure_addopts_source(marker.precedence)
            tokens = source.extend(value)
            _reject_bootstrap_only(tokens, bootstrap_only_fields)

    def _ensure_addopts_source(self, precedence: int) -> AddoptsSource:
        """The addopts source, created on first use at ``precedence``.

        Created lazily so that a configuration with no ``addopts_field`` never
        grows a source it has nothing to put in, and so the precedence the
        marker asks for is the precedence the source gets.
        """
        from ._sources import AddoptsSource

        if self._addopts_source is None:
            # add_source registers every already-declared type with it and
            # keeps the ladder sorted.
            self.add_source(AddoptsSource(precedence=precedence))
            assert self._addopts_source is not None
        return self._addopts_source


def _reject_bootstrap_only(tokens: list[str], bootstrap_only: set[str]) -> None:
    """Refuse addopts that try to set a field marked ``bootstrap_only``.

    By the time addopts are read, the decisions such a field drives -- which
    config file to open, above all -- have already been made, so honouring it
    here would silently do nothing.
    """
    for token in tokens:
        if not token.startswith("--"):
            continue
        name = token[2:].split("=")[0].replace("-", "_")
        if name in bootstrap_only:
            raise ValueError(
                f"Cannot set bootstrap-only field '{name}' via addopts. "
                f"Field '{name}' must be set via CLI arguments, not in "
                f"config file addopts."
            )


class UnknownConfigKeyWarning(UserWarning):
    """A source supplied a key the ConfigPart does not declare."""


def _drop_unknown_keys(
    fragment_type: type[ConfigPart],
    data: dict[str, Any],
) -> dict[str, Any]:
    """Drop keys the ConfigPart does not declare, at any depth, warning once.

    A typo in a nested table is the same user error as a typo at the top level
    and gets the same treatment. Letting it through instead reached the
    SubConfig constructor, which -- correctly, for a programming error --
    raised ``TypeError`` and took the whole load down.
    """
    unknown: list[str] = []
    result = _prune(fragment_type, data, prefix=(), unknown=unknown)
    if unknown:
        warnings.warn(
            f"Unknown config option(s) for {fragment_type.__name__}: "
            f"{', '.join(sorted(unknown))}",
            UnknownConfigKeyWarning,
            stacklevel=4,
        )
    return result


def _prune(
    cls: type[Any],
    data: dict[str, Any],
    *,
    prefix: tuple[str, ...],
    unknown: list[str],
) -> dict[str, Any]:
    """Recursive worker for :func:`_drop_unknown_keys`."""
    known = {field.name: field for field in fields_of(cls, recurse=False)}

    result: dict[str, Any] = {}
    for key, value in data.items():
        field = known.get(key)
        if field is None:
            unknown.append(".".join((*prefix, key)))
            continue
        if field.is_sub_config and isinstance(value, dict):
            value = _prune(field.type, value, prefix=(*prefix, key), unknown=unknown)
        result[key] = value
    return result


def _build_nested_subconfigs(
    cls: type[ConfigPart] | type[SubConfig],
    data: dict[str, Any],
    *,
    prefix: tuple[str, ...] = (),
    inherited: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Recursively convert nested dicts to SubConfig instances.

    For each field annotated as a SubConfig type, if the value is a dict,
    convert it to the appropriate SubConfig instance.

    Also handles parent-to-child cascade: if the parent has a field with
    the same name as a SubConfig field (e.g., parent.level), that value
    cascades to children that don't explicitly set it.

    Args:
        prefix: Dotted path of ``cls`` within the root ConfigPart.
        inherited: Optional out-parameter, filled with
            ``{child_dotted: parent_dotted}`` for every cascaded value, so the
            caller can attribute those values to where the parent got them
            rather than to the child's own default.
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
        child_prefix = (*prefix, field.name)

        if not isinstance(value, dict):
            if value is not None and field.name in result:
                # Already an instance (or something else the caller supplied).
                continue
            value = {}

        cascaded = _apply_cascade(cascade_values, sub_type, value)
        if inherited is not None:
            for name in cascaded.keys() - value.keys():
                inherited[".".join((*child_prefix, name))] = ".".join((*prefix, name))

        # Merge: class defaults < cascaded parent values < explicit values
        merged_value = {**field_defaults(sub_type), **cascaded}
        merged_value = _build_nested_subconfigs(
            sub_type, merged_value, prefix=child_prefix, inherited=inherited
        )
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
