"""Tests for the spec derivation in `cot.config._specs`.

A spec is a pure function of a root, so it is asserted against a table with no
parser, no manager and no sources anywhere near it. This file is that table:
what each annotation implies, and what each marker adds that no annotation
could have said.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

import pytest

from cot.config import (
    ConfigPart,
    counted,
    env_named,
    form,
    formerly,
    from_env,
    help,
    named,
    no_cli,
    no_ini,
    short,
)
from cot.config._fields import MISSING
from cot.config._specs import FieldSpec, field_specs


class Pool(ConfigPart):
    size: int = 5
    timeout: Annotated[float, from_env] = 1.0


class Mode(Enum):
    WRITE = "w"
    APPEND = "a"


class App(ConfigPart, prefix="app", name_prefix="db"):
    host: str = "localhost"
    verbose: Annotated[bool, short("v"), help("be loud")] = False
    tags: list[str] = []
    level: str | None = None
    mode: Literal["w", "a"] = "a"
    enum_mode: Mode = Mode.APPEND
    secret: Annotated[str, no_cli] = ""
    only_cli: Annotated[bool, no_ini] = False
    legacy: Annotated[str, formerly("old_name")] = ""
    renamed: Annotated[str, named("db_special")] = ""
    verbosity: Annotated[int, short("q"), counted] = 0
    maxfail: Annotated[int, form("--exitfirst", short="x", contributes=1)] = 0
    epoch: Annotated[int | None, from_env, env_named("SOURCE_DATE_EPOCH")] = None
    pool: Pool


class Deeper(ConfigPart):
    deepest: str = ""


class Exposed(ConfigPart):
    deep: str = ""
    deeper: Deeper


class ExposedSubtree(ConfigPart, prefix="app"):
    """`from_env` on a nested field opts in everything below it, at any depth."""

    plain: str = ""
    section: Annotated[Exposed, from_env]


def spec_for(root: type[ConfigPart], dotted: str) -> FieldSpec:
    return next(s for s in field_specs(root) if ".".join(s.path) == dotted)


class TestDerivedFromTheAnnotation:
    def test_bool_is_a_flag_with_a_negative_form(self) -> None:
        form_ = spec_for(App, "verbose").cli[0]
        assert form_.flag is True
        assert form_.long == "--db-verbose"
        assert form_.negative == "--no-db-verbose"

    def test_a_non_bool_takes_a_value_and_has_no_negative(self) -> None:
        form_ = spec_for(App, "host").cli[0]
        assert form_.flag is False
        assert form_.negative is None

    def test_a_list_is_repeatable(self) -> None:
        assert spec_for(App, "tags").repeatable is True
        assert spec_for(App, "host").repeatable is False

    def test_a_union_with_none_is_optional(self) -> None:
        assert spec_for(App, "level").optional is True
        assert spec_for(App, "host").optional is False

    def test_a_literal_is_a_closed_set(self) -> None:
        assert spec_for(App, "mode").values == ("w", "a")

    def test_an_enum_is_a_closed_set_of_its_values(self) -> None:
        assert spec_for(App, "enum_mode").values == ("w", "a")

    def test_anything_else_has_no_closed_set(self) -> None:
        assert spec_for(App, "host").values is None


class TestSpellings:
    def test_the_flat_name_is_the_qualified_path(self) -> None:
        assert spec_for(App, "pool.size").flat == "db_pool_size"

    def test_named_replaces_it(self) -> None:
        assert spec_for(App, "renamed").flat == "db_special"

    def test_no_cli_leaves_no_forms(self) -> None:
        assert spec_for(App, "secret").cli == ()

    def test_no_cli_keeps_the_file_key(self) -> None:
        assert spec_for(App, "secret").file_key == "db_secret"

    def test_no_ini_leaves_no_file_key(self) -> None:
        assert spec_for(App, "only_cli").file_key is None

    def test_no_ini_keeps_the_option(self) -> None:
        assert spec_for(App, "only_cli").cli[0].long == "--db-only-cli"


class TestEnvironmentExposureIsOptIn:
    def test_a_field_that_said_nothing_has_no_spelling(self) -> None:
        assert spec_for(App, "host").env is None

    def test_a_marked_field_gets_one_under_the_root_prefix(self) -> None:
        env = spec_for(App, "pool.timeout").env
        assert env is not None
        assert (env.name, env.absolute) == ("APP_DB_POOL_TIMEOUT", False)

    def test_env_named_is_absolute(self) -> None:
        env = spec_for(App, "epoch").env
        assert env is not None
        assert (env.name, env.absolute) == ("SOURCE_DATE_EPOCH", True)

    def test_a_root_keyword_exposes_every_field(self) -> None:
        class Everything(ConfigPart, prefix="app", from_env=True):
            host: str = ""
            port: int = 0

        assert [s.env.name for s in field_specs(Everything) if s.env] == [
            "APP_HOST",
            "APP_PORT",
        ]

    def test_a_marked_nested_field_exposes_its_subtree(self) -> None:
        exposed = {
            ".".join(s.path) for s in field_specs(ExposedSubtree) if s.env is not None
        }
        assert exposed == {"section.deep", "section.deeper.deepest"}


class TestWhatOnlyAMarkerCanSay:
    def test_aliases_come_from_formerly(self) -> None:
        assert spec_for(App, "legacy").aliases == ("old_name",)
        assert spec_for(App, "host").aliases == ()

    def test_counted_is_not_implied_by_int_with_a_short_option(self) -> None:
        assert spec_for(App, "verbosity").counts is True
        assert spec_for(App, "pool.size").counts is False

    def test_help_text_is_carried(self) -> None:
        assert spec_for(App, "verbose").help == "be loud"

    def test_a_second_form_supplies_a_constant(self) -> None:
        forms = spec_for(App, "maxfail").cli
        assert len(forms) == 2
        assert forms[0].long == "--db-maxfail"
        assert forms[0].contributes is MISSING
        assert (forms[1].long, forms[1].short, forms[1].contributes) == (
            "--exitfirst",
            "-x",
            1,
        )

    def test_a_form_supplying_a_constant_takes_no_value(self) -> None:
        assert spec_for(App, "maxfail").cli[1].flag is True


class TestFormValidation:
    def test_a_form_needs_at_least_one_spelling(self) -> None:
        with pytest.raises(ValueError, match="long option, a short option"):
            form()

    def test_a_long_option_starts_with_two_dashes(self) -> None:
        with pytest.raises(ValueError, match="starts with"):
            form("exitfirst")


class TestTheRecord:
    def test_nested_fields_get_no_spec_of_their_own(self) -> None:
        paths = {".".join(s.path) for s in field_specs(App)}
        assert "pool" not in paths
        assert "pool.size" in paths

    def test_the_group_follows_the_roots_naming(self) -> None:
        assert spec_for(App, "host").group == "db"

    def test_default_and_annotation_are_carried_through(self) -> None:
        spec = spec_for(App, "host")
        assert spec.default == "localhost"
        assert spec.annotation is str
