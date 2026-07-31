"""Base classes for configuration."""

from __future__ import annotations

from copy import copy
from typing import Any, ClassVar

from typing_extensions import Self, dataclass_transform

from ._annotations import NamePrefixMarker, PrefixMarker


def _is_mutable(value: object) -> bool:
    """Whether a default needs copying to avoid sharing it between instances."""
    return isinstance(value, list | dict | set)


def _freeze(value: object) -> object:
    """Make a value hashable for :meth:`__hash__`.

    Config values are frequently lists (``list[str]`` fields), which are not
    hashable.  Rather than making every config object unhashable because one
    field might hold a list, convert the common containers structurally.
    """
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


class _FrozenFromKwargsMixin:
    """
    Frozen, keyword-only construction with dataclass-like semantics.

    Instances are built from keyword arguments only, validated against the
    declared fields, and immutable afterwards.  Defaults are materialised into
    the instance ``__dict__`` so that equality and repr do not depend on
    whether a value was passed explicitly or inherited from the class body.
    """

    _config_markers: ClassVar[
        tuple[object, ...]
    ] = ()  # configuration for the classes themselves

    def __init_subclass__(
        cls: type[Self],
        prefix: str | None = None,
        name_prefix: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if prefix is not None:
            cls._config_markers += (PrefixMarker(prefix),)
        if name_prefix is not None:
            cls._config_markers += (NamePrefixMarker(name_prefix),)

    def __init__(self, **kwargs: object) -> None:
        from ._fields import MISSING, fields_of

        fields = fields_of(type(self), recurse=False)
        known = {field.name: field for field in fields}

        unknown = [name for name in kwargs if name not in known]
        if unknown:
            raise TypeError(
                f"{type(self).__name__} got unexpected keyword argument(s) "
                f"{', '.join(sorted(unknown))}. "
                f"Known fields: {', '.join(sorted(known)) or '(none)'}"
            )

        missing: list[str] = []
        for field in fields:
            if field.name in kwargs:
                value = kwargs[field.name]
            elif field.default is not MISSING:
                # A mutable class-level default (``tags: list[str] = []``) is
                # shared by every instance; hand out a copy instead.
                value = (
                    copy(field.default)
                    if _is_mutable(field.default)
                    else (field.default)
                )
            else:
                # Sub-config fields without a default are built by the manager;
                # constructing one directly without it is still an error.
                missing.append(field.name)
                continue
            object.__setattr__(self, field.name, value)

        if missing:
            raise TypeError(
                f"{type(self).__name__} missing required field(s): "
                f"{', '.join(sorted(missing))}"
            )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            f"Cannot modify frozen attribute {name!r} on {type(self).__name__}"
        )

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"Cannot delete frozen attribute {name!r} on {type(self).__name__}"
        )

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        return hash(
            (
                type(self),
                tuple(sorted((k, _freeze(v)) for k, v in self.__dict__.items())),
            )
        )

    def __repr__(self) -> str:
        from ._fields import fields_of

        parts = [
            f"{field.name}={getattr(self, field.name)!r}"
            for field in fields_of(type(self), recurse=False)
            if field.name in self.__dict__
        ]
        return f"{type(self).__name__}({', '.join(parts)})"


@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)
class ConfigPart(_FrozenFromKwargsMixin):
    """
    Base class for configuration parts that can be composed together.

    Example:
        class LoggingConfig(ConfigPart):
            level: str = "INFO"
            file: str | None = None
    """


@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)
class SubConfig(_FrozenFromKwargsMixin):
    """
    Base class for sub-configuration sections.

    class DatabaseConfig(SubConfig):
        host: str
        port: int

    class AppConfig(ConfigPart):
        debug: bool = False
        database: DatabaseConfig

    """


__all__ = [
    "ConfigPart",
    "SubConfig",
]
