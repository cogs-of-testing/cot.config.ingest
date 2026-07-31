"""The declare / resolve / get lifecycle.

Declaration is separate from resolution because a host collects declarations
from independent plugins before any of them can be resolved. These tests pin
the properties that separation is supposed to buy.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Annotated

import pytest

from cot.config import (
    CLISource,
    ConfigLifecycleError,
    ConfigManager,
    ConfigPart,
    IniSource,
    TomlSource,
    addopts_field,
    config_source,
)


class Alpha(ConfigPart, prefix="alpha"):
    value: str = "alpha-default"


class Beta(ConfigPart, prefix="beta"):
    value: str = "beta-default"


class TestDeclaration:
    def test_declare_does_not_build(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)

        assert manager.declared == [Alpha]
        assert manager.resolved is False

    def test_declaring_twice_is_a_noop(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)
        manager.declare(Alpha)

        assert manager.declared == [Alpha]

    def test_declaration_order_is_preserved(self) -> None:
        manager = ConfigManager()
        manager.declare(Beta)
        manager.declare(Alpha)

        assert manager.declared == [Beta, Alpha]

    def test_declaring_after_resolve_raises(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)
        manager.resolve()

        with pytest.raises(ConfigLifecycleError, match="already frozen"):
            manager.declare(Beta)

    def test_error_names_the_offending_type(self) -> None:
        manager = ConfigManager()
        manager.resolve()

        with pytest.raises(ConfigLifecycleError, match="Beta"):
            manager.declare(Beta)


class TestResolution:
    def test_resolve_builds_every_declared_type(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)
        manager.declare(Beta)
        manager.resolve()

        assert manager.get(Alpha).value == "alpha-default"
        assert manager.get(Beta).value == "beta-default"

    def test_resolve_is_idempotent(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)
        manager.resolve()
        first = manager.get(Alpha)
        manager.resolve()

        assert manager.get(Alpha) is first

    def test_get_resolves_implicitly(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)

        assert manager.get(Alpha).value == "alpha-default"
        assert manager.resolved is True

    def test_get_of_undeclared_type_raises(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)

        with pytest.raises(KeyError, match="Beta"):
            manager.get(Beta)

    def test_undeclared_error_lists_what_was_declared(self) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)

        with pytest.raises(KeyError, match="Alpha"):
            manager.get(Beta)


class TestCrossFragmentBootstrap:
    """The reason declaration and resolution are separate.

    Under the old eager API each fragment was built as it was registered, so a
    fragment could not see a config file or addopts contributed by a fragment
    registered after it. Both directions are checked here.
    """

    def test_config_file_declared_by_a_later_fragment_is_seen(
        self, tmp_path: Path
    ) -> None:
        extra = tmp_path / "extra.toml"
        extra.write_text(
            dedent("""
            [alpha]
            value = "from-discovered-file"
        """)
        )

        class Loader(ConfigPart, prefix="loader"):
            config_file: Annotated[str | None, config_source] = None

        manager = ConfigManager(
            sources=[
                CLISource(args=["--config-file", str(extra)], invocation_dir=tmp_path)
            ]
        )
        # Alpha is declared *first*, and knows nothing about the file that the
        # later fragment is about to contribute.
        manager.declare(Alpha)
        manager.declare(Loader)
        manager.resolve()

        assert manager.get(Alpha).value == "from-discovered-file"

    def test_addopts_from_a_later_fragment_reaches_an_earlier_one(
        self, tmp_path: Path
    ) -> None:
        ini = tmp_path / "opts.ini"
        ini.write_text(
            dedent("""
            [opts]
            addopts = --value from-addopts
        """)
        )

        class Opts(ConfigPart, prefix="opts"):
            addopts: Annotated[str, addopts_field] = ""

        manager = ConfigManager(
            sources=[
                IniSource(ini),
                CLISource(args=[], invocation_dir=tmp_path),
            ]
        )
        manager.declare(Alpha)
        manager.declare(Opts)
        manager.resolve()

        assert manager.get(Alpha).value == "from-addopts"

    def test_declaration_order_does_not_change_the_result(self, tmp_path: Path) -> None:
        ini = tmp_path / "opts.ini"
        ini.write_text(
            dedent("""
            [opts]
            addopts = --value from-addopts
        """)
        )

        class Opts(ConfigPart, prefix="opts"):
            addopts: Annotated[str, addopts_field] = ""

        def build(*order: type[ConfigPart]) -> str:
            manager = ConfigManager(
                sources=[
                    IniSource(ini),
                    CLISource(args=[], invocation_dir=tmp_path),
                ]
            )
            for part in order:
                manager.declare(part)
            return manager.get(Alpha).value

        assert build(Alpha, Opts) == build(Opts, Alpha)


class TestSourcesAddedLate:
    def test_source_added_after_declaration_learns_about_it(
        self, tmp_path: Path
    ) -> None:
        toml = tmp_path / "late.toml"
        toml.write_text('[alpha]\nvalue = "from-late-source"\n')

        manager = ConfigManager()
        manager.declare(Alpha)
        manager.add_source(TomlSource(toml))

        assert manager.get(Alpha).value == "from-late-source"

    def test_cli_source_added_late_registers_declared_options(
        self, tmp_path: Path
    ) -> None:
        manager = ConfigManager()
        manager.declare(Alpha)
        # The CLI source has to be told about Alpha even though it arrived
        # after the declaration, or --value would be an unknown argument.
        manager.add_source(CLISource(args=["--value", "x"], invocation_dir=tmp_path))

        assert manager.get(Alpha).value == "x"
