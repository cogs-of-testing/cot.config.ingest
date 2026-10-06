"""Tests for the spelling index in `cot.config._index`.

The index is the only thing that recognises a name a user typed, and the only
thing that holds every declared root at once. Both halves are pinned here: the
four lookups, and the judgement it makes when two roots reach for one spelling.
"""

from __future__ import annotations

from typing import Annotated

import pytest

from cot.config import (
    ConfigCollisionError,
    ConfigManager,
    ConfigPart,
    env_named,
    formerly,
    from_env,
    named,
    short,
)
from cot.config._index import SpellingIndex


class Cli(ConfigPart):
    level: str | None = None


class Logging(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    verbose: Annotated[bool, short("v")] = False
    legacy: Annotated[str, formerly("old_log_name")] = ""
    exposed: Annotated[str, from_env] = ""
    epoch: Annotated[str, from_env, env_named("SOURCE_DATE_EPOCH")] = ""
    cli: Cli


class Cache(ConfigPart, prefix="pytest", name_prefix="cache"):
    level: str = "WARNING"
    cli: Cli


def index_over(*roots: type[ConfigPart]) -> SpellingIndex:
    index = SpellingIndex()
    for root in roots:
        index.add(root)
    return index


class TestTheFourLookups:
    def test_a_flat_key_resolves_to_root_and_path(self) -> None:
        (target,) = index_over(Logging).flat("log_cli_level")
        assert (target.root, target.path) == (Logging, ("cli", "level"))

    def test_an_option_resolves(self) -> None:
        (target,) = index_over(Logging).cli("--log-cli-level")
        assert target.path == ("cli", "level")

    def test_a_short_option_resolves(self) -> None:
        (target,) = index_over(Logging).cli("-v")
        assert target.path == ("verbose",)

    def test_a_negated_boolean_resolves(self) -> None:
        (target,) = index_over(Logging).cli("--no-log-verbose")
        assert target.path == ("verbose",)

    def test_a_nested_table_key_resolves(self) -> None:
        (target,) = index_over(Logging).nested("pytest", ("log", "cli"), "level")
        assert target.path == ("cli", "level")

    def test_a_variable_resolves_under_the_sources_prefix(self) -> None:
        index = index_over(Logging)
        (target,) = index.env("PYTEST_LOG_EXPOSED")
        assert target.path == ("exposed",)
        (prefixed,) = index.env("APP_PYTEST_LOG_EXPOSED", source_prefix="app")
        assert prefixed.path == ("exposed",)

    def test_an_absolute_variable_ignores_the_sources_prefix(self) -> None:
        index = index_over(Logging)
        (target,) = index.env("SOURCE_DATE_EPOCH", source_prefix="app")
        assert target.path == ("epoch",)

    def test_an_unclaimed_spelling_resolves_to_nothing(self) -> None:
        index = index_over(Logging)
        assert index.flat("log_nonsense") == ()
        assert index.cli("--nonsense") == ()
        assert index.nested("pytest", ("log",), "nonsense") == ()
        assert index.env("NONSENSE") == ()


class TestAliases:
    def test_a_legacy_name_resolves_to_the_field(self) -> None:
        (target,) = index_over(Logging).flat("old_log_name")
        assert target.path == ("legacy",)

    def test_and_says_it_is_deprecated(self) -> None:
        (current,) = index_over(Logging).flat("log_legacy")
        (alias,) = index_over(Logging).flat("old_log_name")
        assert current.deprecated is False
        assert alias.deprecated is True


class TestOneNamespaceAcrossRoots:
    def test_a_shared_section_keeps_two_roots_apart_by_name_prefix(self) -> None:
        index = index_over(Logging, Cache)
        (logging_target,) = index.flat("log_cli_level")
        (cache_target,) = index.flat("cache_cli_level")
        assert logging_target.root is Logging
        assert cache_target.root is Cache

    def test_nested_tables_stay_apart_too(self) -> None:
        index = index_over(Logging, Cache)
        (target,) = index.nested("pytest", ("cache", "cli"), "level")
        assert target.root is Cache


class TestCollisions:
    def test_two_roots_claiming_one_flat_name_is_an_error(self) -> None:
        class Alpha(ConfigPart, prefix="alpha"):
            value: str = "a"

        class Beta(ConfigPart, prefix="beta"):
            value: str = "b"

        index = SpellingIndex()
        index.add(Alpha)
        with pytest.raises(ConfigCollisionError) as excinfo:
            index.add(Beta)

        message = str(excinfo.value)
        assert "Alpha.value" in message
        assert "Beta.value" in message
        assert "name_prefix=" in message

    def test_a_prefix_does_not_scope_the_option_namespace(self) -> None:
        # Two sections, one option: --value has no section to sit in, so the
        # two roots meet in the flat namespace whatever their prefix. Their
        # specs agree, so this is adoption rather than an error.
        class One(ConfigPart, prefix="one"):
            value: str = "same"

        class Two(ConfigPart, prefix="two"):
            value: str = "same"

        index = SpellingIndex()
        index.add(One)
        index.add(Two)
        assert {t.root for t in index.flat("value")} == {One, Two}

    def test_two_roots_claiming_one_short_option_is_an_error(self) -> None:
        class Left(ConfigPart, name_prefix="left"):
            verbose: Annotated[bool, short("v")] = False

        class Right(ConfigPart, name_prefix="right"):
            verbose: Annotated[bool, short("v")] = False

        index = SpellingIndex()
        index.add(Left)
        with pytest.raises(ConfigCollisionError, match="'-v'"):
            index.add(Right)

    def test_an_alias_colliding_with_a_real_name_is_an_error(self) -> None:
        class Owner(ConfigPart):
            taken: str = ""

        class Claimant(ConfigPart, name_prefix="other"):
            field: Annotated[str, formerly("taken")] = ""

        index = SpellingIndex()
        index.add(Owner)
        with pytest.raises(ConfigCollisionError, match="'taken'"):
            index.add(Claimant)


class TestAdoption:
    def test_identical_specs_share_one_spelling(self) -> None:
        class Plugin(ConfigPart):
            option: Annotated[str, named("shared_option")] = "default"

        class Host(ConfigPart):
            option: Annotated[str, named("shared_option")] = "default"

        index = index_over(Plugin, Host)
        targets = index.flat("shared_option")
        assert {t.root for t in targets} == {Plugin, Host}

    def test_adoption_does_not_depend_on_who_declared_first(self) -> None:
        class Plugin(ConfigPart):
            option: Annotated[str, named("shared_option")] = "default"

        class Host(ConfigPart):
            option: Annotated[str, named("shared_option")] = "default"

        one = {t.root for t in index_over(Plugin, Host).flat("shared_option")}
        other = {t.root for t in index_over(Host, Plugin).flat("shared_option")}
        assert one == other

    def test_a_differing_default_is_not_adoptable(self) -> None:
        class Plugin(ConfigPart):
            option: Annotated[str, named("shared_option")] = "one"

        class Host(ConfigPart):
            option: Annotated[str, named("shared_option")] = "another"

        index = SpellingIndex()
        index.add(Plugin)
        with pytest.raises(ConfigCollisionError):
            index.add(Host)


class TestTheManagerBuildsIt:
    def test_declare_extends_the_index(self) -> None:
        manager = ConfigManager()
        manager.declare(Logging)
        (target,) = manager.index.flat("log_cli_level")
        assert target.root is Logging

    def test_a_collision_is_reported_at_declare(self) -> None:
        class Alpha(ConfigPart):
            value: str = "a"

        class Beta(ConfigPart):
            value: str = "b"

        manager = ConfigManager()
        manager.declare(Alpha)
        with pytest.raises(ConfigCollisionError):
            manager.declare(Beta)

    def test_declaring_the_same_root_twice_is_a_no_op(self) -> None:
        manager = ConfigManager()
        manager.declare(Logging)
        manager.declare(Logging)
        assert len(manager.index.flat("log_cli_level")) == 1
