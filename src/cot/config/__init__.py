from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, TypeAlias

import typing_extensions
from typing_extensions import Self

from .descriptors import (
    FieldDescriptor,
    FromParentMarker,
    SubConfigDescriptor,
    field,
    from_parent,
    sub_config,
)

Origin: TypeAlias = str | Path | None
InputData: TypeAlias = dict[str, Any]

Inputs: TypeAlias = Sequence[InputData | tuple[Origin, InputData]]
NormalizedInputs: TypeAlias = Sequence[tuple[Origin, InputData]]


class ConfigMeta(type):
    """Metaclass for configuration classes to process field descriptors."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> ConfigMeta:
        # Extract prefix if provided
        prefix = kwargs.pop("prefix", None)

        # Collect field descriptors from class and bases
        fields: dict[str, FieldDescriptor | SubConfigDescriptor] = {}

        # Inherit fields from base classes
        for base in bases:
            if hasattr(base, "__config_fields__"):
                base_fields = base.__config_fields__
                fields.update(base_fields)

        # Process current class fields
        for key, value in list(namespace.items()):
            if isinstance(value, (FieldDescriptor, SubConfigDescriptor)):
                fields[key] = value
                if isinstance(value, FieldDescriptor):
                    value.name = key
                elif isinstance(value, SubConfigDescriptor):
                    value.name = key
                    # Handle forward references
                    if value.config_class is type:
                        # This will be resolved later
                        pass

        # Store fields metadata
        namespace["__config_fields__"] = fields
        namespace["__config_prefix__"] = prefix

        cls = super().__new__(mcs, name, bases, namespace)

        # Set field names
        for field_name, field_obj in fields.items():
            if hasattr(field_obj, "__set_name__"):
                field_obj.__set_name__(cls, field_name)

        return cls


@typing_extensions.dataclass_transform()
class Config(metaclass=ConfigMeta):
    """Base class for configuration objects."""

    __config_fields__: ClassVar[dict[str, FieldDescriptor | SubConfigDescriptor]] = {}
    __config_prefix__: ClassVar[str | None] = None

    def __init__(self, **kwargs: Any):
        # Initialize fields with defaults
        for field_name, field_obj in self.__config_fields__.items():
            if isinstance(field_obj, FieldDescriptor):
                if field_name in kwargs:
                    value = field_obj.validate(kwargs[field_name])
                else:
                    value = field_obj.get_default()
                setattr(self, field_name, value)
            elif isinstance(field_obj, SubConfigDescriptor):
                if field_name in kwargs:
                    value = kwargs[field_name]
                else:
                    # Create empty sub-config
                    value = field_obj.config_class()
                setattr(self, field_name, value)

        # Set any additional kwargs not in fields
        for name, value in kwargs.items():
            if name not in self.__config_fields__:
                setattr(self, name, value)

    def __repr__(self) -> str:
        values = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"<{self.__class__.__name__} {values}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and vars(self) == vars(other)

    @classmethod
    def from_data(cls, inputs: Inputs) -> Self:
        return cls(**inputs[0])  # type: ignore[arg-type]  # todo: normalize inputs


__all__ = [
    "Config",
    "ConfigMeta",
    "field",
    "from_parent",
    "sub_config",
    "FieldDescriptor",
    "SubConfigDescriptor",
    "FromParentMarker",
    "Origin",
    "InputData",
    "Inputs",
    "NormalizedInputs",
]
