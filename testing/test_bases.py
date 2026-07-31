"""Tests for ConfigPart/SubConfig construction semantics.

These classes advertise `@dataclass_transform(eq_default=True,
kw_only_default=True, frozen_default=True)`. These tests pin the behaviour that
promise implies.
"""

from __future__ import annotations

import pytest

from cot.config import ConfigPart, SubConfig


class Inner(SubConfig):
    host: str = "localhost"
    port: int = 5432


class Sample(ConfigPart):
    name: str
    debug: bool = False
    tags: list[str] = []


class TestConstruction:
    def test_defaults_are_applied(self) -> None:
        sample = Sample(name="x")
        assert sample.debug is False

    def test_explicit_values_win(self) -> None:
        assert Sample(name="x", debug=True).debug is True

    def test_defaults_land_in_instance_dict(self) -> None:
        # Equality compares __dict__, so a default must be materialised there
        # or two equal configs would compare unequal.
        assert Sample(name="x").__dict__ == {
            "name": "x",
            "debug": False,
            "tags": [],
        }

    # The type: ignore comments below are the point of these tests: thanks to
    # @dataclass_transform, mypy now rejects these calls statically. The tests
    # pin the matching runtime behaviour for callers without a type checker.

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(TypeError, match="missing required field"):
            Sample()  # type: ignore[call-arg]

    def test_missing_required_field_names_the_field(self) -> None:
        with pytest.raises(TypeError, match="name"):
            Sample()  # type: ignore[call-arg]

    def test_unknown_kwarg_raises(self) -> None:
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            Sample(name="x", nope=1)  # type: ignore[call-arg]

    def test_unknown_kwarg_lists_known_fields(self) -> None:
        with pytest.raises(TypeError, match="Known fields: debug, name, tags"):
            Sample(name="x", nope=1)  # type: ignore[call-arg]

    def test_inherited_fields_are_accepted(self) -> None:
        class Derived(Inner):
            extra: str = "e"

        derived = Derived(host="h", port=1, extra="z")
        assert (derived.host, derived.port, derived.extra) == ("h", 1, "z")


class TestFrozen:
    def test_cannot_reassign(self) -> None:
        sample = Sample(name="x")
        with pytest.raises(AttributeError, match="Cannot modify frozen attribute"):
            sample.debug = True  # type: ignore[misc]

    def test_cannot_set_new_attribute(self) -> None:
        sample = Sample(name="x")
        with pytest.raises(AttributeError, match="Cannot modify frozen attribute"):
            sample.brand_new = 1

    def test_cannot_delete(self) -> None:
        sample = Sample(name="x")
        with pytest.raises(AttributeError, match="Cannot delete frozen attribute"):
            del sample.debug


class TestEquality:
    def test_equal_when_same_values(self) -> None:
        assert Sample(name="x") == Sample(name="x")

    def test_default_equals_explicit(self) -> None:
        assert Sample(name="x") == Sample(name="x", debug=False)

    def test_unequal_when_values_differ(self) -> None:
        assert Sample(name="x") != Sample(name="y")

    def test_unequal_across_types(self) -> None:
        class Other(ConfigPart):
            name: str
            debug: bool = False
            tags: list[str] = []

        assert Sample(name="x") != Other(name="x")


class TestHashing:
    def test_hashable(self) -> None:
        assert hash(Inner()) == hash(Inner())

    def test_usable_in_a_set(self) -> None:
        assert len({Inner(), Inner(), Inner(port=1)}) == 2

    def test_hashable_despite_list_field(self) -> None:
        # `tags: list[str]` would make a naive __hash__ blow up.
        assert hash(Sample(name="x", tags=["a", "b"])) == hash(
            Sample(name="x", tags=["a", "b"])
        )

    def test_different_lists_hash_differently(self) -> None:
        assert hash(Sample(name="x", tags=["a"])) != hash(Sample(name="x", tags=["b"]))


class TestRepr:
    def test_repr_shows_fields(self) -> None:
        assert repr(Inner(host="db", port=1)) == "Inner(host='db', port=1)"

    def test_repr_includes_defaults(self) -> None:
        assert repr(Inner()) == "Inner(host='localhost', port=5432)"

    def test_nested_repr(self) -> None:
        class WithNested(ConfigPart):
            inner: Inner

        assert repr(WithNested(inner=Inner())) == (
            "WithNested(inner=Inner(host='localhost', port=5432))"
        )


class TestInitSubclass:
    def test_prefix_recorded_as_marker(self) -> None:
        from cot.config._annotations import PrefixMarker

        class Prefixed(ConfigPart, prefix="app"):
            value: int = 1

        assert any(
            isinstance(m, PrefixMarker) and m.prefix == "app"
            for m in Prefixed._config_markers
        )

    def test_init_subclass_chain_is_not_swallowed(self) -> None:
        recorded: list[str] = []

        class Mixin:
            def __init_subclass__(cls, **kwargs: object) -> None:
                super().__init_subclass__(**kwargs)
                recorded.append(cls.__name__)

        class Combined(ConfigPart, Mixin, prefix="app"):
            value: int = 1

        assert recorded == ["Combined"]
