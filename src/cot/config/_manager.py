"""declare, resolve, get: the pipeline, run to a fixpoint.

The manager holds two things across resolution, the **base sources** the
application constructed and the **declared set**, and recomputes everything
else on every iteration: the store, the files a ``config_source`` field named,
the sources a ``discover()`` hook added, and the injected arguments. An
iteration that grows neither the declared set nor the derived sources is the
last; its store is projected once, and only its diagnostics are reported.

Each step runs for every declared root before the next begins, so the order
roots were declared in, and the order sources were added in, cannot change the
result (I3).
"""

from __future__ import annotations

import shlex
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from ._annotations import BootstrapOnlyMarker, ConfigSourceMarker, InjectedArgsMarker
from ._bases import ConfigPart
from ._diagnostics import (
    ConfigDeclarationError,
    ConfigError,
    ConfigLifecycleError,
    ConfigUsageError,
    DeprecatedNameWarning,
    Diagnostics,
    RuntimeMutationWarning,
    UnknownConfigKeyWarning,
    UnknownOverrideKeyWarning,
)
from ._fields import (
    FieldInfo,
    check_declaration,
    fields_of,
    has_marker,
    marker_of,
)
from ._help import format_help as _format_help
from ._index import SpellingIndex
from ._origins import Origin
from ._projection import Projection, check_cascade_targets, project
from ._reading import (
    BindingSource,
    CLISource,
    ConfigSource,
    InjectedArgsSource,
    OverrideSource,
    RuntimeSource,
    _ArgvSource,
    source_for_file,
)
from ._store import FailedValue, LayeredStore, LayeredValue, Reading, Unmatched

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

_T = TypeVar("_T", bound=ConfigPart)

Phase = Literal["declaring", "resolving", "projecting", "resolved"]


class _Iteration:
    """What one pass over the sources produced. Discarded unless it is the last."""

    def __init__(self, strict: bool) -> None:
        self.store = LayeredStore()
        self.diagnostics = Diagnostics(strict=strict)
        self.sources: list[ConfigSource] = []
        self.derived: list[ConfigSource] = []


class ConfigManager:
    """Declares roots, resolves them against sources, and hands out instances.

    Example::

        manager = ConfigManager(sources=[
            ConfigFileDiscoverySource(Path.cwd()),
            EnvSource("APP"),
            CLISource(sys.argv[1:]),
        ])
        manager.declare(AppConfig)
        config = manager.get(AppConfig)
    """

    #: How many iterations resolution may take before the configuration is
    #: judged not to settle. Each one must declare a root or derive a source.
    MAX_ITERATIONS = 16

    def __init__(
        self,
        sources: Sequence[ConfigSource] = (),
        *,
        strict: bool = False,
    ) -> None:
        """
        Args:
            sources: The base sources. Every resolution iteration starts from
                these; no two may share a precedence.
            strict: Raise where the library would otherwise warn, for the
                warnings that report input.
        """
        self._strict = strict
        self._base: list[ConfigSource] = []
        self._declared: list[type[ConfigPart]] = []
        self._index = SpellingIndex()
        self._phase: Phase = "declaring"
        self._runtime = RuntimeSource()

        self._current: _Iteration | None = None
        self._previous: _Iteration | None = None
        self._final: _Iteration | None = None
        self._projections: dict[type[ConfigPart], Projection[Any]] = {}
        self._failure: ConfigError | None = None

        for source in sources:
            self.add_source(source)

    # -- declaration -------------------------------------------------------

    def declare(self, root: type[ConfigPart]) -> None:
        """Record a root. Nothing is loaded.

        Declaring a root already declared is a no-op, which is what lets a
        ``discover()`` hook run on every iteration.

        Raises:
            ConfigLifecycleError: after ``resolve()``, or during projection.
            ConfigDeclarationError: if the class is one the library cannot
                honour as declared.
            ConfigCollisionError: if it claims a spelling another declared root
                claims and means something else by it.
        """
        if root in self._declared:
            return
        if self._phase in ("projecting", "resolved"):
            raise ConfigLifecycleError(
                f"Cannot declare {root.__name__} after resolve(); "
                f"configuration is already frozen"
            )
        check_declaration(root)
        check_cascade_targets(root)
        _check_reserved_shorts(root)
        self._index.add(root)
        self._declared.append(root)

    def add_source(self, source: ConfigSource) -> None:
        """Add a base source, or, from a ``discover()`` hook, a derived one.

        A derived source lasts one iteration: the next one asks the hook again.

        Raises:
            ConfigDeclarationError: if another source holds that precedence.
            ConfigLifecycleError: after ``resolve()``.
        """
        if self._phase == "resolving" and self._current is not None:
            _check_rung(source, self._current.sources)
            self._current.sources.append(source)
            self._current.derived.append(source)
            return
        if self._phase != "declaring":
            raise ConfigLifecycleError(
                f"Cannot add {_describe(source)} after resolve(); "
                f"configuration is already frozen"
            )
        _check_rung(source, self._base)
        self._base.append(source)

    @property
    def strict(self) -> bool:
        """Whether input the library would warn about is fatal instead."""
        return self._strict

    @property
    def index(self) -> SpellingIndex:
        """Every spelling of every declared root, resolvable back to its field."""
        return self._index

    @property
    def declared(self) -> list[type[ConfigPart]]:
        """The roots declared so far, in declaration order."""
        return list(self._declared)

    @property
    def sources(self) -> list[ConfigSource]:
        """Every source the last resolution read, lowest rung first.

        Before resolution, the base sources.
        """
        held = self._final.sources if self._final is not None else self._base
        return sorted(held, key=lambda source: source.precedence)

    # -- resolution --------------------------------------------------------

    @property
    def resolved(self) -> bool:
        """Whether resolve() has run and the configuration is frozen."""
        return self._phase == "resolved"

    def resolve(self) -> None:
        """Run the iteration to a fixpoint, then build every declared root.

        Idempotent, and triggered by the first ``get()``. Calling it explicitly
        is how a host pins the moment configuration freezes.

        Raises:
            ConfigLifecycleError: if the declared set or the derived sources
                keep growing past :attr:`MAX_ITERATIONS`.
        """
        if self._phase != "declaring":
            return
        self._phase = "resolving"
        try:
            self._final = self._iterate_to_fixpoint()
        except BaseException:
            # Nothing froze: the input was rejected, and the application may
            # fix it and resolve again.
            self._phase = "declaring"
            raise
        finally:
            self._current = None
            self._previous = None
        self._phase = "projecting"
        try:
            self._project_all(self._final.diagnostics)
        finally:
            self._phase = "resolved"
        # One report for the whole resolution: the order roots are visited is
        # not something the user controls, so a per-root stream would come out
        # in an order nobody can predict or diff.
        try:
            self._final.diagnostics.emit()
        except ConfigError as error:
            # Every later access sees the same rejection, rather than a
            # half-built configuration or a KeyError for a root that failed.
            self._failure = error
            raise

    def _iterate_to_fixpoint(self) -> _Iteration:
        for _ in range(self.MAX_ITERATIONS):
            declared_before = len(self._declared)
            iteration = self._iterate()
            previous = self._previous
            settled = len(self._declared) == declared_before and (
                previous is not None
                and all(source in previous.derived for source in iteration.derived)
            )
            self._previous = iteration
            if settled or (previous is None and self._settles_at_once(iteration)):
                return iteration
        raise ConfigLifecycleError(
            f"Resolution did not settle after {self.MAX_ITERATIONS} iterations: "
            f"the declared roots ({_names(self._declared)}) or the derived "
            f"sources ({_names_of_sources(self._previous)}) kept growing"
        )

    def _settles_at_once(self, iteration: _Iteration) -> bool:
        """A first iteration that declared nothing and derived nothing is final.

        The next one would start from the same base with the same roots and
        read exactly the same thing.
        """
        return not iteration.derived and not any(
            hasattr(root, "discover") for root in self._declared
        )

    def _iterate(self) -> _Iteration:
        iteration = _Iteration(self._strict)
        iteration.sources = list(self._base)
        self._current = iteration

        # 1. every binding source learns every option declared so far
        for source in iteration.sources:
            if isinstance(source, BindingSource):
                source.bind(self._index.all_specs())

        # 2. discover(), reading the previous iteration's store
        for root in list(self._declared):
            discover = getattr(root, "discover", None)
            if callable(discover):
                discover(self)

        # 3. every source into a fresh store
        unmatched: list[tuple[ConfigSource, Unmatched]] = []
        argv: list[_ArgvSource] = []
        for source in iteration.sources:
            self._load(source, iteration, unmatched)
            if isinstance(source, _ArgvSource):
                argv.append(source)

        # 4. the files config_source fields name, until they name no new one
        self._load_named_files(iteration, unmatched)

        # 5. injected arguments, then -o from every argv source
        argv.extend(self._load_injected(iteration, unmatched))
        if argv and not any(isinstance(s, OverrideSource) for s in iteration.sources):
            overrides = OverrideSource(sources=argv)
            _check_rung(overrides, iteration.sources)
            iteration.sources.append(overrides)
            self._load(overrides, iteration, unmatched)

        if self._runtime.writes:
            iteration.sources.append(self._runtime)
            self._load(self._runtime, iteration, unmatched)

        self._report_unmatched(unmatched, iteration.diagnostics)
        return iteration

    def _load(
        self,
        source: ConfigSource,
        iteration: _Iteration,
        unmatched: list[tuple[ConfigSource, Unmatched]],
        readings: Iterable[Reading | Unmatched] | None = None,
    ) -> None:
        """Read one source into the store, building each reading's origin.

        A source says where a value came from; the manager turns that into an
        origin from the source's kind and rung.
        """
        delegates = getattr(source, "delegates", None)
        if readings is None and callable(delegates):
            for delegate in delegates():
                self._load(delegate, iteration, unmatched)
            return

        kind = source.kind
        base_dir = source.base_dir
        dialect = source.dialect
        items = source.read(self._index) if readings is None else readings
        for item in items:
            if isinstance(item, Unmatched):
                unmatched.append((source, item))
                continue
            origin = Origin(
                kind=kind,
                location=item.location,
                precedence=source.precedence,
                base_dir=base_dir,
            )
            iteration.store.add(item, origin, item.dialect or dialect)
            if item.alias is not None:
                current = _field_at(item.root, item.path)
                iteration.diagnostics.add(
                    DeprecatedNameWarning,
                    f"{item.alias} is a deprecated name for "
                    f"{item.root.__name__}.{current.dotted}, used at "
                    f"{item.location}; spell it "
                    f"{_flat_of(self._index, item.root, item.path)} instead",
                )

    def _load_named_files(
        self, iteration: _Iteration, unmatched: list[tuple[ConfigSource, Unmatched]]
    ) -> None:
        """Turn every ``config_source`` winner into a source, at any depth.

        Repeated until no new file is named, because a named file may itself
        name another.
        """
        named: dict[Path, ConfigSource] = {}
        while True:
            found = False
            for root, info, marker in self._marked(ConfigSourceMarker):
                path = self._named_path(iteration, root, info)
                if path is None or path in named:
                    continue
                try:
                    source = source_for_file(path, precedence=marker.precedence)
                except ConfigUsageError as error:
                    iteration.diagnostics.add(
                        ConfigUsageError, f"{error} (named by {info.dotted})"
                    )
                    continue
                _check_rung(source, iteration.sources)
                named[path] = source
                iteration.sources.append(source)
                iteration.derived.append(source)
                self._load(source, iteration, unmatched)
                found = True
            if not found:
                return

    def _named_path(
        self, iteration: _Iteration, root: type[ConfigPart], info: FieldInfo
    ) -> Path | None:
        won = iteration.store.winner(root, info.path)
        if not isinstance(won, LayeredValue) or won.value is None:
            return None
        path = Path(won.value)
        if not path.is_absolute():
            path = self._invocation_dir() / path
        if not path.exists():
            iteration.diagnostics.add(
                ConfigUsageError,
                f"Config file not found: {path}, named by {info.dotted} ({won.origin})",
            )
            return None
        return path

    def _invocation_dir(self) -> Path:
        for source in self._base:
            if isinstance(source, CLISource):
                return source.invocation_dir
        return Path.cwd()

    def _load_injected(
        self, iteration: _Iteration, unmatched: list[tuple[ConfigSource, Unmatched]]
    ) -> list[InjectedArgsSource]:
        """Build one injected source per rung the markers ask for, and load it.

        Every layer of an ``injected_args`` field contributes, not only the
        winner: this is the one place a value accumulates. Contributions are
        ordered by the rung of the source each came from, so the later one wins
        without depending on the order anything was added.
        """
        by_rung: dict[int, list[tuple[int, str, list[str]]]] = {}
        for root, info, marker in self._marked(InjectedArgsMarker):
            for layer in iteration.store.layers(root, info.path):
                if isinstance(layer, FailedValue):
                    continue
                tokens = _tokens_of(layer.value)
                if tokens:
                    by_rung.setdefault(marker.precedence, []).append(
                        (layer.origin.precedence, layer.origin.location, tokens)
                    )

        made: list[InjectedArgsSource] = []
        for precedence, contributions in sorted(by_rung.items()):
            source = InjectedArgsSource(precedence=precedence)
            for _, contributor, tokens in sorted(contributions, key=lambda c: c[0]):
                source.contribute(contributor, tokens)
            _check_rung(source, iteration.sources)
            iteration.sources.append(source)
            readings = list(source.read(self._index))
            self._refuse_bootstrap_only(source, readings)
            self._load(source, iteration, unmatched, readings)
            made.append(source)
        return made

    def _refuse_bootstrap_only(
        self, source: InjectedArgsSource, readings: Sequence[Reading | Unmatched]
    ) -> None:
        """Refuse an injected value for a field whose decisions are already made.

        Judged on paths, through the index, never on token strings: an option,
        its short form, its ``--no-`` form and an ``-o`` pair are all the same
        field.
        """
        targets = [
            (item.root, item.path, item.location)
            for item in readings
            if isinstance(item, Reading)
        ]
        for key, _value, _label in source.overrides:
            targets.extend(
                (target.root, target.path, f"-o {key}")
                for target in self._index.flat(key)
            )
        for root, path, location in targets:
            info = _field_at(root, path)
            if has_marker(info, BootstrapOnlyMarker):
                raise ConfigUsageError(
                    f"{root.__name__}.{info.dotted} cannot be set from injected "
                    f"arguments ({location}): it is bootstrap_only, and the "
                    f"decisions it drives, which config file to open above all, "
                    f"have already been made. Pass it on the command line instead."
                )

    def _marked(
        self, marker_type: type[Any]
    ) -> list[tuple[type[ConfigPart], FieldInfo, Any]]:
        """Every field carrying ``marker_type``, at any depth, in every root."""
        found: list[tuple[type[ConfigPart], FieldInfo, Any]] = []
        for root in self._declared:
            for info in fields_of(root):
                marker = marker_of(info, marker_type)
                if marker is not None and not info.is_nested:
                    found.append((root, info, marker))
        return found

    def _report_unmatched(
        self,
        unmatched: Sequence[tuple[ConfigSource, Unmatched]],
        diagnostics: Diagnostics,
    ) -> None:
        for source, item in unmatched:
            if isinstance(source, OverrideSource):
                diagnostics.add(
                    UnknownOverrideKeyWarning,
                    f"-o {item.spelling} addresses no field; searched "
                    f"{_names(self._declared) or '(no roots)'}",
                )
            else:
                diagnostics.add(
                    UnknownConfigKeyWarning,
                    f"Unknown config option {item.spelling} in {item.location}",
                )

    def _project_all(self, diagnostics: Diagnostics) -> None:
        assert self._final is not None
        store = self._final.store
        projections: dict[type[ConfigPart], Projection[Any]] = {}
        for root in self._declared:
            store.report_failures(root, diagnostics)
            try:
                projections[root] = project(root, store)
            except ConfigError as error:
                diagnostics.add(type(error), str(error))
        self._projections = projections

    # -- access ------------------------------------------------------------

    def get(self, root: type[_T]) -> _T:
        """The built instance of a declared root, resolving first if needed.

        Raises:
            KeyError: if the root was never declared.
        """
        return self._projection(root).instance  # type: ignore[no-any-return]

    def _projection(self, root: type[ConfigPart]) -> Projection[Any]:
        if self._phase == "declaring":
            self.resolve()
        if self._failure is not None:
            raise self._failure
        if root not in self._projections:
            raise KeyError(
                f"{root.__name__} was never declared; declared: "
                f"{_names(self._declared) or '(none)'}"
            )
        return self._projections[root]

    def partial(self, root: type[ConfigPart]) -> dict[str, Any]:
        """The winner per path so far, for a ``discover()`` hook to read.

        Converted, but with no cascade, no assembly and no required-field
        check, because the iteration is not finished. Keyed by dotted path.
        """
        store = self._previous.store if self._previous is not None else None
        if self._phase != "resolving" and self._final is not None:
            store = self._final.store
        if store is None:
            return {}
        values: dict[str, Any] = {}
        for info in fields_of(root):
            won = store.winner(root, info.path)
            if isinstance(won, LayeredValue):
                values[info.dotted] = won.value
        return values

    def layers(
        self, root: type[ConfigPart], path: str
    ) -> tuple[LayeredValue | FailedValue, ...]:
        """Every source that supplied ``path``, lowest rung first."""
        self._projection(root)
        assert self._final is not None
        return self._final.store.layers(root, tuple(path.split(".")))

    def origin_of(self, root: type[ConfigPart], path: str) -> Origin:
        """Where a field's final value came from.

        Raises:
            KeyError: if the root was never declared, or the path is unknown.
        """
        origins = self._projection(root).origins
        if path not in origins:
            raise KeyError(f"No origin recorded for {root.__name__}.{path}")
        origin: Origin = origins[path]
        return origin

    def origins(self, root: type[ConfigPart]) -> dict[str, Origin]:
        """Every recorded origin for a declared root, keyed by dotted path."""
        return dict(self._projection(root).origins)

    def explain(self, root: type[ConfigPart]) -> str:
        """Every field's value, where it came from, and what it beat.

        The ``--debug-config`` output: the point of merging sources is that the
        winner is not obvious from any one of them.
        """
        projection = self._projection(root)
        assert self._final is not None
        store = self._final.store

        rows: list[tuple[str, str, str]] = []
        for info in fields_of(root):
            if info.is_nested:
                continue
            value: Any = projection.instance
            for segment in info.path:
                value = getattr(value, segment, None)
            origin = projection.origins.get(info.dotted)
            shown = str(origin) if origin is not None else "unset"
            beaten = store.layers(root, info.path)[:-1]
            if origin is not None and origin.kind != "default" and beaten:
                over = ", ".join(str(layer.origin) for layer in beaten)
                shown += f" (over {over})"
            rows.append((info.dotted, repr(value), shown))

        if not rows:
            return f"{root.__name__}: no fields\n"

        widths = [max(len(row[column]) for row in rows) for column in range(2)]
        header = f"{'field'.ljust(widths[0])}  {'value'.ljust(widths[1])}  origin"
        lines = [f"{root.__name__}:", header, "-" * len(header)]
        lines.extend(
            f"{name.ljust(widths[0])}  {value.ljust(widths[1])}  {origin}".rstrip()
            for name, value, origin in rows
        )
        return "\n".join(lines) + "\n"

    def format_help(self, *, prog: str | None = None) -> str:
        """Every declared option, rendered from specs. Never prints."""
        return _format_help(self._index.all_specs(), prog=prog)

    def help_requested(self) -> bool:
        """Whether ``-h`` or ``--help`` was among the arguments read."""
        held = self._final.sources if self._final is not None else self._base
        return any(
            isinstance(source, _ArgvSource) and source.help_requested for source in held
        )

    # -- the runtime layer -------------------------------------------------

    def set(
        self, root: type[ConfigPart], path: str, value: Any, *, writer: str
    ) -> None:
        """Write a value after resolution, at the top of the ladder.

        The fragment is rebuilt from the store with the write on top; the
        iteration is not re-run, so a field that would add a source cannot be
        written.

        Raises:
            ConfigUsageError: for a ``config_source`` or ``injected_args`` field.
            KeyError: for a root never declared or a path it does not have.
        """
        self._projection(root)
        assert self._final is not None
        segments = tuple(path.split("."))
        info = _field_at(root, segments)
        for marker in (ConfigSourceMarker, InjectedArgsMarker):
            if has_marker(info, marker):
                raise ConfigUsageError(
                    f"{root.__name__}.{path} cannot be set at runtime: it adds a "
                    f"source, and sources are closed once resolve() has run"
                )

        self._runtime.set(root, segments, value, writer)
        if self._runtime not in self._final.sources:
            self._final.sources.append(self._runtime)
        origin = Origin(
            kind="runtime",
            location=writer,
            precedence=self._runtime.precedence,
        )
        reading = Reading(root=root, path=segments, raw=value, location=origin.location)
        self._final.store.add(reading, origin, self._runtime.dialect)

        diagnostics = Diagnostics(strict=self._strict)
        diagnostics.add(
            RuntimeMutationWarning,
            f"{root.__name__}.{path} set by {writer} after resolve; "
            f"the fragment is rebuilt",
        )
        self._final.store.report_failures(root, diagnostics)
        diagnostics.emit()
        self._projections[root] = project(root, self._final.store)

    # -- fragment lifetime -------------------------------------------------

    def instance(self, root: type[ConfigPart]) -> AbstractContextManager[Any]:
        """The context manager the fragment originates, never entered here.

        Which scope it belongs to is the integration's to decide.

        Raises:
            ConfigUsageError: if the root defines no ``instance()``.
        """
        fragment = self.get(root)
        originate = getattr(fragment, "instance", None)
        if not callable(originate):
            raise ConfigUsageError(
                f"{root.__name__} originates no context manager: it defines no "
                f"instance() method"
            )
        context: AbstractContextManager[Any] = originate()
        return context


def _check_reserved_shorts(root: type[ConfigPart]) -> None:
    """Refuse a ``short()`` the parser keeps for itself, at ``declare()``."""
    from ._parser import RESERVED_SHORTS
    from ._specs import field_specs

    for spec in field_specs(root):
        for form in spec.cli:
            if form.short in RESERVED_SHORTS:
                purpose = "overrides" if form.short == "-o" else "help"
                raise ConfigDeclarationError(
                    f"{root.__name__}.{'.'.join(spec.path)} claims {form.short}, "
                    f"which is reserved for {purpose}. Pick another short()."
                )


def _check_rung(source: ConfigSource, held: Iterable[ConfigSource]) -> None:
    """Refuse a second source at an occupied rung (D22)."""
    for other in held:
        if other is source:
            raise ConfigDeclarationError(f"{_describe(source)} was added twice")
        if other.precedence == source.precedence:
            raise ConfigDeclarationError(
                f"{_describe(source)} and {_describe(other)} both sit at "
                f"precedence {source.precedence}; the result would depend on the "
                f"order they were added. Give one of them a distinct precedence="
            )


def _describe(source: ConfigSource) -> str:
    path = getattr(source, "path", None)
    name = type(source).__name__
    return f"{name}({path})" if path is not None else name


def _names(roots: Iterable[type[ConfigPart]]) -> str:
    return ", ".join(root.__name__ for root in roots)


def _names_of_sources(iteration: _Iteration | None) -> str:
    if iteration is None:
        return "none"
    return ", ".join(_describe(source) for source in iteration.derived) or "none"


def _field_at(root: type[ConfigPart], path: tuple[str, ...]) -> FieldInfo:
    for info in fields_of(root):
        if info.path == path:
            return info
    raise KeyError(f"{root.__name__} has no field {'.'.join(path)}")


def _flat_of(
    index: SpellingIndex, root: type[ConfigPart], path: tuple[str, ...]
) -> str:
    for spec in index.specs(root):
        if spec.path == path:
            return spec.flat
    return ".".join(path)


def _tokens_of(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list | tuple):
        return [str(token) for token in value]
    return [str(value)]


__all__ = ["ConfigManager"]
