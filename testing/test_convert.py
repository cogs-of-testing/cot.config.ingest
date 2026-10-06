"""Tests for the conversion registry in `cot.config._convert`.

Conversion is the one place a raw value becomes a value of the declared type,
so this is where the type rules live: what each scalar accepts, how a union
resolves, what a closed set permits, and what a converter is told about where
its value came from.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest

from cot.config import ConfigDeclarationError, ConfigPart, ConfigValueError, from_parent
from cot.config._convert import (
    check,
    convert,
    has_conversion,
    register_conversion,
    unregister_conversion,
)
from cot.config._fields import check_declaration
from cot.config._origins import Origin


def origin(location: str = "app.toml[key]", base_dir: Path | None = None) -> Origin:
    return Origin(kind="file", location=location, precedence=15, base_dir=base_dir)


class Mode(Enum):
    WRITE = "w"
    APPEND = "a"


class TestScalars:
    @pytest.mark.parametrize("text", ["true", "TRUE", "yes", "on", "1"])
    def test_the_true_words(self, text: str) -> None:
        assert convert(text, bool, origin()) is True

    @pytest.mark.parametrize("text", ["false", "No", "off", "0"])
    def test_the_false_words(self, text: str) -> None:
        assert convert(text, bool, origin()) is False

    def test_anything_else_is_not_a_bool(self) -> None:
        with pytest.raises(ConfigValueError, match="maybe"):
            convert("maybe", bool, origin())

    def test_numbers_parse_strictly(self) -> None:
        assert convert("5", int, origin()) == 5
        assert convert("2.5", float, origin()) == 2.5
        with pytest.raises(ConfigValueError):
            convert("five", int, origin())

    def test_a_bool_is_not_an_int(self) -> None:
        # Python says True == 1; a field declared int should not take a flag.
        with pytest.raises(ConfigValueError):
            convert(True, int, origin())

    def test_annotated_is_stripped_before_dispatch(self) -> None:
        assert convert("on", Annotated[bool, from_parent], origin()) is True


class TestUnions:
    def test_members_are_tried_in_declaration_order(self) -> None:
        # pytest's log_auto_indent: true|on, false|off, or an integer.
        assert convert("4", bool | int | None, origin()) == 4
        assert convert("true", bool | int | None, origin()) is True

    def test_a_union_that_matches_nothing_raises(self) -> None:
        with pytest.raises(ConfigValueError, match="maybe"):
            convert("maybe", bool | int | None, origin())

    def test_optional_accepts_none(self) -> None:
        assert convert(None, str | None, origin()) is None

    def test_str_last_is_why_order_matters(self) -> None:
        assert convert("4", int | str, origin()) == 4
        assert convert("4", str | int, origin()) == "4"


class TestClosedSets:
    def test_a_literal_accepts_its_members(self) -> None:
        assert convert("w", Literal["w", "a"], origin()) == "w"

    def test_and_rejects_anything_else_naming_them(self) -> None:
        with pytest.raises(ConfigValueError, match="permitted values are 'w', 'a'"):
            convert("x", Literal["w", "a"], origin())

    def test_an_enum_is_matched_by_value_and_returned_by_member(self) -> None:
        assert convert("a", Mode, origin()) is Mode.APPEND

    def test_an_int_literal_is_reachable_from_text(self) -> None:
        assert convert("2", Literal[1, 2], origin()) == 2


class TestLists:
    def test_each_element_is_converted(self) -> None:
        assert convert(["1", "2"], list[int], origin()) == [1, 2]

    def test_a_lone_value_becomes_one_element(self) -> None:
        # Tokenisation is the source's business; this is what it hands over.
        assert convert("only", list[str], origin()) == ["only"]

    def test_a_bad_element_names_the_value(self) -> None:
        with pytest.raises(ConfigValueError, match="nope"):
            convert(["1", "nope"], list[int], origin())


class TestTheTypedDialect:
    def test_a_value_of_the_declared_type_passes_through(self) -> None:
        assert check(5, int, origin()) == 5

    def test_a_value_of_another_type_is_rejected_rather_than_reinterpreted(
        self,
    ) -> None:
        # TOML said it was a string; the field says int. That is a broken file,
        # not something to reinterpret.
        with pytest.raises(ConfigValueError):
            check("5", int, origin())

    def test_a_bool_does_not_satisfy_int(self) -> None:
        with pytest.raises(ConfigValueError):
            check(True, int, origin())

    def test_a_union_takes_the_first_member_that_fits(self) -> None:
        assert check(4, bool | int | None, origin()) == 4
        assert check(True, bool | int | None, origin()) is True

    def test_a_closed_set_is_still_closed(self) -> None:
        with pytest.raises(ConfigValueError):
            check("x", Literal["w", "a"], origin())

    def test_a_list_is_checked_element_by_element(self) -> None:
        assert check([1, 2], list[int], origin()) == [1, 2]
        with pytest.raises(ConfigValueError):
            check(["1"], list[int], origin())

    def test_a_domain_type_falls_back_to_its_conversion(self) -> None:
        # TOML has no Path, so a typed source hands over the text.
        assert check("sub/dir", Path, origin()) == Path("sub/dir")


class TestConversionSeesTheOrigin:
    def test_a_relative_path_resolves_against_the_files_directory(self) -> None:
        converted = convert("log.txt", Path, origin(base_dir=Path("/etc/app")))
        assert converted == Path("/etc/app/log.txt")

    def test_an_absolute_path_is_left_alone(self) -> None:
        converted = convert("/var/log.txt", Path, origin(base_dir=Path("/etc/app")))
        assert converted == Path("/var/log.txt")

    def test_a_source_that_says_nothing_leaves_the_path_relative(self) -> None:
        assert convert("log.txt", Path, origin()) == Path("log.txt")

    def test_the_failure_names_where_the_value_came_from(self) -> None:
        with pytest.raises(ConfigValueError, match=r"pytest.ini\[log_level\]"):
            convert("nope", int, origin("pytest.ini[log_level]"))


class TestTheRegistry:
    def test_an_application_registers_its_own_types(self) -> None:
        register_conversion(re.Pattern, re.compile)
        try:
            pattern = convert(r"v(\d+)", re.Pattern, origin())
            assert pattern.match("v12")
        finally:
            unregister_conversion(re.Pattern)

    def test_a_one_argument_converter_is_adapted(self) -> None:
        register_conversion(complex, complex)
        try:
            assert convert("1+2j", complex, origin()) == complex(1, 2)
        finally:
            unregister_conversion(complex)

    def test_a_converter_asks_for_the_origin_by_naming_it(self) -> None:
        # By name rather than by arity, so that an existing one-argument
        # callable such as re.compile can be registered as it stands.
        seen: list[Origin] = []

        class Marked:
            pass

        def build(raw: Any, origin: Origin) -> Marked:
            seen.append(origin)
            return Marked()

        register_conversion(Marked, build)
        try:
            convert("x", Marked, origin("pytest.ini[k]"))
        finally:
            unregister_conversion(Marked)

        assert seen[0].location == "pytest.ini[k]"

    def test_taking_over_a_registered_type_has_to_be_deliberate(self) -> None:
        with pytest.raises(ValueError, match="already has a conversion"):
            register_conversion(int, int)

    def test_a_converter_that_raises_becomes_a_config_value_error(self) -> None:
        def explode(raw: Any) -> Any:
            raise RuntimeError("no")

        register_conversion(bytes, explode)
        try:
            with pytest.raises(ConfigValueError, match="no"):
                convert("x", bytes, origin())
        finally:
            unregister_conversion(bytes)


class TestWhatCanBeConverted:
    @pytest.mark.parametrize(
        "annotation",
        [str, int, float, bool, Path, list[str], Literal["w"], Mode, int | None],
    )
    def test_the_built_in_entries(self, annotation: Any) -> None:
        assert has_conversion(annotation)

    def test_an_unregistered_type_is_not_convertible(self) -> None:
        class Custom:
            pass

        assert not has_conversion(Custom)

    def test_a_field_the_library_cannot_convert_is_refused_at_declare(self) -> None:
        with pytest.raises(ConfigDeclarationError, match="no registered conversion"):
            check_declaration(Unconvertible)

    def test_and_is_accepted_once_a_conversion_exists(self) -> None:
        register_conversion(Custom, lambda raw: Custom())
        try:
            check_declaration(Unconvertible)
        finally:
            unregister_conversion(Custom)


class Custom:
    """A domain type the library knows nothing about."""


class Unconvertible(ConfigPart):
    value: Custom
