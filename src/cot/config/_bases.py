"""The one configuration class.

A ``ConfigPart`` handed to ``manager.declare()`` is a root; a ``ConfigPart``
that is the type of another part's field is nested. There is no second base
class for the second role, because a field's identity is its path within the
root and a class carries no position of its own (D30).

``prefix=``, ``name_prefix=`` and ``from_env=`` describe a root. They are class
keywords rather than field markers because they describe the whole part, and a
nested part carrying one is rejected when the root that contains it is
declared.
"""

from __future__ import annotations

from copy import copy
from typing import Any, ClassVar

from typing_extensions import Self, dataclass_transform


def _is_mutable(value: object) -> bool:
    """Whether a default needs copying to avoid sharing it between instances."""
    return isinstance(value, list | dict | set)


def _freeze(value: object) -> object:
    """Make a value hashable for :meth:`ConfigPart.__hash__`.

    Config values are frequently lists (``list[str]`` fields), which are not
    hashable. Rather than making every config object unhashable because one
    field might hold a list, convert the common containers structurally.
    """
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


#: The class keywords that describe a root, in the order diagnostics name them.
ROOT_KEYWORDS = ("prefix", "name_prefix", "from_env")


@dataclass_transform(eq_default=True, kw_only_default=True, frozen_default=True)
class ConfigPart:
    """A declared group of configuration fields.

    Instances are keyword-only, frozen, and materialised: every field is
    written into the instance ``__dict__``, so equality, ``repr`` and
    provenance do not depend on whether a value was passed or inherited from
    the class body.

    Example:
        class LogCliConfig(ConfigPart):
            level: str | None = None

        class LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log"):
            level: str = "WARNING"
            cli: LogCliConfig
    """

    # Underscored, because a field may legitimately be called `prefix`: an
    # attribute holding a root keyword must not be able to collide with one.
    _prefix: ClassVar[str | None] = None
    _name_prefix: ClassVar[str | None] = None
    _from_env: ClassVar[bool] = False

    def __init_subclass__(
        cls: type[Self],
        prefix: str | None = None,
        name_prefix: str | None = None,
        from_env: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        # Assigned into this class's own body rather than accumulated, so that
        # `declared_root_keywords` can tell a keyword this class set from one
        # it merely inherited from a base.
        if prefix is not None:
            cls._prefix = prefix
        if name_prefix is not None:
            cls._name_prefix = name_prefix
        if from_env is not None:
            cls._from_env = from_env

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
                # Nested fields without a default are built by the manager;
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


def part_prefix(cls: type[ConfigPart]) -> str | None:
    """The file section and environment prefix of the root ``cls`` describes."""
    return cls._prefix


def part_name_prefix(cls: type[ConfigPart]) -> str | None:
    """The segment leading every field name of the root ``cls`` describes."""
    return cls._name_prefix


def part_from_env(cls: type[ConfigPart]) -> bool:
    """Whether ``cls`` exposes every field to the environment."""
    return cls._from_env


def declared_root_keywords(cls: type[ConfigPart]) -> tuple[str, ...]:
    """The root keywords ``cls``'s own class body set, in declaration order.

    An inherited keyword is not reported: the author of the subclass did not
    write it, so it is the base class that made the claim, not this one.
    """
    return tuple(name for name in ROOT_KEYWORDS if f"_{name}" in cls.__dict__)


__all__ = [
    "ROOT_KEYWORDS",
    "ConfigPart",
    "declared_root_keywords",
    "part_from_env",
    "part_name_prefix",
    "part_prefix",
]
