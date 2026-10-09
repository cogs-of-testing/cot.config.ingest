# Changelog

This project is experimental. Until it reaches 1.0 the API may change in any
release, and breaking changes are noted here rather than deprecated.

<!-- towncrier release notes start -->

## 0.3.0 (2026-10-09)

### Added

- Added `add_config(parser, T, adopt=True)`: a plugin that replaces one of pytest's own can read the command-line options pytest already declared instead of failing with `ConfigCollisionError` (P9).

## 0.2.0 (2026-10-06)

### Breaking Changes

- Renamed: `SubConfig` is `ConfigPart`, `AddoptsSource` is `InjectedArgsSource`, `Precedence.ADDOPTS` is `Precedence.INJECTED`, `addopts_field` is `injected_args`, and `EnvSource(parse_toml=True)` is `TomlEnvSource`.
- The core is rebuilt to `docs/design/` (D20). The pytest binding patches nothing and is not auto-enabled: the `pytest11` entry point and `cot.config.pytest_plugin` are gone. A plugin opts in with `add_config(parser, T)` in `pytest_addoption` and `get_config(config, T)` from `cot.config.pytest_binding`.

### Removed

- `DeclaringSource`, `Discoverable` and `OriginAware` are removed.

## 0.1.0 (2026-10-06)

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

[0.1.0]: https://github.com/cogs-of-testing/cot.config.ingest/commits/v0.1.0
