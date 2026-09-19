# Evolution

The staged plan from adapter to replacement: pytest's CLI and config handling
implemented by this library, with `getoption` and `getini` served as a legacy
view over fragments.

This document is a staging area for pytest policy. Everything in it is
not yet built. As each stage lands, its rules move into [the binding](index.md).

The core capabilities the plan depends on are specified on the other side of
[the contract](../binding-contract.md):

| Capability | Core document |
|---|---|
| what an option is, as data | [Specs](../specs.md) |
| every source's value retained | [The layered store](../merging.md#the-layered-store) |
| runtime mutation and rebuild | [The runtime layer](../lifecycle.md#the-runtime-layer) |
| fragments implying instances | [Plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) |
| help rendered from specs | [Help](../reporting.md#help) |
| opt-in environment exposure | [Sources](../sources.md#exposure-is-opt-in) |
| the warning and error set | [Diagnostics](../diagnostics.md) |
| the `override` and `runtime` rungs | [The ladder](../sources.md#the-two-rungs-above-the-command-line) |

## The target

Today pytest parses, and the library reads the results back out of `Config`:

```
argv, ini  ->  pytest Parser  ->  Config.getoption / getini  ->  PytestOptionSource  ->  fragment
```

The end state reverses that. Fragments are the store, the legacy accessors are
a view over it, and a plugin instance is derived from the fragment that
configures it:

```
argv, ini  ->  sources  ->  layered store  ->  fragment  ->  plugin instance
                                          \                  (context-managed)
                                           \-> getoption / getini / config.option
                                                  (legacy views)
```

Nothing here requires pytest's public API to change, with one exception
([P4](decisions.md#p4), `--help` output). `config.getini("log_cli_level")`
keeps returning what it returns today, answered from a different place.

## Binding the specs

The forward direction is a loop over [`field_specs(T)`](../specs.md) that
translates the library's vocabulary into argparse's and pytest's:

```
flag=True             ->  action="store_true"
repeatable=True       ->  action="append"
counts=True           ->  action="count"
values=(...)          ->  choices=(...)
form(contributes=X)   ->  action="store_const", const=X
file_key + annotation ->  addini(type="string"|"bool"|"int"|"float"|"linelist"|"paths")
aliases               ->  addini(aliases=...)
```

That table is the whole of what this binding knows that the core does not, and
it is the only copy of the mapping
([the contract](../binding-contract.md#vocabulary-stops-at-the-boundary)).

**Ingest** is the reverse: existing `parser.addoption(...)` and `addini(...)`
calls become specs and their values join the store. Without it the legacy view
would be correct only for already-converted plugins. Ingested options land in
one flat legacy ConfigPart ([P8](decisions.md#p8)).

Options declared with an arbitrary `type=` converter callable cannot be
specced; they stay host-native and reach the store through ingest.

## The file dialects

pytest reads five file shapes with two data models:

| file | table | data model |
|---|---|---|
| `pytest.ini`, `.pytest.ini` | `[pytest]` | ini: everything is `str` / `list[str]` |
| `setup.cfg` | `[tool:pytest]` | ini |
| `pyproject.toml` | `[tool.pytest.ini_options]` | ini: values stringified on load |
| `pyproject.toml` | `[tool.pytest]` | **toml: native types** |
| `pytest.toml`, `.pytest.toml` | `[pytest]` | **toml: native types** |

Each becomes a source in this binding ([P5](decisions.md#p5)). The ini-mode
sources hand over strings and their values are
[converted](../types.md#two-dialects); the toml-mode sources hand
over native types and their values are checked.

## The legacy view

| pytest call | served from |
|---|---|
| `config.getoption(name)` | the CLI and injected-argument layers for `flat == name`, else the declared default |
| `config.getoption("--log-cli-level")` | same, after option-string to `flat` resolution |
| `config.getini(name)` | the file and override layers for `flat == name` or an alias, else the declared default |
| `config.option.<dest>` | the same as `getoption`, writable via the [runtime layer](../lifecycle.md#the-runtime-layer) ([P3](decisions.md#p3)) |
| `get_option_ini(config, *names)` | the existing helper, unchanged, over the two above |

`getoption` reports CLI and `addopts` merged, because pytest splices `addopts`
into argv before parsing. The [ladder](../sources.md#the-precedence-ladder)
still holds them apart internally, so provenance can say
`addopts --log-level`.

`getini` reads the [`override` rung](../sources.md#the-two-rungs-above-the-command-line)
as well as the file layers, because `-o` means "override an ini setting" in
pytest. The two accessors read different layer sets, so neither has to know the
order.

The reverse index, option string and flat name back to field path, is
[`flat_index()`](../names.md#the-qualified-path).

Error behaviour is part of the contract: `getoption` raises
`ValueError(f"no option named {name!r}")` and `getini` raises
`ValueError(f"unknown configuration value: {name!r}")`. pytest's own test suite
asserts on those strings.

### Where the view deliberately differs

The legacy view is correct rather than faithful where pytest is wrong
([P2](decisions.md#p2)). The known case is the logging plugin's
`get_option_ini`, which ends in `if ret: return ret`, so an ini value of `0`,
`""` or `[]` falls through to the next name. The
[`from_parent` cascade](../merging.md#the-from_parent-cascade) tests presence.

Every such divergence is an explicit entry in the differential harness's
allowlist.

## Testability

| Layer | How it is tested |
|---|---|
| forward binder | a recording fake parser; assert the calls and their order |
| ingest binder | round-trip: `addoption(...)` to spec to `addoption(...)` is a fixed point |
| legacy view | differential against real pytest |

The differential harness is the acceptance test for the whole replacement.
Declare the same options twice, once through `pytest_addoption` and once as a
ConfigPart, then assert that `getoption`, `getini`, `config.option` and
`get_option_ini` return identical values across a matrix of argv, ini, toml and
`-o` inputs. It carries one explicit divergence allowlist. An entry names the
input, both answers, and why the library's is the better one. An unlisted
divergence is a bug.

pytest's logging plugin is the first subject: it is
[the yardstick](../index.md#the-yardstick), and
`testing/test_pytest_logging.py` already declares it as a ConfigPart.

## Stages

Each stage is independently shippable. Stages marked core deliver a library
capability that this binding then consumes.

| # | Stage | Delivers | Side |
|---|---|---|---|
| 1 | [Specs](../specs.md) + forward binder | `add_config(parser, T)` and `get_config(config, T)`, importable and typed | delivered by [the rebuild](../index.md#build-order) |
| 2 | Adopt pytest 9 surface | `addini(aliases=)`, `int`/`float`/`paths` ini types, `Config.stash` | delivered by the rebuild |
| 3 | [Layered store](../merging.md#the-layered-store) + [runtime layer](../lifecycle.md#the-runtime-layer) | `explain()` shows losing values | delivered by the rebuild |
| 4 | Legacy view | `getoption`/`getini` answerable from fragments | binding |
| 5 | Differential harness + allowlist | proof the view is faithful where it means to be | binding |
| 6 | Ingest binder | hand-written options join the store; `--help` uniform | binding |
| 7 | [Plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) | instances derived from fragments | core |
| 8 | Convert plugin options | logging first, then the rest of the built-ins | binding |
| 9 | Convert pytest core options | `-x`, `--tb`, `-k`, `-m`, … | binding |
| 10 | Discovery and bootstrap | `-p`, `-c`, `--rootdir`, rootdir determination | binding |

**Stages 1 to 3 are the rebuild's.** The binding is built as a spec binder
from the start and the store and runtime layer are core, so the plan begins at
stage 4.

**Stage 10 is blocked on pytest.** `findpaths.py` stays pytest's for now, and
its result is handed to the library as constructed sources. A pytest PR in
flight alters this; the handover should be settled against that PR rather than
against today's code.

## Open questions

1. **What owns option groups?** `--help` is rendered from
   [specs](../specs.md) ([P4](decisions.md#p4)), so group names, descriptions
   and ordering come from `FieldSpec.group`. `_group_name()` currently derives
   one from `name_prefix` and `prefix`, which is not the same as pytest's
   hand-written group descriptions. Are groups a class keyword, derived, or
   ingested?
2. **Does the runtime layer survive the migration?** [P3](decisions.md#p3)
   exists because four pytest sites mutate `config.option`. If those four are
   converted to derived fields during stage 9, this binding has no users for
   it. Keep it as permanent public surface, or as scaffolding with a removal
   stage?
3. **Where do the two ini-mode and two toml-mode sources sit relative to each
   other?** [P5](decisions.md#p5) makes them sources but does not order them.
   pytest today picks exactly one config file, so the question only becomes
   real if the binding ever reads more than one.
