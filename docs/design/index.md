# Design

The normative design of `cot.config.ingest`: what the library is meant to be,
why, and how it is built.

## The problem

An application that reads configuration from more than one place ends up
declaring each option more than once. pytest is the worked example: every
logging option exists as a CLI option and as an ini key, declared by two
different calls and reconciled by hand at read time:

```python
add_option_ini("--log-cli-level", dest="log_cli_level", default=None, ...)
...
level = get_option_ini(config, "log_cli_level", "log_level")   # by hand, per option
```

Ninety lines of `pytest_addoption` and a local helper produce thirteen ini keys
and thirteen options, with the fallback chains open-coded at each use site.
Adding `pyproject.toml` means a third mechanism.

Each source needs different things: a parser must be told an option exists
before it can parse it, a file needs a section and a key, an environment
variable needs a name. What is missing is a single declaration those three can
all be derived from.

## What this library is

A declaration of configuration structure, nested, typed and annotated, from
which every source-facing name is derived, and into which every source's values
are merged by a single precedence rule, with provenance recorded throughout.

```python
class LoggingConfig(ConfigPart, prefix="pytest", name_prefix="log"):
    level: str = "WARNING"
    cli: LogCliConfig
    file: LogFileConfig
```

That one declaration yields `--log-cli-level`, `log_cli_level`,
`PYTEST_LOG_CLI_LEVEL` and `[pytest.log.cli] level`, all addressing the same
field, with `log_cli_level` falling back to `log_level` because the child field
is marked `from_parent`.

## The yardstick

`testing/test_pytest_logging.py` declares pytest's entire logging plugin, the
thirteen ini options in `docs/pytest-logging-options.txt` plus the CLI-only
`log_disable`, as one nested structure. It checks each is reachable by its real
pytest name from ini, TOML, env and CLI, with the fallback chains, the
provenance and the help output.

**A change that makes that file harder to write is going the wrong way.** Its
declaration must be able to use the real types pytest uses: `Literal["w", "a"]`
for `log_file_mode` ([types](types.md#literal-and-enum)) and
`bool | int | None` for `log_auto_indent` ([types](types.md#unions)).

## Non-goals

- **Not a serialisation library.** Configuration is read, never written back.
- **Not a schema language.** The type annotations are the schema.
- **Not a runtime store.** Configuration freezes at `resolve()`
  ([lifecycle](lifecycle.md#resolution-is-an-iteration)). Change
  notification and hot reload are [deferred](deferred.md).
- **Not an argparse replacement.** The CLI parser exists because options must
  be registrable after parsing has already happened once
  ([sources](sources.md#cli-parsing)). Anything beyond that belongs to the
  host.

## Where the code stands

Nothing has been published. The first implementation was reviewed twice, and
reading the resulting design without the code in view showed that the design's
own consequences were not what the code was approaching. The code is therefore
being rebuilt to these documents ([D20](decisions.md#d20)), in
[the build order](#build-order), with the existing tests as the acceptance
criteria.

Until the rebuild lands, these documents describe the target and carry no
status markers. The code in `src/` is the pre-rebuild shape and is not evidence
of what the design says. When the new core is in place, every rule here is
built by construction, and the marker discipline resumes for whatever drifts
after that.

## The pipeline

Everything below is one pipeline, and each document owns one stage of it:

1. **Field model.** Classes become `FieldInfo` records; a field's identity is
   its path ([ConfigParts](config-parts.md)).
2. **Specs.** Each field becomes a `FieldSpec`, a pure function of its root:
   every spelling, every CLI form, the closed value set ([Specs](specs.md)).
3. **The index.** At `declare()` the manager builds one `SpellingIndex` over
   every declared root and judges collisions ([Names](names.md)).
4. **Sources.** Each reads its input, resolves spellings through the index and
   yields readings per path, or unmatched spellings ([Sources](sources.md)).
5. **The store.** Readings are converted on entry, with their origin, and kept
   per path in ladder order ([Types](types.md), [Merging](merging.md)).
6. **Projection.** Winner per path, the `from_parent` cascade, assembly and
   construction ([Merging](merging.md)).
7. **Resolution.** Steps 3 to 5 repeat from the same base until neither the
   declared set nor the derived sources grow; then step 6 runs once
   ([Lifecycle](lifecycle.md)).

[Reporting](reporting.md) and [Diagnostics](diagnostics.md) read the store.
[The binding contract](binding-contract.md) says what a host may put at step 4.

## The documents

| Document | What it settles |
|---|---|
| [Invariants](invariants.md) | The eight rules everything else follows from |
| [ConfigParts](config-parts.md) | The class, the field model, roots and nested parts |
| [Names](names.md) | The qualified path, `prefix`/`name_prefix`, the two file spellings, the index, `-o`, collisions |
| [Types](types.md) | The registry, dialects, unions, `Literal`, what a failed conversion does |
| [Sources](sources.md) | The reading protocol, the precedence ladder, dialects, CLI parsing, file discovery |
| [Lifecycle](lifecycle.md) | declare, resolve, get; the iteration; injected arguments; the runtime layer |
| [Merging](merging.md) | The layered store, unknown keys, assembly, `from_parent` |
| [Specs](specs.md) | What an option is, as data, in the library's vocabulary |
| [Reporting](reporting.md) | Provenance and help |
| [Diagnostics](diagnostics.md) | The warning and error set, strict mode, and which one an input gets |
| [Binding contract](binding-contract.md) | The core/host boundary, and conformance |
| [Decisions](decisions.md) | D1 to D30, core, with rationale and cost |
| [Deferred](deferred.md) | Not in scope, plus the open questions |

Everything above is core: it holds for every host and for an application with
no host at all. Host policy lives separately and may not be cited by a core
document:

| Binding | |
|---|---|
| [pytest](pytest/index.md) | the binding |
| [pytest: Evolution](pytest/evolution.md) | the staged plan to replace pytest's config layer |
| [pytest: Decisions](pytest/decisions.md) | P1 to P8, pytest policy |
| [vcs-versioning](vcs-versioning/index.md) | a candidate binding, evaluated; no argument parser at all |

**Reading order.** [Invariants](invariants.md) first. Then
[ConfigParts](config-parts.md) and [Names](names.md), which are what a user of
the library touches. Then [Sources](sources.md), [Lifecycle](lifecycle.md) and
[Merging](merging.md), which are how a value gets from a file to a field.
[Reporting](reporting.md), [Diagnostics](diagnostics.md) and [Specs](specs.md)
are self-contained. Read [the binding contract](binding-contract.md) before
anything under [pytest/](pytest/index.md).

If you are here to change behaviour, read [Decisions](decisions.md) first: a
rule already has a rationale and a recorded cost, and disagreeing with it means
amending that record before the code.

## Build order

The order the new core is built in. A step's **needs** are the steps whose
absence would make it wrong, not merely inconvenient. Each step is tested
against a table before the next begins, because the whole point of the pipeline
is that every stage is a value.

| # | Step | Delivers | Needs |
|---|---|---|---|
| 1 | **Field model and names** | `fields_of()`, `names_of()`; one class, nested detection, the root keywords | – |
| 2 | **Specs and the index** | `field_specs()`, `CliForm`, `EnvSpelling`; `SpellingIndex` with collision and adoption; every marker | 1 |
| 3 | **Diagnostics** | `ConfigError` / `ConfigWarning` and the set beneath them; aggregation; strict mode | – |
| 4 | **Conversion** | the registry with its built-in entries; unions; `Literal` and `Enum`; origin-aware converters | 3 |
| 5 | **The store and projection** | readings in, `LayeredValue` out; shadowed failures; the cascade; assembly; construction checks | 2, 3, 4 |
| 6 | **Sources** | `TomlSource`, `IniSource`, `EnvSource`, `TomlEnvSource`, the native parser and `CLISource.bind()`, `OverrideSource`, `InjectedArgsSource`, discovery; distinct rungs | 2, 5 |
| 7 | **The manager** | `declare()`, the iteration, `get()`, `partial()`, `origin_of()`, `explain()`, `format_help()` | 5, 6 |
| 8 | **The runtime layer and fragment lifetime** | `set()`, `RuntimeSource`, `instance()` contexts | 7 |
| 9 | **The pytest binding** | `add_config()`, `get_config()`, the forward binder, the host source; the example plugin | 7 |
| 10 | **Conformance** | one suite over the native parser and the pytest binding; the yardstick runs through it | 6, 9 |
| 11 | **YAML** | a third file format, once [its questions](deferred.md#open-questions) are answered | 6 |

The existing tests under `testing/` are the acceptance criteria for steps 1 to
9, renamed where the public API changed: `SubConfig` is `ConfigPart`,
`AddoptsSource` is `InjectedArgsSource`, `Precedence.ADDOPTS` is
`Precedence.INJECTED`, `addopts_field` is `injected_args`, and
`EnvSource(parse_toml=True)` is `TomlEnvSource`. A test that pinned old
behaviour a decision rejects is rewritten to the decision, citing it.

The pytest binding's [staged plan](pytest/evolution.md#stages) starts after
step 9; its stages 1 and 3 are delivered by the rebuild.
