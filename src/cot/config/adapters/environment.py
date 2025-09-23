"""Environment variable adapter for configuration."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from .._name_mapping import field_to_env_name
from ..descriptors import FieldDescriptor, SubConfigDescriptor

if TYPE_CHECKING:
    from .. import Config


class EnvironmentAdapter:
    """Adapter to load configuration from environment variables."""

    def __init__(
        self,
        config_class: type[Config],
        env_prefix: str | None = None,
        load_json: bool = True,
        load_toml: bool = False,
    ):
        """
        Initialize the environment adapter.

        :param config_class: The Config class to adapt
        :param env_prefix: Global prefix for all environment variables
        :param load_json: Parse JSON strings from environment variables
        :param load_toml: Parse TOML strings from environment variables
        """
        self.config_class = config_class
        self.env_prefix = env_prefix or config_class.__config_prefix__
        self.load_json = load_json
        self.load_toml = load_toml

    def extract_config(self, environ: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Extract configuration from environment variables.

        :param environ: Environment dictionary (defaults to os.environ)
        :returns: Dictionary of configuration values
        """
        if environ is None:
            environ = dict(os.environ)

        config_data: dict[str, Any] = {}

        for field_name, field_obj in self.config_class.__config_fields__.items():
            if isinstance(field_obj, FieldDescriptor):
                value = self._get_field_from_env(environ, field_name, field_obj)
                if value is not None:
                    config_data[field_name] = value

            elif isinstance(field_obj, SubConfigDescriptor):
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
            primary_field = subconfig.config_class.__config_fields__.get(
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
        ) in subconfig.config_class.__config_fields__.items():
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

        :param raw_value: Raw string from environment
        :param field: Field descriptor with metadata
        :returns: Parsed value
        """
        # Handle empty strings
        if not raw_value:
            return None

        # Handle boolean strings first
        if raw_value.lower() in ("true", "yes", "1", "on"):
            return True
        elif raw_value.lower() in ("false", "no", "0", "off"):
            return False

        # Try to parse as JSON if enabled
        if self.load_json:
            try:
                return json.loads(raw_value)
            except (json.JSONDecodeError, ValueError):
                pass

        # Try to parse as TOML if enabled
        if self.load_toml:
            try:
                try:
                    import tomllib  # type: ignore
                except ImportError:
                    import tomli as tomllib  # type: ignore

                # TOML requires key-value format
                toml_str = f"value = {raw_value}"
                parsed = tomllib.loads(toml_str)
                return parsed.get("value")
            except Exception:
                pass

        # Handle list fields with action="append"
        if field.action == "append":
            # Split by comma or semicolon
            if "," in raw_value:
                return [v.strip() for v in raw_value.split(",")]
            elif ";" in raw_value:
                return [v.strip() for v in raw_value.split(";")]
            else:
                return [raw_value]

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

        for field_name, field_obj in self.config_class.__config_fields__.items():
            if isinstance(field_obj, FieldDescriptor):
                env_name = field_to_env_name(field_name, self.env_prefix)
                mapping[field_name] = env_name

            elif isinstance(field_obj, SubConfigDescriptor):
                # Primary field
                if field_obj.primary:
                    env_name = field_to_env_name(field_name, self.env_prefix)
                    mapping[f"{field_name}.{field_obj.primary}"] = env_name

                # Other fields
                for sub_field_name in field_obj.config_class.__config_fields__:
                    if sub_field_name != field_obj.primary:
                        prefixed_name = f"{field_name}_{sub_field_name}"
                        env_name = field_to_env_name(prefixed_name, self.env_prefix)
                        mapping[f"{field_name}.{sub_field_name}"] = env_name

        return mapping
