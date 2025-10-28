"""Pytest configuration adapter for mapping Config classes to pytest options."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .._name_mapping import field_to_cli_name
from ..descriptors import FieldDescriptor, SubConfigDescriptor

if TYPE_CHECKING:
    from .. import Config


class Parser(Protocol):
    """Protocol for pytest Parser interface."""

    def addini(
        self,
        name: str,
        default: Any = None,
        type: str | None = None,
        help: str | None = None,
    ) -> None:
        """Add an ini option."""
        ...

    def getgroup(self, name: str) -> Any:
        """Get or create an option group."""
        ...

    def addoption(
        self,
        *names: str,
        dest: str | None = None,
        default: Any = None,
        action: str | None = None,
        choices: list[Any] | None = None,
        help: str | None = None,
        metavar: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Add a command line option."""
        ...


class ConfigToPytestAdapter:
    """Adapter to register Config classes with pytest's Parser."""

    def __init__(self, config_class: type[Config]):
        """
        Initialize the adapter.

        :param config_class: The Config class to adapt
        """
        self.config_class = config_class
        self.prefix = config_class._get_fields_config().prefix

    def add_to_parser(self, parser: Parser, group_name: str | None = None) -> None:
        """
        Register the configuration with a pytest Parser.

        :param parser: The pytest Parser instance
        :param group_name: Optional group name for options
        """
        group = parser.getgroup(group_name) if group_name else parser

        # Process each field in the config
        for field_name, field_obj in self.config_class._get_fields_config().items():
            if isinstance(field_obj, FieldDescriptor):
                self._add_field_to_parser(parser, group, field_name, field_obj)
            elif isinstance(field_obj, SubConfigDescriptor):
                self._add_subconfig_to_parser(parser, group, field_name, field_obj)

    def _add_field_to_parser(
        self,
        parser: Parser,
        group: Any,
        field_name: str,
        field: FieldDescriptor,
    ) -> None:
        """Add a single field to the parser."""
        # Convert field name to CLI option
        cli_name = self._field_to_cli_name(field_name)
        ini_name = self._field_to_ini_name(field_name)

        # Get the default value
        default = field.get_default()

        # Determine if this should be both CLI and ini option
        if field.action == "append":
            # List fields are CLI-only with append action
            if hasattr(group, "addoption"):
                group.addoption(
                    cli_name,
                    dest=ini_name,
                    default=default if default is not None else [],
                    action="append",
                    help=field.help,
                    metavar=field.metavar,
                )
        else:
            # Add as both ini and CLI option
            parser.addini(
                ini_name,
                default=default,
                type=self._get_ini_type(field),
                help=f"Default value for {cli_name}" if not field.help else field.help,
            )

            if hasattr(group, "addoption"):
                group.addoption(
                    cli_name,
                    dest=ini_name,
                    default=default,
                    choices=field.choices,
                    help=field.help,
                    metavar=field.metavar,
                )

    def _add_subconfig_to_parser(
        self,
        parser: Parser,
        group: Any,
        field_name: str,
        subconfig: SubConfigDescriptor,
    ) -> None:
        """Add a sub-configuration to the parser."""
        # Sub-config adapter would be created here if needed
        # ConfigToPytestAdapter(subconfig.config_class)

        # If there's a primary field, handle it specially
        if subconfig.primary:
            primary_field = subconfig.config_class._get_fields_config().get(
                subconfig.primary
            )
            if isinstance(primary_field, FieldDescriptor):
                # Add the primary field with the sub-config's name
                cli_name = self._field_to_cli_name(field_name)
                ini_name = self._field_to_ini_name(field_name)

                parser.addini(
                    ini_name,
                    default=primary_field.get_default(),
                    type=self._get_ini_type(primary_field),
                    help=primary_field.help,
                )

                if hasattr(group, "addoption"):
                    group.addoption(
                        cli_name,
                        dest=ini_name,
                        default=primary_field.get_default(),
                        choices=primary_field.choices,
                        help=primary_field.help,
                        metavar=primary_field.metavar,
                    )

        # Add all fields from sub-config with prefixed names
        sub_fields = subconfig.config_class._get_fields_config().items()
        for sub_field_name, sub_field in sub_fields:
            if isinstance(sub_field, FieldDescriptor):
                # Skip the primary field if already added
                if sub_field_name == subconfig.primary:
                    continue

                # Create prefixed name
                prefixed_name = f"{field_name}_{sub_field_name}"
                self._add_field_to_parser(parser, group, prefixed_name, sub_field)

    def _field_to_cli_name(self, field_name: str) -> str:
        """Convert a field name to a CLI option name."""
        return field_to_cli_name(field_name, self.prefix)

    def _field_to_ini_name(self, field_name: str) -> str:
        """Convert a field name to an ini option name."""
        # Add prefix if configured
        if self.prefix:
            return f"{self.prefix}_{field_name}"
        return field_name

    def _get_ini_type(self, field: FieldDescriptor) -> str | None:
        """Determine the ini type for a field."""
        # This is a simplified version - could be enhanced with type hints
        if field.default is True or field.default is False:
            return "bool"
        return None

    def extract_config(self, parsed_args: Any) -> dict[str, Any]:
        """
        Extract configuration values from parsed arguments.

        :param parsed_args: Parsed arguments from pytest
        :returns: Dictionary of configuration values
        """
        config_data: dict[str, Any] = {}

        for field_name, field_obj in self.config_class._get_fields_config().items():
            ini_name = self._field_to_ini_name(field_name)

            if hasattr(parsed_args, ini_name):
                value = getattr(parsed_args, ini_name)
                if value is not None:
                    config_data[field_name] = value

            # Handle sub-configs
            if isinstance(field_obj, SubConfigDescriptor):
                sub_data: dict[str, Any] = {}

                # Check for primary field
                if field_obj.primary:
                    primary_ini = self._field_to_ini_name(field_name)
                    if hasattr(parsed_args, primary_ini):
                        value = getattr(parsed_args, primary_ini)
                        if value is not None:
                            sub_data[field_obj.primary] = value

                # Check for prefixed fields
                for sub_field_name in field_obj.config_class._get_fields_config():
                    if sub_field_name == field_obj.primary:
                        continue

                    prefixed_name = f"{field_name}_{sub_field_name}"
                    prefixed_ini = self._field_to_ini_name(prefixed_name)

                    if hasattr(parsed_args, prefixed_ini):
                        value = getattr(parsed_args, prefixed_ini)
                        if value is not None:
                            sub_data[sub_field_name] = value

                if sub_data:
                    config_data[field_name] = field_obj.config_class(**sub_data)

        return config_data
