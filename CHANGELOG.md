# Changelog

This project is experimental. Until it reaches 1.0 the API may change in any
release, and breaking changes are noted here rather than deprecated.

## Unreleased

### Added

- `ConfigPart` / `SubConfig`: frozen, keyword-only configuration classes with a
  `@dataclass_transform` signature.
- Sources: `TomlSource`, `IniSource`, `CLISource`, `AddoptsSource`, `EnvSource`,
  `ConfigFileDiscoverySource`.
- Field markers usable as `Annotated[T, marker]` or `T @ marker`: `from_parent`,
  `named()`, `no_cli`, `help()`, `config_source`, `bootstrap_only`,
  `addopts_field`, `short()`; and the class keywords `prefix=` and
  `name_prefix=`.
- `declare()` / `resolve()` / `get()` lifecycle. Every pass runs for all declared
  types before the next begins, so declaration order does not change the result.
- Provenance: `origin_of()`, `origins()` and `explain()` report where each value
  came from, including values reached through the `from_parent` cascade.
- `format_help()` / `help_requested()`. Neither prints nor exits.
- `Precedence`, the default ladder `defaults(-1) < file(15) < addopts(18) <
  env(20) < cli(25)`. Every source and marker accepts `precedence=` to override
  it.
- pytest proof of concept (`cot.config.pytest_plugin`), auto-enabled through a
  `pytest11` entry point. **It monkeypatches pytest**; see the README.
- `cot.config.example_plugin`, a worked opt-in example.

[Unreleased]: https://github.com/cogs-of-testing/cot.config.ingest/commits/main
