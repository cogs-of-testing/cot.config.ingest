"""Argparse adapter for configuration."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

from .._name_mapping import field_to_cli_name
from ..descriptors import FieldDescriptor, SubConfigDescriptor

if TYPE_CHECKING:
    from .. import Config


class ConfigToArgparseAdapter:
    """Adapter to register Config classes with argparse ArgumentParser."""

    def __init__(self, config_class: type[Config]):
        """
        Initialize the adapter.

        Args:
            config_class: The Config class to adapt
        """
        self.config_class = config_class
        self.prefix = config_class.__config_prefix__

    def add_to_parser(
        self,
        parser: argparse.ArgumentParser,
        group_name: str | None = None,
    ) -> None:
        """
        Register the configuration with an ArgumentParser.

        Args:
            parser: The ArgumentParser instance
            group_name: Optional group name for options
        """
        group = parser.add_argument_group(group_name) if group_name else parser

        # Process each field in the config
        for field_name, field_obj in self.config_class.__config_fields__.items():
            if isinstance(field_obj, FieldDescriptor):
                self._add_field_to_parser(group, field_name, field_obj)
            elif isinstance(field_obj, SubConfigDescriptor):
                self._add_subconfig_to_parser(parser, group, field_name, field_obj)

    def _add_field_to_parser(
        self,
        group: argparse.ArgumentParser | argparse._ArgumentGroup,
        field_name: str,
        field: FieldDescriptor,
    ) -> None:
        """Add a single field to the parser."""
        cli_name = field_to_cli_name(field_name, self.prefix)
        dest = self._field_to_dest(field_name)

        kwargs: dict[str, Any] = {
            "dest": dest,
            "help": field.help,
        }

        # Handle different field types
        if field.action:
            kwargs["action"] = field.action
            if field.action == "append":
                kwargs["default"] = field.get_default() or []
            elif field.action in ("store_true", "store_false"):
                # Boolean flags don't take values
                pass
            else:
                kwargs["default"] = field.get_default()
        else:
            kwargs["default"] = field.get_default()
            if field.metavar:
                kwargs["metavar"] = field.metavar
            if field.choices:
                kwargs["choices"] = field.choices

            # Add type conversion based on default value
            default_val = field.get_default()
            if default_val is not None:
                if isinstance(default_val, int):
                    kwargs["type"] = int
                elif isinstance(default_val, float):
                    kwargs["type"] = float

        # Handle required fields
        if field.required:
            kwargs["required"] = True

        group.add_argument(cli_name, **kwargs)

    def _add_subconfig_to_parser(
        self,
        parser: argparse.ArgumentParser,
        group: argparse.ArgumentParser | argparse._ArgumentGroup,
        field_name: str,
        subconfig: SubConfigDescriptor,
    ) -> None:
        """Add a sub-configuration to the parser."""
        # If there's a primary field, add it with the sub-config's name
        if subconfig.primary:
            primary_field = subconfig.config_class.__config_fields__.get(
                subconfig.primary
            )
            if isinstance(primary_field, FieldDescriptor):
                # Add the primary field with the sub-config's name
                self._add_field_to_parser(group, field_name, primary_field)

        # Add all fields from sub-config with prefixed names
        sub_fields = subconfig.config_class.__config_fields__.items()
        for sub_field_name, sub_field in sub_fields:
            if isinstance(sub_field, FieldDescriptor):
                # Skip the primary field if already added
                if sub_field_name == subconfig.primary:
                    continue

                # Create prefixed name
                prefixed_name = f"{field_name}_{sub_field_name}"
                self._add_field_to_parser(group, prefixed_name, sub_field)

    def _field_to_dest(self, field_name: str) -> str:
        """Convert field name to destination variable name."""
        if self.prefix:
            return f"{self.prefix}_{field_name}"
        return field_name

    def extract_config(self, args: argparse.Namespace) -> dict[str, Any]:
        """
        Extract configuration values from parsed arguments.

        Args:
            args: Parsed arguments from argparse

        Returns:
            Dictionary of configuration values
        """
        config_data: dict[str, Any] = {}

        for field_name, field_obj in self.config_class.__config_fields__.items():
            dest = self._field_to_dest(field_name)

            if hasattr(args, dest):
                value = getattr(args, dest)
                # Only include values that differ from the default
                if isinstance(field_obj, FieldDescriptor):
                    default_value = field_obj.get_default()
                    if value != default_value:
                        config_data[field_name] = value
                elif value is not None:
                    config_data[field_name] = value

            # Handle sub-configs
            if isinstance(field_obj, SubConfigDescriptor):
                sub_data: dict[str, Any] = {}

                # Check for primary field
                if field_obj.primary:
                    primary_dest = self._field_to_dest(field_name)
                    if hasattr(args, primary_dest):
                        value = getattr(args, primary_dest)
                        if value is not None:
                            sub_data[field_obj.primary] = value

                # Check for prefixed fields
                for sub_field_name in field_obj.config_class.__config_fields__:
                    if sub_field_name == field_obj.primary:
                        continue

                    prefixed_name = f"{field_name}_{sub_field_name}"
                    prefixed_dest = self._field_to_dest(prefixed_name)

                    if hasattr(args, prefixed_dest):
                        value = getattr(args, prefixed_dest)
                        if value is not None:
                            sub_data[sub_field_name] = value

                if sub_data:
                    config_data[field_name] = field_obj.config_class(**sub_data)

        return config_data

    def create_parser(
        self,
        prog: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> argparse.ArgumentParser:
        """
        Create a new ArgumentParser with the config registered.

        Args:
            prog: Program name
            description: Program description
            **kwargs: Additional ArgumentParser arguments

        Returns:
            Configured ArgumentParser
        """
        parser = argparse.ArgumentParser(prog=prog, description=description, **kwargs)
        self.add_to_parser(parser)
        return parser