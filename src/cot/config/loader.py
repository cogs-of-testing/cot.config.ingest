"""Configuration loader with source tracking and debugging capabilities."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from typing_extensions import Self

from ._name_mapping import field_to_cli_name
from .adapters.argparse import ConfigToArgparseAdapter
from .adapters.environment import EnvironmentAdapter
from .loaders import load_file
from .source_info import ConfigDebugInfo, SourceType

if TYPE_CHECKING:
    from . import Config

ConfigType = TypeVar("ConfigType", bound="Config")


class ConfigLoader(Generic[ConfigType]):
    """
    Loader for configuration from multiple sources with tracking.

    This class manages loading configuration from files, environment variables,
    and command-line arguments while tracking the source of each value for
    debugging purposes.
    """

    def __init__(
        self,
        config_class: type[ConfigType],
        *,
        env_prefix: str | None = None,
        enable_env: bool = True,
        enable_cli: bool = True,
        debug: bool = False,
    ):
        """
        Initialize the configuration loader.

        :param config_class: The Config class to load
        :param env_prefix: Prefix for environment variables
        :param enable_env: Whether to load from environment variables
        :param enable_cli: Whether to support CLI arguments
        :param debug: Enable debug tracking of sources
        """
        self.config_class = config_class
        self.env_prefix = env_prefix or config_class._get_fields_config().prefix
        self.enable_env = enable_env
        self.enable_cli = enable_cli
        self.debug = debug

        # Debug information
        self._debug_info = ConfigDebugInfo() if debug else None

        # Loaded data from different sources
        self._file_data: dict[str, Any] = {}
        self._env_data: dict[str, Any] = {}
        self._cli_data: dict[str, Any] = {}
        self._code_data: dict[str, Any] = {}

        # Adapters
        self._env_adapter: EnvironmentAdapter | None = None
        self._cli_adapter: ConfigToArgparseAdapter | None = None
        self._cli_parser: argparse.ArgumentParser | None = None

    def load_file(
        self,
        path: Path | str,
        *,
        required: bool = True,
        merge: bool = True,
    ) -> Self:
        """
        Load configuration from a file.

        :param path: Path to the configuration file
        :param required: Whether the file must exist
        :param merge: Whether to merge with existing file data
        :returns: Self for chaining
        """
        path = Path(path)

        if not path.exists():
            if required:
                raise FileNotFoundError(f"Configuration file not found: {path}")
            return self

        data = load_file(path)

        if merge:
            self._merge_data(self._file_data, data)
        else:
            self._file_data = data

        if self._debug_info:
            self._debug_info.add_source(SourceType.FILE, str(path))

        return self

    def load_files(self, *paths: Path | str, required: bool = False) -> Self:
        """
        Load configuration from multiple files.

        :param paths: Paths to configuration files
        :param required: Whether files must exist
        :returns: Self for chaining
        """
        for path in paths:
            self.load_file(path, required=required)
        return self

    def load_env(self, environ: dict[str, str] | None = None) -> Self:
        """
        Load configuration from environment variables.

        :param environ: Environment dictionary (defaults to os.environ)
        :returns: Self for chaining
        """
        if not self.enable_env:
            return self

        if self._env_adapter is None:
            self._env_adapter = EnvironmentAdapter(
                self.config_class,
                env_prefix=self.env_prefix,
            )

        self._env_data = self._env_adapter.extract_config(environ)

        if self._debug_info:
            self._debug_info.add_source(SourceType.ENV, "environment")

        return self

    def load_cli(
        self,
        args: list[str] | None = None,
        *,
        parser: argparse.ArgumentParser | None = None,
    ) -> Self:
        """
        Load configuration from command-line arguments.

        :param args: Arguments to parse (defaults to sys.argv)
        :param parser: Custom ArgumentParser to use
        :returns: Self for chaining
        """
        if not self.enable_cli:
            return self

        if parser is None:
            parser = self.get_cli_parser()

        parsed_args = parser.parse_args(args)

        if self._cli_adapter is None:
            self._cli_adapter = ConfigToArgparseAdapter(self.config_class)

        self._cli_data = self._cli_adapter.extract_config(parsed_args)

        if self._debug_info:
            self._debug_info.add_source(SourceType.CLI, "command-line")

        return self

    def set_values(self, **values: Any) -> Self:
        """
        Set configuration values programmatically.

        :param values: Configuration values to set
        :returns: Self for chaining
        """
        self._merge_data(self._code_data, values)

        if self._debug_info:
            self._debug_info.add_source(SourceType.CODE, "set_values()")

        return self

    def get_cli_parser(
        self,
        prog: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> argparse.ArgumentParser:
        """
        Get or create the ArgumentParser for CLI configuration.

        :param prog: Program name
        :param description: Program description
        :param kwargs: Additional ArgumentParser arguments
        :returns: Configured ArgumentParser
        """
        if self._cli_parser is None:
            if self._cli_adapter is None:
                self._cli_adapter = ConfigToArgparseAdapter(self.config_class)

            self._cli_parser = self._cli_adapter.create_parser(
                prog=prog,
                description=description,
                **kwargs,
            )

        return self._cli_parser

    def build(self) -> ConfigType:
        """
        Build the configuration instance from all loaded sources.

        :returns: Configured instance with all sources merged
        """
        # Merge all data sources in order of precedence
        merged_data: dict[str, Any] = {}

        # Process each source and track origins if debugging
        for source_type, source_data in [
            (SourceType.FILE, self._file_data),
            (SourceType.ENV, self._env_data),
            (SourceType.CODE, self._code_data),
            (SourceType.CLI, self._cli_data),
        ]:
            if source_data:
                if self._debug_info:
                    self._track_source_values(merged_data, source_data, source_type)
                self._merge_data(merged_data, source_data)

        # Create the config instance
        config = self.config_class(**merged_data)

        # Attach debug info if enabled
        if self._debug_info:
            # Track default values
            self._track_defaults(config, merged_data)
            # Attach debug info to the instance as private attribute
            object.__setattr__(config, "_debug_info", self._debug_info)

        return config

    def _track_source_values(
        self,
        current_data: dict[str, Any],
        new_data: dict[str, Any],
        source_type: SourceType,
        prefix: str = "",
    ) -> None:
        """Recursively track the source of configuration values.

        This mirrors the deep-merge semantics used by `_merge_data` and records
        provenance for nested fields using dotted paths (e.g. "db.host").
        """
        if not self._debug_info:
            return

        # Prepare mappings/fallbacks once
        env_names = None
        if source_type == SourceType.ENV and self._env_adapter:
            env_names = self._env_adapter.get_env_var_names()

        cli_prefix = None
        if source_type == SourceType.CLI:
            # Ensure we have an adapter to determine prefix used for CLI names
            if self._cli_adapter is None:
                self._cli_adapter = ConfigToArgparseAdapter(self.config_class)
            cli_prefix = self._cli_adapter.prefix

        for key, value in new_data.items():
            field_path = f"{prefix}.{key}" if prefix else key

            # If the new value is a dict, recurse to record leaf provenance
            if isinstance(value, dict):
                curr_sub = (
                    current_data.get(key, {}) if isinstance(current_data, dict) else {}
                )
                if not isinstance(curr_sub, dict):
                    curr_sub = {}
                self._track_source_values(
                    curr_sub, value, source_type, prefix=field_path
                )
                continue

            # If the adapter returned a sub-config instance (e.g. EnvironmentAdapter
            # creates subconfig objects), convert it to a mapping and recurse so we
            # can record nested field provenance (e.g. "db.host").
            if not isinstance(value, dict):
                value_cls = getattr(value, "__class__", None)
                fields_cfg = getattr(value_cls, "_get_fields_config", None)
                if callable(fields_cfg):
                    try:
                        sub_fields = value.__class__._get_fields_config()
                    except Exception:
                        sub_fields = None
                    if sub_fields:
                        sub_map: dict[str, Any] = {}
                        # Only include fields that differ from their descriptor defaults
                        from .descriptors import FieldDescriptor

                        for sub_name, sub_field_obj in sub_fields.items():
                            if hasattr(value, sub_name) and isinstance(
                                sub_field_obj, FieldDescriptor
                            ):
                                val = getattr(value, sub_name)
                                default_val = sub_field_obj.get_default()
                                # Treat default (including None) as "not
                                # provided" by the source
                                if val != default_val:
                                    sub_map[sub_name] = val

                        if sub_map:
                            curr_sub = (
                                current_data.get(key, {})
                                if isinstance(current_data, dict)
                                else {}
                            )
                            self._track_source_values(
                                curr_sub, sub_map, source_type, prefix=field_path
                            )
                            continue

            # Determine location based on source type
            location = None
            if source_type == SourceType.ENV:
                if env_names is None and self._env_adapter:
                    env_names = self._env_adapter.get_env_var_names()
                if env_names:
                    location = env_names.get(field_path)
            elif source_type == SourceType.CLI:
                # CLI names for sub-fields use underscores: e.g. db.host -> db_host
                prefixed_name = field_path.replace(".", "_")
                location = field_to_cli_name(prefixed_name, cli_prefix)

            self._debug_info.set_value(
                field_name=field_path,
                value=value,
                source_type=source_type,
                location=location,
                is_default=False,
            )

    def _track_defaults(self, config: Config, merged_data: dict[str, Any]) -> None:
        """Track default values that weren't overridden."""
        if not self._debug_info:
            return

        for field_name, field_obj in config._get_fields_config().items():
            if field_name not in merged_data:
                # This field is using its default value
                from .descriptors import FieldDescriptor

                if isinstance(field_obj, FieldDescriptor):
                    default_value = field_obj.get_default()
                    source_type = (
                        SourceType.DEFAULT_FACTORY
                        if field_obj.default_factory
                        else SourceType.DEFAULT
                    )

                    self._debug_info.set_value(
                        field_name=field_name,
                        value=default_value,
                        source_type=source_type,
                        is_default=True,
                    )

    def _merge_data(self, target: dict[str, Any], source: dict[str, Any]) -> None:
        """Deep merge source dictionary into target dictionary."""

        def to_mapping(val: Any) -> Any:
            """
            Convert sub-config instances to dicts for merging,
            otherwise return as-is.
            """
            # If it's already a dict, use it
            if isinstance(val, dict):
                return val

            # If it's a config-like instance, convert to dict of its fields
            val_cls = getattr(val, "__class__", None)
            if val_cls is not None and hasattr(val_cls, "_get_fields_config"):
                try:
                    fields = val.__class__._get_fields_config()
                except Exception:
                    fields = None

                if fields:
                    result: dict[str, Any] = {}
                    for sub_name in fields:
                        if hasattr(val, sub_name):
                            result[sub_name] = getattr(val, sub_name)
                    return result

            return val

        for key, value in source.items():
            if key in target:
                tval = target[key]
                sval = value

                tmap = to_mapping(tval)
                smap = to_mapping(sval)

                # If both sides are mappings, merge recursively
                if isinstance(tmap, dict) and isinstance(smap, dict):
                    # Merge while treating explicit None in source as "not provided"
                    # when a target value already exists. This handles adapters
                    # that construct sub-config instances with missing fields set
                    # to their default (often None) so they don't wipe file data.
                    for sub_k, sub_v in smap.items():
                        if sub_v is None and sub_k in tmap and tmap[sub_k] is not None:
                            # Skip overriding with None (treat as absent)
                            continue

                        if (
                            sub_k in tmap
                            and isinstance(tmap[sub_k], dict)
                            and isinstance(sub_v, dict)
                        ):
                            self._merge_data(tmap[sub_k], sub_v)
                        else:
                            tmap[sub_k] = sub_v

                    # Ensure merged mapping is placed back into target
                    target[key] = tmap
                else:
                    # Otherwise, override with new value
                    target[key] = value
            else:
                target[key] = value

    def get_debug_report(self) -> str:
        """
        Get a debug report of configuration sources.

        :returns: Human-readable debug report
        :raises RuntimeError: If debug mode is not enabled
        """
        if not self._debug_info:
            raise RuntimeError(
                "Debug mode is not enabled. Set debug=True in ConfigLoader"
            )

        return self._debug_info.generate_report()


class LazyConfigLoader(Generic[ConfigType]):
    """
    Lazy configuration loader that defers loading until accessed.

    This is useful for applications that want to set up configuration
    loading but defer the actual loading until needed.
    """

    def __init__(self, config_class: type[ConfigType], **kwargs: Any):
        """
        Initialize the lazy loader.

        :param config_class: The Config class to load
        :param kwargs: Arguments for ConfigLoader
        """
        self.config_class = config_class
        self.loader_kwargs = kwargs
        self._loader: ConfigLoader[ConfigType] | None = None
        self._config: ConfigType | None = None

    def get_loader(self) -> ConfigLoader[ConfigType]:
        """Get or create the ConfigLoader instance."""
        if self._loader is None:
            self._loader = ConfigLoader(self.config_class, **self.loader_kwargs)
        return self._loader

    def get_config(self) -> ConfigType:
        """Get the configuration instance, loading if necessary."""
        if self._config is None:
            self._config = self.get_loader().build()
        return self._config

    def reset(self) -> None:
        """Reset the loader and configuration."""
        self._loader = None
        self._config = None
