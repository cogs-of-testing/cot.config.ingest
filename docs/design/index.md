# Design

This is the normative design of `cot.config.ingest`: what the library is meant
to be, why, and where the code has yet to catch up.

## The problem

An application that reads configuration from more than one place ends up
declaring each option more than once. pytest is the worked example: every
logging option exists as a CLI option *and* as an ini key, declared by two
different calls, reconciled by hand at read time:

```python
add_option_ini("--log-cli-level", dest="log_cli_level", default=None, ...)
...
level = get_option_ini(config, "log_cli_level", "log_level")   # by hand, per option
```

Ninety lines of `pytest_addoption` and a local helper produce thirteen ini keys
and twelve options, with the fallback chains open-coded at each use site. Adding
`pyproject.toml` means a third mechanism.

The duplication is not accidental. Each source needs different things: a parser
must be told an option exists before it can parse it; a file needs a section and
a key; an environment variable needs a name. What is *missing* is a single
declaration those three can all be derived from.

## What this library is

A declaration of configuration **structure** — nested, typed, annotated — from
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

`testing/test_pytest_logging.py` declares pytest's entire logging plugin — the
thirteen ini options in `docs/pytest-logging-options.txt` plus the CLI-only
`log_disable` — as one nested structure, and checks each is reachable by its
real pytest name from ini, TOML, env and CLI, with the fallback chains, the
provenance and the help output.

**A change that makes that file harder to write is going the wrong way.** It is
the acceptance criterion for the design, and its declaration must be able to use
the *real* types pytest uses: `Literal["w", "a"]` for `log_file_mode`
([types](types.md#literal)), `bool | int | None` for `log_auto_indent`
([types](types.md#unions)).

## Non-goals

- **Not a serialisation library.** Configuration is read, never written back.
- **Not a schema language.** The type annotations are the schema; there is no
  parallel declaration format.
- **Not a runtime store.** Configuration freezes at `resolve()`
  ([lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint)). Change
  notification and hot reload are [deferred](deferred.md).
- **Not an argparse replacement.** The CLI parser exists because options must be
  registrable after parsing has already happened once
  ([sources](sources.md#cli-parsing)). Anything beyond that belongs to the host.

## Status markers

Every rule in these documents carries one:

| Marker | Meaning |
|---|---|
| **[built]** | The code does this today. |
| **[change]** | The code does something else. The code is wrong, not this document. |
| **[new]** | Not in the code at all. |

A **[change]** or **[new]** rule is a commitment, not a wish. If one turns out to
be a bad idea, the rule changes here first and the reasoning is recorded in
[Decisions](decisions.md).

## The documents

| Document | What it settles |
|---|---|
| [Invariants](invariants.md) | The eight rules everything else follows from |
| [ConfigParts](config-parts.md) | Classes, fields, the field model, frozen semantics |
| [Names](names.md) | The qualified path, `prefix`/`name_prefix`, `named()`, `-o`, collisions |
| [Types](types.md) | Coercion, unions, `Literal`, where type checking happens |
| [Sources](sources.md) | The source protocol, the precedence ladder, CLI parsing, file discovery |
| [Lifecycle](lifecycle.md) | declare → resolve → get, the feedback passes, `addopts` |
| [Merging](merging.md) | Deep merge, unknown keys, sub-config assembly, `from_parent` |
| [Reporting](reporting.md) | Provenance and help — what the library tells the user |
| [Host adapters](host-adapters.md) | The pytest proof of concept, and the conformance requirement |
| [Decisions](decisions.md) | Review findings resolved, with rationale and cost |
| [Deferred](deferred.md) | Absent from the code, plus the open questions |

**Reading order.** [Invariants](invariants.md) first — they are short and
everything else refers back to them. Then [ConfigParts](config-parts.md) and
[Names](names.md), which are what a user of the library actually touches. Then
[Sources](sources.md), [Lifecycle](lifecycle.md) and [Merging](merging.md),
which are how a value gets from a file to a field. [Reporting](reporting.md)
and [Host adapters](host-adapters.md) are self-contained.

If you are here to change behaviour, read [Decisions](decisions.md) first: a
**[change]** rule already has a rationale and a recorded cost, and disagreeing
with it means amending that record rather than the code.

## Gap list

Every rule the code does not yet satisfy, in one place. This is the difference
between the design and `main`.

| Gap | Status | Where | Decision |
|---|---|---|---|
| `name_prefix` missing from the nested file spelling | change | [names](names.md#the-qualified-path) | [D8](decisions.md#d8) |
| Unknown keys judged per-part, not across the section | change | [names](names.md#unknown-keys-are-judged-across-the-section) | [D8](decisions.md#d8) |
| `-o` addresses the structural path, not the flat name | change | [names](names.md#the-o-override-key) | [D1](decisions.md#d1) |
| `-o` values report as CLI options | change | [reporting](reporting.md#overrides-report-as-overrides) | [D1](decisions.md#d1) |
| An unrecognised `-o` key is silent | change | [names](names.md#the-o-override-key) | [D1](decisions.md#d1) |
| Booleans have no `--no-` form | new | [sources](sources.md#cli-parsing) | [D2](decisions.md#d2) |
| A value beginning with `-` is dropped | change | [sources](sources.md#cli-parsing) | [D2](decisions.md#d2) |
| Unions take the first member unconditionally | change | [types](types.md#unions) | [D3](decisions.md#d3) |
| `Literal` is unsupported | new | [types](types.md#literal) | — |
| Typed sources are neither coerced nor checked | change | [types](types.md#values-from-typed-sources) | [D4](decisions.md#d4) |
| `resolve()` does not reach a fixpoint | change | [lifecycle](lifecycle.md#the-passes-iterate-to-a-fixpoint) | [D5](decisions.md#d5) |
| Backends disagree on option collisions | change | [names](names.md#collisions) | [D6](decisions.md#d6) |
| No cross-backend conformance suite | new | [host adapters](host-adapters.md#adapters-must-share-semantics) | [D6](decisions.md#d6) |
| `config_source` / `addopts_field` / `bootstrap_only` ignored below the top level | change | [names](names.md#names-are-never-constructed-by-hand) | [D7](decisions.md#d7) |
| `bootstrap_only` compares munged token strings | change | [lifecycle](lifecycle.md#the-addopts-feedback-loop) | [D7](decisions.md#d7) |
| `config_source` silently ignores non-`.toml` files | change | [sources](sources.md#config-file-discovery) | [D7](decisions.md#d7) |
| `ConfigFileDiscoverySource` uses a raw name and private access | change | [sources](sources.md#config-file-discovery) | [D7](decisions.md#d7) |
| `DeclaringSource` / `OriginAware` tested with `getattr` | change | [sources](sources.md#the-protocol) | — |
| Origins recorded before unknown keys are pruned | change | [merging](merging.md#unknown-keys) | — |
| Mutable defaults copied shallowly | change | [config parts](config-parts.md#configpart-and-subconfig) | — |
| A `ConfigPart` nested in a `ConfigPart` fails obscurely | new | [config parts](config-parts.md#configpart-and-subconfig) | — |

The rows without a decision are corrections with no design content — there is
nothing to weigh, only work to do. The rest carry a cost that was argued.
