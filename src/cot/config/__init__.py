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


class FieldsConfig(dict[str, FieldDescriptor | SubConfigDescriptor]):
    """Container for config fields with prefix information."""

    def __init__(
        self,
        fields: dict[str, FieldDescriptor | SubConfigDescriptor],
        prefix: str | None = None,
    ):
        """
        Initialize FieldsConfig.

        :param fields: Dictionary of field descriptors
        :param prefix: Optional prefix for this config
        """
        super().__init__(fields)
        self.prefix = prefix


def get_fields_config(config_class: type) -> FieldsConfig:
    """
    Get the FieldsConfig from a Config class.

    :param config_class: The Config class to extract from
    :returns: FieldsConfig instance
    """
    return config_class._get_fields_config()  # type: ignore[attr-defined, no-any-return]


@typing_extensions.dataclass_transform()
class Config:
    """Base class for configuration objects."""

    __fields_config: ClassVar[FieldsConfig] = FieldsConfig({})

    @classmethod
    def _get_fields_config(cls) -> FieldsConfig:
        """
        Get the FieldsConfig for this class.

        Helper to avoid name mangling issues when accessing from other classes.
        """
        return cls.__fields_config

    def __init_subclass__(cls, prefix: str | None = None, **kwargs: Any) -> None:
        """Process configuration class at definition time."""
        super().__init_subclass__(**kwargs)

        # Collect field descriptors from bases and current class
        fields: dict[str, FieldDescriptor | SubConfigDescriptor] = {}

        # Inherit fields from base classes
        for base in cls.__mro__[1:]:  # Skip cls itself
            base_fields_config = getattr(base, "_Config__fields_config", None)
            if base_fields_config is not None:
                # Add base fields that aren't overridden
                for name, field_obj in base_fields_config.items():
                    if name not in fields:
                        fields[name] = field_obj

        # Process current class - look for field descriptors
        for name, value in cls.__dict__.items():
            if isinstance(value, FieldDescriptor | SubConfigDescriptor):
                fields[name] = value
                # Set the name on the descriptor
                if isinstance(value, FieldDescriptor):
                    value.name = name
                elif isinstance(value, SubConfigDescriptor):
                    value.name = name
                    # Handle forward references
                    if value.config_class is type:
                        # This will be resolved later
                        pass

        # Store fields and prefix in FieldsConfig (using mangled name)
        cls.__fields_config = FieldsConfig(fields, prefix)

        # Call __set_name__ on all fields to finalize them
        for field_name, field_obj in fields.items():
            if hasattr(field_obj, "__set_name__"):
                field_obj.__set_name__(cls, field_name)

    def __init__(self, **kwargs: Any):
        # Phase 1: Initialize all regular fields (not sub-configs)
        for field_name, field_obj in self.__fields_config.items():
            if isinstance(field_obj, FieldDescriptor):
                if field_name in kwargs:
                    value = field_obj.validate(kwargs[field_name])
                else:
                    value = field_obj.get_default()
                setattr(self, field_name, value)

        # Phase 2: Initialize sub-configs (after all parent fields are set)
        # This ensures parent values are available for propagation
        for field_name, field_obj in self.__fields_config.items():
            if isinstance(field_obj, SubConfigDescriptor):
                if field_name in kwargs:
                    value = kwargs[field_name]
                    # Convert dict to sub-config instance if needed
                    if isinstance(value, dict):
                        # Merge parent values into sub-config kwargs
                        sub_kwargs = self._merge_parent_values(
                            value, field_obj.config_class
                        )
                        value = field_obj.config_class(**sub_kwargs)
                    # If it's already an instance, use as-is
                else:
                    # Create sub-config with parent values
                    sub_kwargs = self._merge_parent_values({}, field_obj.config_class)
                    value = field_obj.config_class(**sub_kwargs)

                setattr(self, field_name, value)

        # Phase 3: Set any additional kwargs not in fields
        for name, value in kwargs.items():
            if name not in self.__fields_config:
                setattr(self, name, value)

    def __repr__(self) -> str:
        values = ", ".join(f"{k}={v!r}" for k, v in vars(self).items())
        return f"<{self.__class__.__name__} {values}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__) and vars(self) == vars(other)

    def _merge_parent_values(
        self, sub_kwargs: dict[str, Any], sub_config_class: type[Config]
    ) -> dict[str, Any]:
        """
        Merge parent values into sub-config kwargs for fields marked with from_parent.

        :param sub_kwargs: Explicit kwargs provided for the sub-config
        :param sub_config_class: The sub-configuration class
        :returns: Updated kwargs with from_parent values from parent config
        """
        # Start with provided kwargs
        result = sub_kwargs.copy()

        # Get sub-config's field descriptors
        sub_fields = sub_config_class._get_fields_config()

        # Process all from_parent fields
        for field_name, field_obj in sub_fields.items():
            if (
                isinstance(field_obj, FieldDescriptor)
                and field_obj.from_parent
                and field_name not in result
                and hasattr(self, field_name)
            ):
                # This field should get its value from parent
                # Look for the value in the parent (self)
                parent_value = getattr(self, field_name)
                result[field_name] = parent_value

        return result

    @classmethod
    def from_data(
        cls, *sources: dict[str, Any] | tuple[Origin, dict[str, Any]]
    ) -> Self:
        """
        Create a Config instance from multiple data sources.

        :param sources: Variable number of data sources. Each can be:

            - A dictionary of configuration data
            - A tuple of (origin, data) where origin describes the source

        :returns: Config instance with merged data from all sources

        .. note::
            Sources are merged in order, with later sources overriding earlier ones.
        """
        merged_data: dict[str, Any] = {}

        for source in sources:
            if isinstance(source, tuple):
                _origin, data = source
            else:
                data = source

            # Deep merge the data
            cls._merge_data(merged_data, data)

        return cls(**merged_data)

    @classmethod
    def _merge_data(cls, target: dict[str, Any], source: dict[str, Any]) -> None:
        """Deep merge source dictionary into target dictionary."""
        for key, value in source.items():
            if key in target:
                # If both values are dicts, merge them
                if isinstance(target[key], dict) and isinstance(value, dict):
                    cls._merge_data(target[key], value)
                else:
                    # Otherwise, override with new value
                    target[key] = value
            else:
                target[key] = value

    @classmethod
    def from_files(cls, *paths: Path | str) -> Self:
        """
        Load configuration from multiple files.

        :param paths: File paths to load configuration from
        :returns: Config instance with merged data from all files
        """
        from .loaders import load_file  # Avoid circular import

        sources = []
        for path in paths:
            if Path(path).exists():
                data = load_file(path)
                sources.append((str(path), data))

        return cls.from_data(*sources)




__all__ = [
    "Config",
    "FieldsConfig",
    "get_fields_config",
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
