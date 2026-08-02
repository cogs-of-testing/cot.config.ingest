# Evolution

The staged plan from *adapter* to *replacement*: pytest's CLI and config
handling implemented by this library, with `getoption` and `getini` served as a
legacy view over fragments.

This document is a **staging area** for pytest policy. Everything in it is
**[new]**. As each stage lands, its rules move into
[the binding](index.md) and leave this one shorter.

The core capabilities the plan depends on live on the other side of
[the contract](../binding-contract.md) and are specified there, not here:

| Capability | Core document |
|---|---|
| what an option is, as data | [Specs](../specs.md) |
| every source's value retained | [The layered store](../merging.md#the-layered-store) |
| runtime mutation and rebuild | [The runtime layer](../lifecycle.md#the-runtime-layer) |
| fragments implying instances | [Plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) |
| help rendered from specs | [Help](../reporting.md#help) |
| environment exposure policy | [Sources](../sources.md#environment-exposure) |

None of those are pytest's. What follows is.

## The target

Today the arrows point inward: pytest parses, and the library reads the results
back out of `Config`.

```
argv, ini  ->  pytest Parser  ->  Config.getoption / getini  ->  PytestOptionSource  ->  fragment
```

The end state reverses them. Fragments are the store; the legacy accessors are a
view over it; and a plugin instance is derived from the fragment that configures
it.

```
argv, ini  ->  sources  ->  layered store  ->  fragment  ->  plugin instance
                                          \                  (context-managed)
                                           \-> getoption / getini / config.option
                                                  (legacy views)
```

Nothing here requires pytest's public API to change, with one deliberate
exception ([P4](decisions.md#p4), `--help` output).
`config.getini("log_cli_level")` keeps returning what it returns today; it is
simply answered from a different place. That is what makes the migration
tractable — the replacement can be correct before anything downstream is aware of
it.

## Binding the specs

The forward direction is a loop over [`field_specs(T)`](../specs.md) that
translates the library's vocabulary into argparse's and pytest's:

```
flag=True             ->  action="store_true"
repeatable=True       ->  action="append"
counts=True           ->  action="count"
values=(...)          ->  choices=(...)
accumulates_to=X      ->  action="store_const", const=X
optional=True         ->  nargs="?"
file_key + annotation ->  addini(type="string"|"bool"|"int"|"float"|"linelist"|"paths")
aliases               ->  addini(aliases=...)
```

That table is the whole of what this binding knows that the core does not, and
it is why the vocabulary translation is
[a function in the binding rather than a field on the spec](../binding-contract.md#vocabulary-stops-at-the-boundary).

**Ingest** is the reverse: existing `parser.addoption(...)` / `addini(...)` calls
become specs and their values join the store. Without it the legacy view would be
correct only for already-converted plugins, making the migration all-or-nothing.
Ingested options land in one flat legacy ConfigPart ([P8](decisions.md#p8)).

Options declared with an arbitrary `type=` converter callable have no annotation
that implies them and cannot be specced; they stay host-native and reach the
store through ingest.

## The file dialects

pytest reads five file shapes with two data models:

| file | table | data model |
|---|---|---|
| `pytest.ini`, `.pytest.ini` | `[pytest]` | ini — everything is `str` / `list[str]` |
| `setup.cfg` | `[tool:pytest]` | ini |
| `pyproject.toml` | `[tool.pytest.ini_options]` | ini — values stringified on load |
| `pyproject.toml` | `[tool.pytest]` | **toml — native types** |
| `pytest.toml`, `.pytest.toml` | `[pytest]` | **toml — native types** |

Using both `[tool.pytest]` and `[tool.pytest.ini_options]` is a `UsageError`
today, which is pytest saying the same thing this plan says: two namespaces, not
two spellings.

Each becomes a source in this binding ([P5](decisions.md#p5)). The ini-mode
sources hand over strings and their values are
[coerced](../types.md#values-from-typed-sources); the toml-mode sources hand over
native types and their values are **checked**.

## The legacy view

| pytest call | served from |
|---|---|
| `config.getoption(name)` | the CLI **and injected-argument** layers for `flat == name`, else the declared default |
| `config.getoption("--log-cli-level")` | same, after option-string → `flat` resolution |
| `config.getini(name)` | the file layers for `flat == name` or an alias, else the declared default |
| `config.option.<dest>` | the same as `getoption`, writable via the [runtime layer](../lifecycle.md#the-runtime-layer) ([P3](decisions.md#p3)) |
| `get_option_ini(config, *names)` | the existing helper, unchanged, over the two above |

`getoption` reports **CLI and `addopts` merged**, because that is what pytest
returns today: it splices `addopts` into argv before parsing. The
[ladder](../sources.md#the-precedence-ladder) still holds them apart internally,
so provenance can say `addopts --log-level` while the legacy accessor gives the
flattened answer. Faithful on the outside, honest on the inside.

This is a property of *this view*, not of the ladder. A binding without a legacy
accessor reports the layers separately and nothing is lost.

The reverse index it needs — option string and flat name back to field path — is
[`flat_index()`](../names.md#the-qualified-path), which already exists.

Error behaviour is part of the contract: `getoption` raises
`ValueError(f"no option named {name!r}")` and `getini` raises
`ValueError(f"unknown configuration value: {name!r}")`. pytest's own test suite
asserts on those strings.

### Where the view deliberately differs

The legacy view is **correct rather than faithful** where pytest is wrong
([P2](decisions.md#p2)). The known case is the logging plugin's
`get_option_ini`, which ends in `if ret: return ret` — a truthiness test, so an
ini value of `0`, `""` or `[]` falls through to the next name. The
[`from_parent` cascade](../merging.md#the-from_parent-cascade) tests presence and
gets it right.

Every such divergence is an explicit entry in the differential harness's
allowlist, and each entry is an argument for the migration rather than a bug in
it.

## Testability

| Layer | How it is tested |
|---|---|
| forward binder | a recording fake parser; assert the calls and their order |
| ingest binder | round-trip: `addoption(...)` → spec → `addoption(...)` is a fixed point |
| legacy view | **differential** against real pytest |

Core layers are tested in the core; see [specs](../specs.md) and
[the store](../merging.md#the-layered-store).

The differential harness is the acceptance test for the whole replacement.
Declare the same options twice — once through `pytest_addoption` the way pytest
does today, once as a ConfigPart — then assert that `getoption`, `getini`,
`config.option` and `get_option_ini` return **identical** values across a matrix
of argv, ini, toml and `-o` inputs.

It carries one explicit **divergence allowlist**. An entry names the input, both
answers, and why the library's is the better one. An unlisted divergence is a
bug; adding an entry is a design decision, not a test fix.

pytest's logging plugin is the obvious first subject: it is already
[the yardstick](../index.md#the-yardstick), it has thirteen ini options with
fallback chains, and `testing/test_pytest_logging.py` already declares it as a
ConfigPart.

## Stages

Each stage is independently useful and independently shippable. Stages marked
*core* deliver a library capability that this binding then consumes.

| # | Stage | Delivers | Side |
|---|---|---|---|
| 1 | [Specs](../specs.md) + forward binder; remove the monkeypatch | `add_config(parser, T)` and `get_config(config, T)`, importable and typed | core + binding |
| 2 | Adopt pytest 9 surface | `addini(aliases=)`, `int`/`float`/`paths` ini types, `Config.stash` | binding |
| 3 | [Layered store](../merging.md#the-layered-store) + [runtime layer](../lifecycle.md#the-runtime-layer) | `explain()` shows losing values | core |
| 4 | Legacy view | `getoption`/`getini` answerable from fragments | binding |
| 5 | Differential harness + allowlist | proof the view is faithful where it means to be | binding |
| 6 | Ingest binder | hand-written options join the store; `--help` uniform | binding |
| 7 | [Plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) | instances derived from fragments | core |
| 8 | Convert plugin options | logging first, then the rest of the built-ins | binding |
| 9 | Convert pytest core options | `-x`, `--tb`, `-k`, `-m`, … | binding |
| 10 | Discovery and bootstrap | `-p`, `-c`, `--rootdir`, rootdir determination | binding |

**Stage 1 is the one that was asked for**, and it stands alone: it is worth doing
whether or not the later stages happen, because it removes the
[monkeypatch](index.md#activation) and makes the mapping testable.

**Stage 10 is blocked on pytest, not on this library.** `findpaths.py` — args to
common ancestor, upward search, `-c` and `--rootdir` overrides, "pytest.ini wins
even when empty" — stays pytest's for now, and its result is handed to the
library as constructed sources. There is a pytest PR in flight that alters this;
the shape of the eventual handover should be settled against that PR rather than
against today's code.

## Open questions

1. **What owns option groups?** `--help` is rendered from
   [specs](../specs.md) ([P4](decisions.md#p4)), so group names, descriptions and
   ordering come from `FieldSpec.group`. `_group_name()` currently derives one
   from `name_prefix`/`prefix`, which is not the same as pytest's hand-written
   group descriptions ("logging", "collection", …). Are groups a class keyword,
   derived, or ingested?
2. **Does the runtime layer survive the migration?** [P3](decisions.md#p3) exists
   because four pytest sites mutate `config.option`. If those four are converted
   to derived fields during stage 9, this binding has no users for it — and a
   mechanism that warns on every use is a mechanism asking to be deleted. Keep it
   as permanent public surface, or as scaffolding with a removal stage?
3. **Where do the two ini-mode and two toml-mode sources sit relative to each
   other?** [P5](decisions.md#p5) makes them sources but does not order them.
   pytest today picks exactly one config file, so the question only becomes real
   if the binding ever reads more than one.
