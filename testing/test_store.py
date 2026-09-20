"""Tests for the layered store and the projection.

The store is what every source said, per path, in ladder order. The projection
is what a fragment ends up with: the winner, the cascade, assembly and the
construction checks. Both are exercised directly, without a manager or a
source anywhere near them.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from cot.config import (
    ConfigPart,
    ConfigValueError,
    MissingConfigError,
    ShadowedValueWarning,
    from_parent,
)
from cot.config._diagnostics import Diagnostics
from cot.config._origins import Origin
from cot.config._projection import project
from cot.config._store import FailedValue, LayeredStore, LayeredValue, Reading


class Cli(ConfigPart):
    level: Annotated[str | None, from_parent] = None
    enabled: bool = False


class Logging(ConfigPart, prefix="pytest", name_prefix="log"):
    level: Annotated[str | None, from_parent] = "WARNING"
    retries: int = 0
    cli: Cli


class Required(ConfigPart):
    host: str
    port: int = 5432


class Child(ConfigPart):
    retries: Annotated[int, from_parent] = 9


class Parent(ConfigPart):
    retries: int = 1
    child: Child


def origin(kind: str, precedence: int, location: str) -> Origin:
    return Origin(kind=kind, location=location, precedence=precedence)  # type: ignore[arg-type]


def store_with(*rows: tuple[tuple[str, ...], object, Origin, str]) -> LayeredStore:
    store = LayeredStore()
    for path, raw, where, dialect in rows:
        store.add(
            Reading(root=Logging, path=path, raw=raw, location=where.location),
            where,
            dialect,  # type: ignore[arg-type]
        )
    return store


class TestTheStoreKeepsEveryLayer:
    def test_layers_come_back_lowest_rung_first(self) -> None:
        store = store_with(
            (("retries",), "3", origin("cli", 25, "--log-retries"), "string"),
            (("retries",), "1", origin("file", 15, "app.toml"), "string"),
        )
        layers = store.layers(Logging, ("retries",))
        assert [layer.origin.kind for layer in layers] == ["file", "cli"]

    def test_the_winner_is_the_highest_rung(self) -> None:
        store = store_with(
            (("retries",), "1", origin("file", 15, "app.toml"), "string"),
            (("retries",), "3", origin("cli", 25, "--log-retries"), "string"),
        )
        won = store.winner(Logging, ("retries",))
        assert isinstance(won, LayeredValue)
        assert won.value == 3

    def test_an_untouched_path_has_no_winner(self) -> None:
        assert LayeredStore().winner(Logging, ("retries",)) is None

    def test_values_are_converted_on_entry(self) -> None:
        store = store_with(
            (("retries",), "7", origin("env", 20, "PYTEST_LOG_RETRIES"), "string")
        )
        won = store.winner(Logging, ("retries",))
        assert isinstance(won, LayeredValue)
        assert won.value == 7  # not "7": nothing downstream sees a raw value

    def test_a_typed_source_is_checked_rather_than_converted(self) -> None:
        store = store_with((("retries",), "7", origin("file", 15, "t.toml"), "typed"))
        assert isinstance(store.winner(Logging, ("retries",)), FailedValue)


class TestFailuresAreJudgedByWhatTheyWouldHaveDone:
    def test_a_failure_that_wins_is_an_error(self) -> None:
        store = store_with(
            (("retries",), "not a number", origin("cli", 25, "--log-retries"), "string")
        )
        diagnostics = Diagnostics()
        store.report_failures(Logging, diagnostics)

        with pytest.raises(ConfigValueError, match="not a number"):
            diagnostics.emit()

    def test_a_shadowed_failure_warns_and_names_what_beat_it(self) -> None:
        store = store_with(
            (("retries",), "nonsense", origin("file", 15, "app.toml"), "string"),
            (("retries",), "3", origin("cli", 25, "--log-retries"), "string"),
        )
        diagnostics = Diagnostics()
        store.report_failures(Logging, diagnostics)

        with pytest.warns(ShadowedValueWarning, match="--log-retries"):
            diagnostics.emit()

    def test_strict_makes_a_shadowed_failure_fatal(self) -> None:
        store = store_with(
            (("retries",), "nonsense", origin("file", 15, "app.toml"), "string"),
            (("retries",), "3", origin("cli", 25, "--log-retries"), "string"),
        )
        diagnostics = Diagnostics(strict=True)
        store.report_failures(Logging, diagnostics)

        with pytest.raises(ConfigValueError):
            diagnostics.emit()

    def test_a_failure_does_not_become_the_value(self) -> None:
        store = store_with(
            (("retries",), "nonsense", origin("cli", 25, "--log-retries"), "string")
        )
        assert project(Logging, store).instance.retries == 0


class TestProjection:
    def test_the_winner_reaches_the_instance(self) -> None:
        store = store_with(
            (("cli", "level"), "DEBUG", origin("cli", 25, "--log-cli-level"), "string")
        )
        assert project(Logging, store).instance.cli.level == "DEBUG"

    def test_an_untouched_field_gets_its_default(self) -> None:
        assert project(Logging, LayeredStore()).instance.retries == 0

    def test_nested_parts_are_assembled(self) -> None:
        built = project(Logging, LayeredStore()).instance
        assert isinstance(built.cli, Cli)
        assert built.cli.enabled is False

    def test_every_value_has_an_origin_including_defaults(self) -> None:
        origins = project(Logging, LayeredStore()).origins
        assert origins["retries"].kind == "default"

    def test_a_missing_required_field_names_every_one_at_once(self) -> None:
        with pytest.raises(MissingConfigError, match="host"):
            project(Required, LayeredStore())


class TestTheCascade:
    def test_a_child_with_nothing_of_its_own_takes_the_parents_value(self) -> None:
        store = store_with(
            (("level",), "DEBUG", origin("cli", 25, "--log-level"), "string")
        )
        assert project(Logging, store).instance.cli.level == "DEBUG"

    def test_the_childs_own_value_wins(self) -> None:
        store = store_with(
            (("level",), "DEBUG", origin("cli", 25, "--log-level"), "string"),
            (("cli", "level"), "INFO", origin("file", 15, "app.toml"), "string"),
        )
        # Not a precedence comparison: the child said something, so it keeps it.
        assert project(Logging, store).instance.cli.level == "INFO"

    def test_a_cascaded_value_is_attributed_to_where_the_parent_got_it(self) -> None:
        store = store_with(
            (("level",), "DEBUG", origin("cli", 25, "--log-level"), "string")
        )
        origins = project(Logging, store).origins
        assert origins["cli.level"].kind == "cli"
        assert "inherited from level" in origins["cli.level"].location

    def test_presence_is_tested_rather_than_truthiness(self) -> None:
        store = LayeredStore()
        store.add(
            Reading(root=Parent, path=("child", "retries"), raw="0", location="--x"),
            origin("cli", 25, "--x"),
            "string",
        )
        # An explicit 0 in the child is a value, not an absence.
        assert project(Parent, store).instance.child.retries == 0

    def test_a_default_in_the_child_does_not_block_the_cascade(self) -> None:
        store = store_with(
            (("level",), "DEBUG", origin("cli", 25, "--log-level"), "string")
        )
        built = project(Logging, store).instance
        assert built.cli.level == "DEBUG"
