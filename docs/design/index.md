# Design

The normative design of `cot.config.ingest`: what the library is meant to be,
why, and where the code has yet to catch up.

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
for `log_file_mode` ([types](types.md#literal)) and `bool | int | None` for
`log_auto_indent` ([types](types.md#unions)).

## Non-goals

- **Not a serialisation library.** Configuration is read, never written back.
- **Not a schema language.** The type annotations are the schema.
- **Not a runtime store.** Configuration freezes at `resolve()`
  ([lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint)). Change
  notification and hot reload are [deferred](deferred.md).
- **Not an argparse replacement.** The CLI parser exists because options must
  be registrable after parsing has already happened once
  ([sources](sources.md#cli-parsing)). Anything beyond that belongs to the
  host.

## Status markers

Every rule in these documents carries one:

| Marker | Meaning |
|---|---|
| **[built]** | The code does this today. |
| **[change]** | The code does something else. The code is wrong, not this document. |
| **[new]** | Not in the code at all. |

A **[change]** or **[new]** rule is a commitment. If one turns out to be a bad
idea, the rule changes here first and the reasoning is recorded in
[Decisions](decisions.md).

## The documents

| Document | What it settles |
|---|---|
| [Invariants](invariants.md) | The eight rules everything else follows from |
| [ConfigParts](config-parts.md) | Classes, fields, the field model, frozen semantics |
| [Names](names.md) | The qualified path, `prefix`/`name_prefix`, `named()`, `-o`, collisions |
| [Types](types.md) | Coercion, unions, `Literal`, where type checking happens |
| [Sources](sources.md) | The source protocol, the precedence ladder, dialects, CLI parsing, file discovery |
| [Lifecycle](lifecycle.md) | declare, resolve, get; the feedback passes; injected arguments |
| [Merging](merging.md) | Deep merge, unknown keys, sub-config assembly, `from_parent` |
| [Specs](specs.md) | What an option is, as data, in the library's vocabulary |
| [Reporting](reporting.md) | Provenance and help |
| [Diagnostics](diagnostics.md) | The warning and error set, and which one an input gets |
| [Binding contract](binding-contract.md) | The core/host boundary, and conformance |
| [Decisions](decisions.md) | D1 to D19, core, with rationale and cost |
| [Deferred](deferred.md) | Absent from the code, plus the open questions |

Everything above is core: it holds for every host and for an application with
no host at all. Host policy lives separately and may not be cited by a core
document:

| Binding | |
|---|---|
| [pytest](pytest/index.md) | the binding as it is today |
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
**[change]** rule already has a rationale and a recorded cost, and disagreeing
with it means amending that record rather than the code.

## Gap list

Every rule the code does not yet satisfy. **Break** marks a row that changes
behaviour someone may be relying on. **Step** is where it lands in
[the order of work](#order-of-work).

| Gap | Status | Break | Where | Decision | Step |
|---|---|---|---|---|---|
| `name_prefix` missing from the nested file spelling | change | ✓ | [names](names.md#the-qualified-path) | [D8](decisions.md#d8) | [5](#order-of-work) |
| Unknown keys judged per-part, not across the section | change |  | [names](names.md#unknown-keys-are-judged-across-the-section) | [D8](decisions.md#d8) | [5](#order-of-work) |
| A part with no `prefix=` takes its class name as a file section | change | ✓ | [names](names.md#when-there-is-no-prefix) | — | [5](#order-of-work) |
| `-o` addresses the structural path, not the flat name | change | ✓ | [names](names.md#the-o-override-key) | [D1](decisions.md#d1) | [5](#order-of-work) |
| `-o` values report as CLI options | change |  | [reporting](reporting.md#overrides-report-as-overrides) | [D1](decisions.md#d1) | [4](#order-of-work) |
| An unrecognised `-o` key is silent | change |  | [names](names.md#the-o-override-key) | [D1](decisions.md#d1) | [5](#order-of-work) |
| `-o` is a post-merge fixup with no rung | new |  | [sources](sources.md#the-two-rungs-above-the-command-line) | [D14](decisions.md#d14) | [4](#order-of-work) |
| Booleans have no `--no-` form | new |  | [sources](sources.md#cli-parsing) | [D2](decisions.md#d2) | [6](#order-of-work) |
| A value beginning with `-` is dropped | change | ✓ | [sources](sources.md#cli-parsing) | [D2](decisions.md#d2) | [6](#order-of-work) |
| Unions take the first member unconditionally | change | ✓ | [types](types.md#unions) | [D3](decisions.md#d3) | [7](#order-of-work) |
| `Literal` is unsupported | new |  | [types](types.md#literal) | [D18](decisions.md#d18) | [7](#order-of-work) |
| `Enum` is unsupported | new |  | [types](types.md#enum) | [D18](decisions.md#d18) | [deferred](deferred.md#deferred) |
| No conversion for domain types; the coercible set is fixed | new |  | [types](types.md#the-conversion-registry) | [D18](decisions.md#d18) | [deferred](deferred.md#deferred) |
| Conversion cannot see where a value came from | change |  | [types](types.md#coercion-sees-the-origin) | [D19](decisions.md#d19) | [deferred](deferred.md#deferred) |
| Typed sources are neither coerced nor checked | change | ✓ | [types](types.md#values-from-typed-sources) | [D4](decisions.md#d4) | [7](#order-of-work) |
| `EnvSource(parse_toml=)` conflates two dialects in one source | change | ✓ | [sources](sources.md#two-sources-two-dialects) | [D15](decisions.md#d15) | [7](#order-of-work) |
| Every field is environment-readable without opting in | change | ✓ | [sources](sources.md#exposure-is-opt-in) | [D13](decisions.md#d13) | [8](#order-of-work) |
| YAML is not a supported file format | new |  | [sources](sources.md#yaml) | [D17](decisions.md#d17) | [16](#order-of-work) |
| `resolve()` does not reach a fixpoint | change |  | [lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint) | [D5](decisions.md#d5) | [9](#order-of-work) |
| Backends disagree on option collisions | change | ✓ | [names](names.md#collisions) | [D6](decisions.md#d6) | [3](#order-of-work) |
| No cross-backend conformance suite | new |  | [the binding contract](binding-contract.md#conformance) | [D6](decisions.md#d6) | [14](#order-of-work) |
| `config_source` / `addopts_field` / `bootstrap_only` ignored below the top level | change |  | [names](names.md#names-are-never-constructed-by-hand) | [D7](decisions.md#d7) | [1](#order-of-work) |
| `bootstrap_only` compares munged token strings | change |  | [lifecycle](lifecycle.md#the-injected-arguments-loop) | [D7](decisions.md#d7) | [1](#order-of-work) |
| A config file named explicitly but absent raises a bare `FileNotFoundError` | change |  | [sources](sources.md#config-file-discovery) | [D16](decisions.md#d16) | [3](#order-of-work) |
| `config_source` silently ignores non-`.toml` files | change |  | [sources](sources.md#config-file-discovery) | [D7](decisions.md#d7) | [2](#order-of-work) |
| `ConfigFileDiscoverySource` uses a raw name and private access | change |  | [sources](sources.md#config-file-discovery) | [D7](decisions.md#d7) | [1](#order-of-work) |
| `DeclaringSource` / `OriginAware` tested with `getattr` | change |  | [sources](sources.md#the-protocol) | — | [2](#order-of-work) |
| Origins recorded before unknown keys are pruned | change |  | [merging](merging.md#unknown-keys) | — | [2](#order-of-work) |
| `from_parent` with no matching parent field is a silent no-op | change |  | [merging](merging.md#the-from_parent-cascade) | — | [3](#order-of-work) |
| Mutable defaults copied shallowly | change |  | [config parts](config-parts.md#configpart-and-subconfig) | — | [2](#order-of-work) |
| A `ConfigPart` nested in a `ConfigPart` fails obscurely | new |  | [config parts](config-parts.md#configpart-and-subconfig) | — | [2](#order-of-work) |
| Warnings and errors are ad hoc; no shared base, three silent drops | change | ✓ | [diagnostics](diagnostics.md) | [D16](decisions.md#d16) | [3](#order-of-work) |
| No way to declare a legacy spelling, and using one warns nowhere | new |  | [names](names.md#per-field-overrides) | — | [10](#order-of-work) |
| No way to pin an absolute environment variable name | new |  | [names](names.md#per-field-overrides) | — | [8](#order-of-work) |
| Missing required fields raise a bare `TypeError` | change | ✓ | [config parts](config-parts.md#required-and-optional) | [D16](decisions.md#d16) | [3](#order-of-work) |
| There is no spec layer; the derivation is entangled with the source | new |  | [specs](specs.md) | [D9](decisions.md#d9) | [10](#order-of-work) |
| The store keeps only the winning value | change |  | [merging](merging.md#the-layered-store) | [D10](decisions.md#d10) | [11](#order-of-work) |
| No runtime layer or rung; a late write cannot reach a fragment | new |  | [lifecycle](lifecycle.md#the-runtime-layer) | [D11](decisions.md#d11), [D14](decisions.md#d14) | [12](#order-of-work) |
| Fragments imply no instance and have no lifetime | new |  | [lifecycle](lifecycle.md#plugin-instances-and-lifetime) | [D11](decisions.md#d11) | [15](#order-of-work) |
| Help is not rendered from specs | new |  | [reporting](reporting.md#help) | [D12](decisions.md#d12) | [13](#order-of-work) |
| The injected-arguments rung is named for pytest | change | ✓ | [sources](sources.md#the-precedence-ladder) | — | [2](#order-of-work) |
| No way to suppress a field's file spelling | new |  | [names](names.md#per-field-overrides) | — | [5](#order-of-work) |

Host policy is tracked separately, in
[the pytest gap list](pytest/index.md#what-the-binding-predates) and
[P1 to P8](pytest/decisions.md).

The rows without a decision are corrections with no design content. The rest
carry a cost that was argued.

## Order of work

The gap list says what; this says in what order. A step's **needs** are the
steps whose absence would make it wrong, not merely inconvenient.

| # | Step | Delivers | Needs |
|---|---|---|---|
| 1 | **Hand-built names** ([D7](decisions.md#d7)) | the five name-construction sites route through `_names.py`; markers work at every depth | — |
| 2 | **Small corrections** | deep-copied defaults, `isinstance` protocol checks, the nested-`ConfigPart` error, one suffix-to-source map, the `injected` rename | — |
| 3 | **Diagnostics** ([D16](decisions.md#d16)) | `ConfigError` / `ConfigWarning` and the set beneath them; `ConfigDeclarationError` for the `from_parent` and nesting checks; collisions raise `ConfigCollisionError` in both backends | 1, because every message names a field |
| 4 | **The ladder** ([D14](decisions.md#d14)) | `override(30)` and `runtime(40)`; `-o` becomes a source | — |
| 5 | **Names** ([D8](decisions.md#d8), [D1](decisions.md#d1)) | the qualified path, unknown keys judged across the section, `-o` by flat name and warning when unmatched, no class-name sections, `no_ini` | 1, 3, 4 |
| 6 | **CLI parsing** ([D2](decisions.md#d2)) | `--no-` forms; unconditional value consumption | 3 |
| 7 | **Types** ([D3](decisions.md#d3), [D4](decisions.md#d4), [D15](decisions.md#d15), [D18](decisions.md#d18) for `Literal`) | left-to-right unions, checked typed values, split env dialects, `Literal` | 3 |
| 8 | **Environment opt-in** ([D13](decisions.md#d13)) | `from_env` and `env_named`; no implicit exposure | 7, because the dialect split moves the same constructors |
| 9 | **Fixpoint resolve** ([D5](decisions.md#d5)) | passes 2 to 5 iterate; `discover()` becomes implementable | 3 |
| 10 | **Specs** ([D9](decisions.md#d9)) | `field_specs(T)`, host-free, bound by the native parser first; `formerly()`, `aliases` and `DeprecatedNameWarning` | 5, 7, 8, because a spec is spellings and every spelling has to be settled first |
| 11 | **Layered store** ([D10](decisions.md#d10)) | every source's value per path; provenance as a projection | 4, and the origins/pruning fix from step 2 |
| 12 | **Runtime layer** ([D11](decisions.md#d11)) | `manager.set()`; late writes land at `runtime`, fragments rebuild | 4, 11 |
| 13 | **Help from specs** ([D12](decisions.md#d12)) | one renderer, showing what registration calls cannot | 10 |
| 14 | **Conformance suite** ([D6](decisions.md#d6)) | one suite, parameterised over bindings | 10, and everything it compares |
| 15 | **Fragment lifetime** ([D11](decisions.md#d11)) | context-managed instances | 12 |
| 16 | **YAML** ([D17](decisions.md#d17)) | a third file format | 2 for the suffix map; otherwise blocked on [its open questions](deferred.md#open-questions) |

Three things this ordering makes visible:

- **Steps 1 to 4 are the whole foundation**, and only the `injected` rename is
  breaking.
- **The breaking set lands between steps 5 and 8**: names, types and the
  environment. Grouping them into one release keeps the number of releases
  anyone has to read the changelog for down to one.
- **Step 10 is the hinge.** Specs need every spelling settled, and help,
  conformance and any second binding need specs. It is also
  [the pytest binding's stage 1](pytest/evolution.md#stages).

The binding's [staged plan](pytest/evolution.md#stages) consumes steps 10, 11,
12 and 15 as its stages 1, 3 and 7.

A second binding, [vcs-versioning](vcs-versioning/index.md), evaluated and not
committed to, needs steps 1 to 8 and then step 9, because an environment
variable whose name embeds a value read from the configuration cannot be added
without [the fixpoint](lifecycle.md#the-passes-iterate-to-a-fixpoint). D18's
registry and D19 exist because of that evaluation and have no other consumer
yet, so they are [deferred](deferred.md#deferred) rather than sequenced:
implemented against its requirements when it is ported, not ahead of them.
