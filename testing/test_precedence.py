"""The precedence ladder is the only thing that decides a winner.

``defaults < file < addopts < env < cli`` is a set of defaults, not a fixed
enum: every source takes ``precedence=``, and what these tests pin is that the
number is *honoured* -- no source is special-cased above the ladder, and
``addopts`` occupies a real rung of it rather than being spliced into argv.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Annotated

import pytest

from cot.config import (
    AddoptsSource,
    CLISource,
    ConfigManager,
    ConfigPart,
    EnvSource,
    Precedence,
    SubConfig,
    TomlSource,
    UnknownConfigKeyWarning,
    addopts_field,
    config_source,
)
from cot.config._annotations import AddoptsMarker


class Simple(ConfigPart, prefix="app"):
    level: str = "WARNING"


class WithAddopts(ConfigPart, prefix="app"):
    addopts: Annotated[str, addopts_field] = ""
    level: str = "WARNING"


def _toml(tmp_path: Path, body: str, name: str = "config.toml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body))
    return path


class TestLadderDefaults:
    """The documented ladder is what the sources actually default to."""

    def test_every_source_defaults_to_its_rung(self, tmp_path: Path) -> None:
        assert TomlSource(tmp_path / "x.toml").precedence == Precedence.FILE
        assert AddoptsSource().precedence == Precedence.ADDOPTS
        assert EnvSource().precedence == Precedence.ENV
        assert CLISource().precedence == Precedence.CLI

    def test_the_ladder_is_ordered(self) -> None:
        assert (
            Precedence.DEFAULTS
            < Precedence.FILE
            < Precedence.ADDOPTS
            < Precedence.ENV
            < Precedence.CLI
        )

    def test_addopts_marker_defaults_to_its_rung(self) -> None:
        assert AddoptsMarker().precedence == Precedence.ADDOPTS


class TestPrecedenceIsTheOnlyAuthority:
    """No source outranks the ladder by virtue of what it is."""

    def test_a_source_above_cli_beats_cli(self, tmp_path: Path) -> None:
        """A file declared above the CLI rung wins against a typed argument.

        The CLI used to be merged a second time after the precedence-ordered
        loop, which made its 25 decorative: nothing could outrank it.
        """
        config_file = _toml(tmp_path, '[app]\nlevel = "FROM_FILE"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=["--level", "FROM_CLI"], invocation_dir=tmp_path),
                TomlSource(config_file, precedence=Precedence.CLI + 1),
            ]
        )
        manager.declare(Simple)

        assert manager.get(Simple).level == "FROM_FILE"
        assert manager.origin_of(Simple, "level").kind == "file"

    def test_cli_still_wins_at_default_precedences(self, tmp_path: Path) -> None:
        config_file = _toml(tmp_path, '[app]\nlevel = "FROM_FILE"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=["--level", "FROM_CLI"], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(Simple)

        assert manager.get(Simple).level == "FROM_CLI"


class TestAddoptsIsASource:
    """addopts sits on the ladder instead of being spliced into argv."""

    def test_addopts_beats_the_file_that_carried_it(self, tmp_path: Path) -> None:
        config_file = _toml(
            tmp_path,
            """
            [app]
            level = "FROM_FILE"
            addopts = "--level FROM_ADDOPTS"
            """,
        )
        manager = ConfigManager(
            sources=[
                CLISource(args=[], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(WithAddopts)

        assert manager.get(WithAddopts).level == "FROM_ADDOPTS"

    def test_env_beats_addopts(self, tmp_path: Path) -> None:
        """env(20) outranks addopts(18) -- which argv splicing could not express."""
        config_file = _toml(tmp_path, '[app]\naddopts = "--level FROM_ADDOPTS"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=[], invocation_dir=tmp_path),
                TomlSource(config_file),
                EnvSource(environ={"APP_LEVEL": "FROM_ENV"}),
            ]
        )
        manager.declare(WithAddopts)

        assert manager.get(WithAddopts).level == "FROM_ENV"

    def test_typed_arguments_beat_addopts(self, tmp_path: Path) -> None:
        config_file = _toml(tmp_path, '[app]\naddopts = "--level FROM_ADDOPTS"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=["--level", "FROM_CLI"], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(WithAddopts)

        assert manager.get(WithAddopts).level == "FROM_CLI"

    def test_addopts_values_are_attributed_to_addopts(self, tmp_path: Path) -> None:
        """An option nobody typed is the hardest kind to debug; name it."""
        config_file = _toml(tmp_path, '[app]\naddopts = "--level FROM_ADDOPTS"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=[], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(WithAddopts)
        manager.resolve()

        origin = manager.origin_of(WithAddopts, "level")
        assert origin.kind == "addopts"
        assert "--level" in origin.location
        assert origin.precedence == Precedence.ADDOPTS

    def test_the_marker_precedence_is_the_sources_precedence(
        self, tmp_path: Path
    ) -> None:
        """`addopts_field` with a custom precedence actually moves the rung."""

        class LoudAddopts(ConfigPart, prefix="app"):
            addopts: Annotated[str, AddoptsMarker(Precedence.CLI + 5)] = ""
            level: str = "WARNING"

        config_file = _toml(tmp_path, '[app]\naddopts = "--level FROM_ADDOPTS"\n')

        manager = ConfigManager(
            sources=[
                CLISource(args=["--level", "FROM_CLI"], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(LoudAddopts)

        assert manager.get(LoudAddopts).level == "FROM_ADDOPTS"

    def test_no_addopts_source_without_an_addopts_field(self, tmp_path: Path) -> None:
        manager = ConfigManager(sources=[CLISource(args=[], invocation_dir=tmp_path)])
        manager.declare(Simple)
        manager.resolve()

        assert not any(isinstance(s, AddoptsSource) for s in manager.sources)

    def test_addopts_accumulate_across_parts(self, tmp_path: Path) -> None:
        """Two parts each contributing addopts both reach the parser.

        ``name_prefix`` keeps the two ``level`` fields from claiming the same
        option -- without it they are genuinely the same ``--level``.
        """

        class Other(ConfigPart, prefix="other", name_prefix="other"):
            addopts: Annotated[str, addopts_field] = ""
            level: str = "WARNING"

        config_file = _toml(
            tmp_path,
            """
            [app]
            addopts = "--level FROM_APP"
            [other]
            addopts = "--other-level FROM_OTHER"
            """,
        )
        manager = ConfigManager(
            sources=[
                CLISource(args=[], invocation_dir=tmp_path),
                TomlSource(config_file),
            ]
        )
        manager.declare(WithAddopts)
        manager.declare(Other)

        assert manager.get(WithAddopts).level == "FROM_APP"
        assert manager.get(Other).level == "FROM_OTHER"


class TestConfigSourceFields:
    """A ``config_source`` field is honoured wherever its value came from."""

    def test_config_file_named_by_an_env_var_is_loaded(self, tmp_path: Path) -> None:
        """Naming the file in the environment is as explicit as naming it in argv.

        The bootstrap pass used to consult defaults and the CLI only, so a
        config file requested through the environment was silently ignored.
        """
        extra = _toml(tmp_path, '[app]\nlevel = "FROM_EXTRA"\n', name="extra.toml")

        class Bootstrapping(ConfigPart, prefix="app"):
            config_file: Annotated[str | None, config_source] = None
            level: str = "WARNING"

        manager = ConfigManager(
            sources=[
                CLISource(args=[], invocation_dir=tmp_path),
                EnvSource(environ={"APP_CONFIG_FILE": str(extra)}),
            ]
        )
        manager.declare(Bootstrapping)

        assert manager.get(Bootstrapping).level == "FROM_EXTRA"


class TestBooleanCoercion:
    """Explicit boolean values survive the CLI, not just bare flags."""

    def test_explicit_false_is_false(self, tmp_path: Path) -> None:
        """``--flag=false`` used to store the *string* "false", which is truthy."""

        class Flags(ConfigPart, prefix="app"):
            enabled: bool = True

        manager = ConfigManager(
            sources=[CLISource(args=["--enabled=false"], invocation_dir=tmp_path)]
        )
        manager.declare(Flags)

        assert manager.get(Flags).enabled is False

    def test_bare_flag_still_sets_true(self, tmp_path: Path) -> None:
        class Flags(ConfigPart, prefix="app"):
            enabled: bool = False

        manager = ConfigManager(
            sources=[CLISource(args=["--enabled"], invocation_dir=tmp_path)]
        )
        manager.declare(Flags)

        assert manager.get(Flags).enabled is True


class TestUnknownKeysAtEveryDepth:
    """A typo in a nested table is user error, same as one at the top."""

    class Cli(SubConfig):
        level: str = "WARNING"

    class Nested(ConfigPart, prefix="app"):
        level: str = "WARNING"
        cli: TestUnknownKeysAtEveryDepth.Cli  # type: ignore[name-defined]

    def test_nested_unknown_key_warns_and_drops(self, tmp_path: Path) -> None:
        config_file = _toml(
            tmp_path,
            """
            [app]
            level = "INFO"
            [app.cli]
            bogus = 1
            """,
        )
        manager = ConfigManager(sources=[TomlSource(config_file)])
        manager.declare(self.Nested)

        with pytest.warns(UnknownConfigKeyWarning, match=r"cli\.bogus"):
            config = manager.get(self.Nested)

        assert config.level == "INFO"
        assert config.cli.level == "WARNING"
