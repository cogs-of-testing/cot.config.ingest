"""The manager as the design describes it: build-order step 7.

Each class pins one rule from ``docs/design/lifecycle.md``,
``docs/design/sources.md`` or ``docs/design/diagnostics.md`` that the older
acceptance tests do not reach.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Annotated, Any

import pytest

from cot.config import (
    CLISource,
    ConfigDeclarationError,
    ConfigFileDiscoverySource,
    ConfigLifecycleError,
    ConfigManager,
    ConfigPart,
    ConfigUsageError,
    DeprecatedNameWarning,
    EnvSource,
    IniSource,
    MissingConfigError,
    Precedence,
    RuntimeMutationWarning,
    TomlSource,
    UnknownConfigKeyWarning,
    UnknownOverrideKeyWarning,
    bootstrap_only,
    config_source,
    formerly,
    injected_args,
    short,
)


class App(ConfigPart, prefix="app"):
    level: str = "WARNING"
    debug: bool = False


class TestNoTwoSourcesShareARung:
    """D22: a tie would be broken by insertion order, which I3 forbids."""

    def test_second_source_at_an_occupied_rung_is_refused(self, tmp_path: Path) -> None:
        manager = ConfigManager(sources=[TomlSource(tmp_path / "a.toml")])

        with pytest.raises(ConfigDeclarationError, match="precedence 15"):
            manager.add_source(IniSource(tmp_path / "b.ini"))

    def test_distinct_rungs_are_accepted(self, tmp_path: Path) -> None:
        ConfigManager(
            sources=[
                TomlSource(tmp_path / "a.toml"),
                IniSource(tmp_path / "b.ini", precedence=Precedence.FILE + 1),
            ]
        )

    def test_a_named_file_sits_above_discovery(self, tmp_path: Path) -> None:
        """D33: the default rungs of the two front ends do not collide."""
        (tmp_path / "pyproject.toml").write_text('[app]\nlevel = "DISCOVERED"\n')
        (tmp_path / "named.toml").write_text('[app]\nlevel = "NAMED"\n')

        class Loader(ConfigPart, prefix="loader"):
            config_file: Annotated[str | None, config_source] = None

        manager = ConfigManager(
            sources=[
                ConfigFileDiscoverySource(tmp_path),
                CLISource(["--config-file", "named.toml"], invocation_dir=tmp_path),
            ]
        )
        manager.declare(App)
        manager.declare(Loader)

        assert manager.get(App).level == "NAMED"
        assert manager.origin_of(App, "level").precedence == Precedence.NAMED_FILE


class TestDiscoveryDelegates:
    """D34: each discovered file keeps its own dialect and base directory."""

    def test_ini_found_by_discovery_is_converted(self, tmp_path: Path) -> None:
        (tmp_path / "tox.ini").write_text("[app]\ndebug = true\n")

        manager = ConfigManager(sources=[ConfigFileDiscoverySource(tmp_path)])
        manager.declare(App)

        assert manager.get(App).debug is True

    def test_nearest_file_wins(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        (tmp_path / "pyproject.toml").write_text('[app]\nlevel = "OUTER"\n')
        (inner / "pyproject.toml").write_text('[app]\nlevel = "INNER"\n')

        manager = ConfigManager(sources=[ConfigFileDiscoverySource(inner)])
        manager.declare(App)

        assert manager.get(App).level == "INNER"


class TestTheIteration:
    def test_discover_declares_a_root_named_in_configuration(
        self, tmp_path: Path
    ) -> None:
        """A config file may name a plugin, and the plugin declares a root."""

        class Plugin(ConfigPart, prefix="plugin"):
            colour: str = "plain"

        registry: dict[str, type[ConfigPart]] = {"fancy": Plugin}

        class Plugins(ConfigPart, prefix="host"):
            plugins: list[str] = []

            @classmethod
            def discover(cls, manager: ConfigManager) -> None:
                for name in manager.partial(cls).get("plugins", []):
                    manager.declare(registry[name])

        config = tmp_path / "app.toml"
        config.write_text('[host]\nplugins = ["fancy"]\n[plugin]\ncolour = "loud"\n')
        manager = ConfigManager(
            sources=[TomlSource(config), CLISource(["--colour", "bright"])]
        )
        manager.declare(Plugins)

        # --colour was not an option until the plugin was declared; the
        # iteration re-parses argv once it is.
        assert manager.get(Plugin).colour == "bright"

    def test_partial_is_a_dict_without_the_cascade(self, tmp_path: Path) -> None:
        seen: list[dict[str, Any]] = []

        class Peek(ConfigPart, prefix="peek"):
            level: str = "WARNING"

            @classmethod
            def discover(cls, manager: ConfigManager) -> None:
                seen.append(manager.partial(cls))

        manager = ConfigManager(sources=[CLISource(["--level", "DEBUG"])])
        manager.declare(Peek)
        manager.resolve()

        assert seen[0] == {}  # the first iteration has read nothing yet
        assert seen[-1] == {"level": "DEBUG"}

    def test_a_set_that_never_settles_is_a_lifecycle_error(self) -> None:
        counter = iter(range(1000))

        class Grows(ConfigPart, prefix="grows"):
            @classmethod
            def discover(cls, manager: ConfigManager) -> None:
                n = next(counter)
                manager.declare(type(f"Made{n}", (ConfigPart,), {}, prefix=f"made{n}"))

        manager = ConfigManager()
        manager.declare(Grows)

        with pytest.raises(ConfigLifecycleError, match="did not settle"):
            manager.resolve()

    def test_declaring_after_resolve_is_refused(self) -> None:
        manager = ConfigManager()
        manager.declare(App)
        manager.resolve()

        with pytest.raises(ConfigLifecycleError, match="frozen"):
            manager.add_source(EnvSource())


class TestInjectedArguments:
    class Opts(ConfigPart, prefix="app"):
        addopts: Annotated[str, injected_args] = ""
        config_file: Annotated[str | None, config_source, bootstrap_only] = None
        level: str = "WARNING"

    def test_bootstrap_only_is_refused_by_path_not_spelling(
        self, tmp_path: Path
    ) -> None:
        """The ``-o`` spelling of a bootstrap_only field is the same field."""
        config = tmp_path / "app.toml"
        config.write_text('[app]\naddopts = "-o config_file=x.toml"\n')

        manager = ConfigManager(sources=[TomlSource(config), CLISource([])])
        manager.declare(self.Opts)

        with pytest.raises(ConfigUsageError, match="bootstrap_only"):
            manager.resolve()

    def test_every_layer_contributes_and_the_later_rung_wins(
        self, tmp_path: Path
    ) -> None:
        class EnvOpts(ConfigPart, prefix="app", from_env=True):
            addopts: Annotated[str, injected_args] = ""
            level: str = "WARNING"
            debug: bool = False

        config = tmp_path / "app.toml"
        config.write_text('[app]\naddopts = "--level FROM_FILE --debug"\n')

        manager = ConfigManager(
            sources=[
                TomlSource(config),
                EnvSource(environ={"APP_ADDOPTS": "--level FROM_ENV"}),
                CLISource([]),
            ]
        )
        manager.declare(EnvOpts)
        config_ = manager.get(EnvOpts)

        assert config_.level == "FROM_ENV"
        assert config_.debug is True


class TestDiagnostics:
    def test_unknown_override_key_is_its_own_warning(self) -> None:
        manager = ConfigManager(sources=[CLISource(["-o", "nonsense=1"])])
        manager.declare(App)

        with pytest.warns(UnknownOverrideKeyWarning, match="nonsense"):
            manager.resolve()

    def test_unknown_keys_across_roots_are_one_warning(self, tmp_path: Path) -> None:
        config = tmp_path / "app.toml"
        config.write_text("[app]\nlevl = 1\nlevle = 2\n")
        manager = ConfigManager(sources=[TomlSource(config)])
        manager.declare(App)

        with pytest.warns(UnknownConfigKeyWarning) as caught:
            manager.resolve()

        assert len(caught) == 1
        assert "levl" in str(caught[0].message)
        assert "levle" in str(caught[0].message)

    def test_a_deprecated_alias_reaches_the_field_and_warns(
        self, tmp_path: Path
    ) -> None:
        class Renamed(ConfigPart, prefix="app"):
            version_file: Annotated[str | None, formerly("write_to")] = None

        config = tmp_path / "app.toml"
        config.write_text('[app]\nwrite_to = "v.txt"\n')
        manager = ConfigManager(sources=[TomlSource(config)])
        manager.declare(Renamed)

        with pytest.warns(DeprecatedNameWarning, match="version_file"):
            assert manager.get(Renamed).version_file == "v.txt"

    def test_a_missing_named_file_names_the_field(self, tmp_path: Path) -> None:
        class Loader(ConfigPart, prefix="loader"):
            config_file: Annotated[str | None, config_source] = None

        manager = ConfigManager(
            sources=[CLISource(["--config-file", "gone.toml"], invocation_dir=tmp_path)]
        )
        manager.declare(Loader)

        with pytest.raises(ConfigUsageError, match=r"gone\.toml.*config_file"):
            manager.resolve()

    def test_a_reserved_short_is_refused_at_declare(self) -> None:
        class Clash(ConfigPart):
            help_me: Annotated[bool, short("h")] = False

        with pytest.raises(ConfigDeclarationError, match="reserved for help"):
            ConfigManager().declare(Clash)


class TestProvenance:
    def test_explain_shows_what_the_winner_beat(self, tmp_path: Path) -> None:
        config = tmp_path / "app.toml"
        config.write_text('[app]\nlevel = "FROM_FILE"\n')
        manager = ConfigManager(
            sources=[TomlSource(config), CLISource(["--level", "FROM_CLI"])]
        )
        manager.declare(App)

        report = manager.explain(App)

        assert "cli:--level (over file:" in report

    def test_override_reports_as_override(self) -> None:
        manager = ConfigManager(sources=[CLISource(["--level", "A", "-o", "level=B"])])
        manager.declare(App)

        assert manager.get(App).level == "B"
        origin = manager.origin_of(App, "level")
        assert (origin.kind, origin.location) == ("override", "-o level")


class TestTheRuntimeLayer:
    def test_a_runtime_write_wins_and_warns(self) -> None:
        manager = ConfigManager(sources=[CLISource(["--level", "DEBUG"])])
        manager.declare(App)
        manager.resolve()

        with pytest.warns(RuntimeMutationWarning, match="pager"):
            manager.set(App, "level", "ERROR", writer="pager")

        assert manager.get(App).level == "ERROR"
        assert str(manager.origin_of(App, "level")) == "runtime:pager"

    def test_a_write_to_a_feedback_field_is_refused(self) -> None:
        class Loader(ConfigPart, prefix="loader"):
            config_file: Annotated[str | None, config_source] = None

        manager = ConfigManager()
        manager.declare(Loader)
        manager.resolve()

        with pytest.raises(ConfigUsageError, match="adds a source"):
            manager.set(Loader, "config_file", "x.toml", writer="me")


def test_nothing_warns_on_correct_configuration(tmp_path: Path) -> None:
    """I8: a warning that fires on correct configuration is a defect."""
    config = tmp_path / "app.toml"
    config.write_text('[app]\nlevel = "INFO"\n')
    manager = ConfigManager(
        sources=[TomlSource(config), EnvSource("X"), CLISource(["tests/"])]
    )
    manager.declare(App)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        manager.resolve()


class TestFragmentLifetime:
    """D32: the fragment originates a context manager; the caller enters it."""

    def test_instance_is_handed_over_unentered(self) -> None:
        from collections.abc import Iterator
        from contextlib import contextmanager

        events: list[str] = []

        class Timing(ConfigPart, prefix="timing"):
            report: bool = False

            @contextmanager
            def instance(self) -> Iterator[object | None]:
                if not self.report:
                    yield None
                    return
                events.append("enter")
                try:
                    yield "reporter"
                finally:
                    events.append("exit")

        manager = ConfigManager(sources=[CLISource(["--report"])])
        manager.declare(Timing)

        context = manager.instance(Timing)
        assert events == []
        with context as reporter:
            assert reporter == "reporter"
        assert events == ["enter", "exit"]

    def test_a_root_without_instance_is_a_usage_error(self) -> None:
        manager = ConfigManager()
        manager.declare(App)

        with pytest.raises(ConfigUsageError, match="no instance"):
            manager.instance(App)


class TestARejectedResolution:
    def test_every_later_access_sees_the_same_error(self, tmp_path: Path) -> None:
        class Needs(ConfigPart, prefix="needs"):
            name: str

        manager = ConfigManager()
        manager.declare(Needs)

        with pytest.raises(MissingConfigError, match="name"):
            manager.get(Needs)
        with pytest.raises(MissingConfigError, match="name"):
            manager.get(Needs)

    def test_a_usage_error_during_the_iteration_leaves_nothing_frozen(self) -> None:
        manager = ConfigManager(sources=[CLISource(["--level"])])
        manager.declare(App)

        with pytest.raises(ConfigUsageError, match="--level"):
            manager.resolve()
        assert manager.resolved is False
