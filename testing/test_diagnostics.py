"""Tests for the diagnostic set in `cot.config._diagnostics`.

Two things are pinned here: the shape of the taxonomy, because a host filters
and an application catches by base class, and the aggregation, because one
resolution says everything it found once rather than a stream in an order
nobody controls.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cot.config import (
    ConfigCollisionError,
    ConfigDeclarationError,
    ConfigError,
    ConfigLifecycleError,
    ConfigManager,
    ConfigPart,
    ConfigUsageError,
    ConfigValueError,
    ConfigWarning,
    DeprecatedNameWarning,
    MissingConfigError,
    RuntimeMutationWarning,
    ShadowedValueWarning,
    TomlSource,
    UnknownConfigKeyWarning,
    UnknownOverrideKeyWarning,
)
from cot.config._diagnostics import STRICT_PROMOTIONS, Diagnostics


class Sample(ConfigPart, prefix="app"):
    host: str = "localhost"
    port: int = 5432


class TestTheTaxonomy:
    @pytest.mark.parametrize(
        "warning",
        [
            UnknownConfigKeyWarning,
            UnknownOverrideKeyWarning,
            DeprecatedNameWarning,
            ShadowedValueWarning,
            RuntimeMutationWarning,
        ],
    )
    def test_every_warning_shares_one_base(self, warning: type[ConfigWarning]) -> None:
        assert issubclass(warning, ConfigWarning)
        assert issubclass(warning, UserWarning)

    @pytest.mark.parametrize(
        "error",
        [
            ConfigLifecycleError,
            ConfigDeclarationError,
            ConfigCollisionError,
            ConfigUsageError,
            ConfigValueError,
            MissingConfigError,
        ],
    )
    def test_every_error_shares_one_base(self, error: type[ConfigError]) -> None:
        assert issubclass(error, ConfigError)

    def test_a_collision_is_a_declaration_error(self) -> None:
        # Programmer error, not input: the declaration is what is wrong.
        assert issubclass(ConfigCollisionError, ConfigDeclarationError)

    def test_a_deprecated_name_is_not_a_deprecation_warning(self) -> None:
        # Python hides DeprecationWarning outside __main__, and the person who
        # has to rename a key in a config file is not running the interpreter.
        assert not issubclass(DeprecatedNameWarning, DeprecationWarning)


class TestAggregation:
    def test_one_category_is_reported_once_naming_everything(self) -> None:
        diagnostics = Diagnostics()
        diagnostics.extend(UnknownConfigKeyWarning, ["hsot", "prot", "verbsoe"])

        with pytest.warns(UnknownConfigKeyWarning) as caught:
            diagnostics.emit()

        assert len(caught) == 1
        message = str(caught[0].message)
        assert "hsot" in message
        assert "prot" in message
        assert "verbsoe" in message

    def test_two_categories_are_reported_once_each(self) -> None:
        diagnostics = Diagnostics()
        diagnostics.add(UnknownConfigKeyWarning, "hsot")
        diagnostics.add(DeprecatedNameWarning, "write_to is now version_file")

        with pytest.warns(ConfigWarning) as caught:
            diagnostics.emit()

        assert {w.category for w in caught} == {
            UnknownConfigKeyWarning,
            DeprecatedNameWarning,
        }

    def test_nothing_collected_says_nothing(self) -> None:
        import warnings as warnings_module

        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error")
            Diagnostics().emit()

    def test_an_error_carries_every_message(self) -> None:
        diagnostics = Diagnostics()
        diagnostics.add(ConfigUsageError, "first problem")
        diagnostics.add(ConfigUsageError, "second problem")

        with pytest.raises(ConfigUsageError) as excinfo:
            diagnostics.emit()

        assert "first problem" in str(excinfo.value)
        assert "second problem" in str(excinfo.value)

    def test_clear_forgets_a_stale_pass(self) -> None:
        # An earlier iteration parsed argv against fewer options, so what it
        # complained about may no longer be true.
        diagnostics = Diagnostics()
        diagnostics.add(UnknownConfigKeyWarning, "stale")
        diagnostics.clear()
        assert diagnostics.entries == []


class TestStrictMode:
    @pytest.mark.parametrize(("warning", "error"), list(STRICT_PROMOTIONS.items()))
    def test_each_input_warning_is_promoted(
        self, warning: type[ConfigWarning], error: type[ConfigError]
    ) -> None:
        diagnostics = Diagnostics(strict=True)
        diagnostics.add(warning, "something the user wrote")

        with pytest.raises(error):
            diagnostics.emit()

    def test_a_runtime_mutation_is_exempt(self) -> None:
        # It reports what the host did, not what the user wrote, and promoting
        # it would make manager.set() unusable.
        assert RuntimeMutationWarning not in STRICT_PROMOTIONS

        diagnostics = Diagnostics(strict=True)
        diagnostics.add(RuntimeMutationWarning, "OutputConfig.color set by pager")

        with pytest.warns(RuntimeMutationWarning):
            diagnostics.emit()

    def test_lenient_by_default(self) -> None:
        diagnostics = Diagnostics()
        diagnostics.add(UnknownConfigKeyWarning, "hsot")

        with pytest.warns(UnknownConfigKeyWarning):
            diagnostics.emit()


class TestTheManagerReportsOnce:
    def _file(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "app.toml"
        path.write_text(dedent(body))
        return path

    def test_several_typos_produce_one_warning(self, tmp_path: Path) -> None:
        config = self._file(
            tmp_path,
            """
            [app]
            hsot = "db.internal"
            prot = 1
            extra = true
            """,
        )
        manager = ConfigManager(sources=[TomlSource(config)])
        manager.declare(Sample)

        with pytest.warns(UnknownConfigKeyWarning) as caught:
            manager.get(Sample)

        assert len(caught) == 1

    def test_strict_makes_a_typo_fatal(self, tmp_path: Path) -> None:
        config = self._file(
            tmp_path,
            """
            [app]
            hsot = "db.internal"
            """,
        )
        manager = ConfigManager(sources=[TomlSource(config)], strict=True)
        manager.declare(Sample)

        with pytest.raises(ConfigUsageError, match="hsot"):
            manager.get(Sample)

    def test_strict_is_off_unless_asked_for(self) -> None:
        assert ConfigManager().strict is False
        assert ConfigManager(strict=True).strict is True
