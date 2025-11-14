"""Environment variable adapter for configuration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from .._name_mapping import field_to_env_name
from ..descriptors import FieldDescriptor, SubConfigDescriptor
from ._parsing import (
    ParseError,
    parse_boolean,
    parse_float,
    parse_int,
    parse_list,
    parse_toml,
)

if TYPE_CHECKING:
    from .. import Config


class EnvironmentAdapter:
    """Adapter to load configuration from environment variables."""

    def __init__(
        self,
        config_class: type[Config],
        env_prefix: str | None = None,
    ):
        """
        Initialize the environment adapter.

        :param config_class: The Config class to adapt
        :param env_prefix: Global prefix for all environment variables
        """
        self.config_class = config_class
        self.env_prefix = env_prefix or config_class._get_fields_config().prefix

    def extract_config(self, environ: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Extract configuration from environment variables.

        :param environ: Environment dictionary (defaults to os.environ)
        :returns: Dictionary of configuration values
        """
        if environ is None:
            environ = dict(os.environ)

        config_data: dict[str, Any] = {}

        for field_name, field_obj in self.config_class._get_fields_config().items():
            if isinstance(field_obj, FieldDescriptor):
                value = self._get_field_from_env(environ, field_name, field_obj)
                if value is not None:
                    config_data[field_name] = value

            else:
                assert isinstance(field_obj, SubConfigDescriptor)
                sub_data = self._get_subconfig_from_env(environ, field_name, field_obj)
                if sub_data:
                    config_data[field_name] = field_obj.config_class(**sub_data)

        return config_data

    def _get_field_from_env(
        self,
        environ: dict[str, str],
        field_name: str,
        field: FieldDescriptor,
    ) -> Any:
        """Get a single field value from environment."""
        env_name = field_to_env_name(field_name, self.env_prefix)

        if env_name not in environ:
            return None

        raw_value = environ[env_name]

        # Parse the value based on field type and settings
        return self._parse_env_value(raw_value, field)

    def _get_subconfig_from_env(
        self,
        environ: dict[str, str],
        field_name: str,
        subconfig: SubConfigDescriptor,
    ) -> dict[str, Any]:
        """Get sub-configuration from environment."""
        sub_data: dict[str, Any] = {}

        # Check for primary field
        if subconfig.primary:
            primary_field = subconfig.config_class._get_fields_config().get(
                subconfig.primary
            )
            if isinstance(primary_field, FieldDescriptor):
                value = self._get_field_from_env(environ, field_name, primary_field)
                if value is not None:
                    sub_data[subconfig.primary] = value

        # Check for prefixed fields
        for (
            sub_field_name,
            sub_field,
        ) in subconfig.config_class._get_fields_config().items():
            if sub_field_name == subconfig.primary:
                continue

            if isinstance(sub_field, FieldDescriptor):
                prefixed_name = f"{field_name}_{sub_field_name}"
                value = self._get_field_from_env(environ, prefixed_name, sub_field)
                if value is not None:
                    sub_data[sub_field_name] = value

        return sub_data

    def _parse_env_value(self, raw_value: str, field: FieldDescriptor) -> Any:
        """
        Parse environment variable value based on field metadata.

        Orchestrates parsing through specialized helper functions in order:
        1. Empty string handling
        2. Boolean parsing
        3. Integer parsing (if value looks like an integer)
        4. Float parsing (if value looks like a float)
        5. TOML parsing (always attempted)
        6. List parsing (for append-action fields)
        7. Choices validation
        8. String return (default)

        :param raw_value: Raw string from environment
        :param field: Field descriptor with metadata
        :returns: Parsed value
        """
        # Handle empty strings
        if not raw_value:
            return None

        # Try boolean parsing first (handles common bool strings)
        bool_result = parse_boolean(raw_value)
        if bool_result is not None:
            return bool_result

        # Try integer parsing (for numeric strings)
        try:
            return parse_int(raw_value)
        except ParseError:
            pass

        # Try float parsing (for decimal numbers)
        try:
            return parse_float(raw_value)
        except ParseError:
            pass

        # Try TOML parsing (always enabled)
        try:
            return parse_toml(raw_value)
        except ParseError:
            pass

        # Handle list fields with action="append"
        if field.action == "append":
            return parse_list(raw_value)

        # Validate against choices
        if field.choices and raw_value not in field.choices:
            return None

        # Return as string by default
        return raw_value

    def get_env_var_names(self) -> dict[str, str]:
        """
        Get a mapping of field names to environment variable names.

        :returns: Dictionary mapping field names to env var names
        """
        mapping = {}

        for field_name, field_obj in self.config_class._get_fields_config().items():
            if isinstance(field_obj, FieldDescriptor):
                env_name = field_to_env_name(field_name, self.env_prefix)
                mapping[field_name] = env_name

            elif isinstance(field_obj, SubConfigDescriptor):
                # Primary field
                if field_obj.primary:
                    env_name = field_to_env_name(field_name, self.env_prefix)
                    mapping[f"{field_name}.{field_obj.primary}"] = env_name

                # Other fields
                for sub_field_name in field_obj.config_class._get_fields_config():
                    if sub_field_name != field_obj.primary:
                        prefixed_name = f"{field_name}_{sub_field_name}"
                        env_name = field_to_env_name(prefixed_name, self.env_prefix)
                        mapping[f"{field_name}.{sub_field_name}"] = env_name

        return mapping
