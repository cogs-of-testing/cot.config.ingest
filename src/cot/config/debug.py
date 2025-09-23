"""Global debug functionality for configuration tracking."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .source_info import ConfigDebugInfo, ConfigValue

if TYPE_CHECKING:
    from . import Config


def get_debug_info(config: Config) -> ConfigDebugInfo | None:
    """
    Get debug information for a configuration instance.

    :param config: The configuration instance
    :returns: Debug information if available, None otherwise
    """
    return getattr(config, "_debug_info", None)


def get_value_source(config: Config, field_name: str) -> ConfigValue | None:
    """
    Get the source information for a specific configuration field.

    :param config: The configuration instance
    :param field_name: The name of the field
    :returns: ConfigValue with source information if available
    """
    debug_info = get_debug_info(config)
    if debug_info:
        return debug_info.get_value(field_name)
    return None


def get_config_report(config: Config) -> str:
    """
    Generate a debug report for a configuration instance.

    :param config: The configuration instance
    :returns: Human-readable debug report
    :raises ValueError: If no debug information is available
    """
    debug_info = get_debug_info(config)
    if not debug_info:
        raise ValueError(
            "No debug information available for this configuration. "
            "Ensure the ConfigLoader was created with debug=True"
        )
    return debug_info.generate_report()


def get_non_default_values(config: Config) -> dict[str, Any]:
    """
    Get all configuration values that are not using defaults.

    :param config: The configuration instance
    :returns: Dictionary of field names to values for non-default values
    """
    debug_info = get_debug_info(config)
    if not debug_info:
        return {}

    result = {}
    for field_name, config_value in debug_info.get_non_default_values().items():
        result[field_name] = getattr(config, field_name, config_value.value)
    return result


def get_overridden_values(config: Config) -> dict[str, Any]:
    """
    Get all configuration values that were overridden from previous sources.

    :param config: The configuration instance
    :returns: Dictionary of field names to values for overridden values
    """
    debug_info = get_debug_info(config)
    if not debug_info:
        return {}

    result = {}
    for field_name, config_value in debug_info.get_overridden_values().items():
        result[field_name] = getattr(config, field_name, config_value.value)
    return result


def is_default(config: Config, field_name: str) -> bool:
    """
    Check if a configuration field is using its default value.

    :param config: The configuration instance
    :param field_name: The name of the field
    :returns: True if the field is using its default value
    """
    value_info = get_value_source(config, field_name)
    if value_info:
        return value_info.is_default()

    # If no debug info, we can't determine
    return False


def was_overridden(config: Config, field_name: str) -> bool:
    """
    Check if a configuration field was overridden from a previous source.

    :param config: The configuration instance
    :param field_name: The name of the field
    :returns: True if the field was overridden
    """
    value_info = get_value_source(config, field_name)
    if value_info:
        return value_info.was_overridden()
    return False


def get_load_order(config: Config) -> list[tuple[str, str | None]]:
    """
    Get the order in which configuration sources were loaded.

    :param config: The configuration instance
    :returns: List of (source_type, location) tuples
    """
    debug_info = get_debug_info(config)
    if not debug_info:
        return []

    return [(st.value, loc) for st, loc in debug_info.get_load_order()]


def get_source_location(config: Config, field_name: str) -> str | None:
    """
    Get the location where a configuration value came from.

    :param config: The configuration instance
    :param field_name: The name of the field
    :returns: Location string (file path, env var name, etc.) or None
    """
    value_info = get_value_source(config, field_name)
    if value_info:
        return value_info.source.location
    return None


def get_override_chain(config: Config, field_name: str) -> list[str]:
    """
    Get the chain of overrides for a configuration field.

    :param config: The configuration instance
    :param field_name: The name of the field
    :returns: List of source descriptions from most recent to oldest
    """
    value_info = get_value_source(config, field_name)
    if value_info:
        return [str(source) for source in value_info.source.get_override_chain()]
    return []