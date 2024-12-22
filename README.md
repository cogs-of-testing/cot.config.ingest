from email.policy import default

# cot.config.ingest

## goal

The goal of cot.config.ingest is to provide type annotations and helpers to ingest configuration from

* cli arguments (via argparse/click/others)
* environment variables
* configuration files of different formats/structures

It's a early experiment that may or may not fail.

## inspiring use case

pytest as of 2024 is suffering from the design of the configuration system
as cli args and ini options are handled differently.

Additionally, adding correct support for `pyproject.toml` data seems daunting.

### problem example

the following code snippet sets up the configuration options and cli arguments for the logging plugin


```python 

from pytest import Parser

DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"

def pytest_addoption(parser: Parser) -> None:
    """Add options to control log capturing."""
    group = parser.getgroup("logging")

    def add_option_ini(option, dest, default=None, type=None, **kwargs):
        parser.addini(
            dest, default=default, type=type, help="Default value for " + option
        )
        group.addoption(option, dest=dest, **kwargs)

    add_option_ini(
        "--log-level",
        dest="log_level",
        default=None,
        metavar="LEVEL",
        help=(
            "Level of messages to catch/display."
            " Not set by default, so it depends on the root/parent log handler's"
            ' effective level, where it is "WARNING" by default.'
        ),
    )
    add_option_ini(
        "--log-format",
        dest="log_format",
        default=DEFAULT_LOG_FORMAT,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-date-format",
        dest="log_date_format",
        default=DEFAULT_LOG_DATE_FORMAT,
        help="Log date format used by the logging module",
    )
    parser.addini(
        "log_cli",
        default=False,
        type="bool",
        help='Enable log display during test run (also known as "live logging")',
    )
    add_option_ini(
        "--log-cli-level", dest="log_cli_level", default=None, help="CLI logging level"
    )
    add_option_ini(
        "--log-cli-format",
        dest="log_cli_format",
        default=None,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-cli-date-format",
        dest="log_cli_date_format",
        default=None,
        help="Log date format used by the logging module",
    )
    add_option_ini(
        "--log-file",
        dest="log_file",
        default=None,
        help="Path to a file when logging will be written to",
    )
    add_option_ini(
        "--log-file-mode",
        dest="log_file_mode",
        default="w",
        choices=["w", "a"],
        help="Log file open mode",
    )
    add_option_ini(
        "--log-file-level",
        dest="log_file_level",
        default=None,
        help="Log file logging level",
    )
    add_option_ini(
        "--log-file-format",
        dest="log_file_format",
        default=None,
        help="Log format used by the logging module",
    )
    add_option_ini(
        "--log-file-date-format",
        dest="log_file_date_format",
        default=None,
        help="Log date format used by the logging module",
    )
    add_option_ini(
        "--log-auto-indent",
        dest="log_auto_indent",
        default=None,
        help="Auto-indent multiline messages passed to the logging module. Accepts true|on, false|off or an integer.",
    )
    group.addoption(
        "--log-disable",
        action="append",
        default=[],
        dest="logger_disable",
        help="Disable a logger by name. Can be passed multiple times.",
    )


```


### propose example
```python
from pathlib import Path
from typing import Literal

from pytest import Parser
from cot.config import Config, from_parent, sub_config, field 


DEFAULT_LOG_FORMAT = "%(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
DEFAULT_LOG_DATE_FORMAT = "%H:%M:%S"


class LogBaseConfig(Config):
    level: int | str | None = field(from_parent, default=None, help=(
            "Level of messages to catch/display."
            " Not set by default, so it depends on the root/parent log handler's"
            ' effective level, where it is "WARNING" by default.'
        ))
    date_format: str = field(from_parent, default=DEFAULT_LOG_DATE_FORMAT)
    format: str = field(from_parent, default=DEFAULT_LOG_FORMAT,
                        help="Log format used by the logging module")
    
class LogCliConfig(LogBaseConfig):
    enable: bool = field(help='Enable log display during test run (also known as "live logging")')
    
    
class LogFileConfig(LogCliConfig):
    path: Path | None = field(default=None)
    mode : Literal["w", "a"] = field(default="w")

    
class LogingPluginConfig(Config, LogBaseConfig, prefix="log"):
    cli: LogCliConfig = sub_config(primary=LogBaseConfig.enable)
    file: LogFileConfig = sub_config(primary=LogCliConfig.path)
    auto_indent: bool | int | None = field(default=None)
    disable: list[str] = field(default_factory=list)
    
    
def pytest_addoption(parser: Parser):
    parser.add_config(LogingPluginConfig)
    



```


### open questions

- [ ] mapping of prefixes/underscores and sbu-objects
- [ ] mapping of ini options
- [ ] ingestion of backward compatibility fields
- [ ] toml/yaml behaviours