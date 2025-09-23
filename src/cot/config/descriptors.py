from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, overload

T = TypeVar("T")

MISSING = object()


@dataclass
class FieldDescriptor:
    """Descriptor for configuration fields with metadata."""

    name: str | None = None
    default: Any = MISSING
    default_factory: Callable[[], Any] | None = None
    help: str | None = None
    choices: list[Any] | None = None
    from_parent: bool = False
    metavar: str | None = None
    action: str | None = None
    required: bool = False

    def __set_name__(self, owner: type, name: str) -> None:
        """Set the field name when attached to a class.

        :param owner: The class that owns this descriptor
        :param name: The name of the attribute
        """
        if self.name is None:
            self.name = name

    def get_default(self) -> Any:
        """Get the default value for this field.

        :returns: The default value or result of default_factory
        """
        if self.default_factory is not None:
            return self.default_factory()
        if self.default is not MISSING:
            return self.default
        return None

    def validate(self, value: Any) -> Any:
        """Validate the value against choices if specified.

        :param value: The value to validate
        :returns: The validated value
        :raises ValueError: If value is not in allowed choices
        """
        if self.choices is not None and value not in self.choices:
            raise ValueError(
                f"Invalid value {value!r} for {self.name}. "
                f"Must be one of {self.choices}"
            )
        return value


@dataclass
class SubConfigDescriptor:
    """Descriptor for nested configuration objects."""

    config_class: type[Any]
    primary: str | None = None
    name: str | None = None

    def __set_name__(self, owner: type, name: str) -> None:
        """Set the sub-config name when attached to a class.

        :param owner: The class that owns this descriptor
        :param name: The name of the attribute
        """
        if self.name is None:
            self.name = name


class FromParentMarker:
    """Marker to indicate a field should inherit from parent config."""

    def __repr__(self) -> str:
        return "from_parent"


from_parent = FromParentMarker()


@overload
def field(
    *,
    default: T,
    help: str | None = None,
    choices: list[T] | None = None,
    metavar: str | None = None,
) -> T: ...


@overload
def field(
    *,
    default_factory: Callable[[], T],
    help: str | None = None,
    choices: list[T] | None = None,
    metavar: str | None = None,
) -> T: ...


@overload
def field(
    from_parent: FromParentMarker,
    *,
    default: T | None = None,
    help: str | None = None,
    choices: list[T] | None = None,
    metavar: str | None = None,
) -> T: ...


@overload
def field(
    *,
    help: str | None = None,
    choices: list[T] | None = None,
    metavar: str | None = None,
) -> Any: ...


def field(
    from_parent: FromParentMarker | None = None,
    *,
    default: Any = MISSING,
    default_factory: Callable[[], Any] | None = None,
    help: str | None = None,
    choices: list[Any] | None = None,
    metavar: str | None = None,
    action: str | None = None,
    required: bool = False,
) -> Any:
    """
    Create a field descriptor for configuration attributes.

    :param from_parent: Marker to inherit value from parent config
    :param default: Default value for the field
    :param default_factory: Callable to create default value
    :param help: Help text for the field
    :param choices: Valid choices for the field value
    :param metavar: Metavar for CLI argument
    :param action: CLI action type (e.g., 'append', 'store_true')
    :param required: Whether the field is required
    :returns: FieldDescriptor instance
    :raises ValueError: If both default and default_factory are specified
    """
    if default_factory is not None and default is not MISSING:
        raise ValueError("Cannot specify both default and default_factory")

    is_from_parent = from_parent is not None

    return FieldDescriptor(
        default=default,
        default_factory=default_factory,
        help=help,
        choices=choices,
        from_parent=is_from_parent,
        metavar=metavar,
        action=action,
        required=required,
    )


def sub_config(
    config_class: type[T] | None = None,
    *,
    primary: str | None = None,
) -> T:
    """
    Create a sub-configuration descriptor.

    :param config_class: The configuration class for the sub-config
    :param primary: The primary field name for CLI mapping
    :returns: SubConfigDescriptor instance
    """
    if config_class is None:
        # This will be filled in by the metaclass
        return SubConfigDescriptor(config_class=type, primary=primary)  # type: ignore
    return SubConfigDescriptor(config_class=config_class, primary=primary)  # type: ignore
