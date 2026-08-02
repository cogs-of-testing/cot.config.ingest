# Evolution

The staged plan from *adapter* to *replacement*: pytest's CLI and config
handling implemented by this library, with `getoption` and `getini` served as a
legacy view over fragments.

This document is a **staging area**. Everything in it is **[new]**. As each
stage lands, its rules move into the topical documents ([names](names.md),
[sources](sources.md), [host adapters](host-adapters.md)) and leave this one
shorter. What remains here is always the part not yet built.

## The target

Today the arrows point inward: pytest parses, and the library reads the results
back out of `Config`.

```
argv, ini  ->  pytest Parser  ->  Config.getoption / getini  ->  PytestOptionSource  ->  fragment
```

The end state reverses them. Fragments are the store; the legacy accessors are a
view over it.

```
argv, ini  ->  sources  ->  layered store  ->  fragment          (typed, nested, cascaded)
                                           \-> getoption/getini  (legacy view, unchanged semantics)
```

Nothing about this requires pytest to change its public API. `config.getini("log_cli_level")`
keeps returning what it returns today; it is simply answered from a different
place. That is what makes the migration tractable: the replacement can be
correct before anything downstream is aware of it.

## The layers

| Layer | What it is | Depends on pytest |
|---|---|---|
| L0 | the [field model](config-parts.md#fields) — `FieldInfo`, paths, markers | no |
| L1 | **option specs** — what an option *is*, as data | no |
| L2 | **binders** — specs → a host's registration calls, and back | yes, thinly |
| L3 | **layered value store** — every source's value retained, not just the winner | no |
| L4 | **views** — the typed fragment, and the legacy accessors | no |

L0 exists. L1–L4 are the work.

## L1 — Option specs

A pure function of a ConfigPart. No parser, no `Config`, no I/O.

```python
@dataclass(frozen=True)
class OptionSpec:
    path: tuple[str, ...]        # ("cli", "level") — the identity (I1)
    flat: str                    # "log_cli_level"  — dest, ini key, -o key
    long: str | None             # "--log-cli-level", None when no_cli
    short: str | None            # "-v"
    annotation: Any              # as declared
    default: Any                 # the library's default
    choices: tuple[Any, ...]|None  # from Literal
    action: Literal["store", "store_true", "append"]
    ini_type: str | None         # pytest's vocabulary; None = not an ini option
    aliases: tuple[str, ...]     # legacy spellings
    help: str
    group: str
```

`option_specs(T) -> tuple[OptionSpec, ...]` is the single derivation. Everything
that needs to know what options exist reads specs:
[`format_help()`](reporting.md#help), the pytest binder, the
[conformance suite](host-adapters.md#adapters-must-share-semantics), and
eventually pytest's own `--help`.

Two properties make this worth a layer of its own rather than inlining the
derivation into the binder:

- **it is assertable without a host.** `option_specs(LoggingConfig)` is a value.
  A test says what it should be and compares; no `Parser` to stand up, no pytest
  to run.
- **it is where the vocabularies meet.** `action` and `ini_type` are pytest's
  words. Keeping them in a spec derived from the annotation means exactly one
  place translates between the two type systems, and it is a place that can be
  tested exhaustively against a table.

## L2 — Binders

**Forward** — `add_config(parser, T)`: for each spec, `parser.addini(...)` and
`group.addoption(...)`. This is the PoC's `PytestOptionSource.declare` with the
derivation lifted out, so what remains is a loop over specs and nothing else.
Everything the user asked for at the surface is here.

**Ingest** — the reverse: an existing `parser.addoption(...)` / `addini(...)`
becomes a synthesised single-field spec. This is what makes a *mixed* world
work — during a migration, most plugins still declare options the old way, and
the store has to hold their values too or the legacy view is only correct for
the parts already converted.

Ingest is also the answer to "ingestion of backward compatibility fields", which
has been an open question in the README since the beginning.

## L3 — The layered value store

**This is the load-bearing new thing, and the reason the current design cannot
serve the legacy API.**

`getoption` and `getini` are *per-layer* accessors. A fragment holds a *merged*
value. One declaration has to answer three different questions:

```python
config.getoption("log_cli_level")     # the CLI layer alone, else argparse's default
config.getini("log_cli_level")        # the ini/toml layer alone, else the declared default
get_config(config, LoggingConfig).cli.level   # merged, cascaded, typed
```

Today [`ConfigManager`](lifecycle.md#the-passes) keeps the merged value and the
*winning* [origin](reporting.md#the-manager-records-sources-refine). It discards
what the losing sources said, so it can answer the third question and neither of
the first two.

The store therefore retains a value per source per path:

```python
@dataclass(frozen=True)
class LayeredValue:
    value: Any
    source: ConfigSource
    origin: Origin

store.layers(LoggingConfig, ("cli", "level"))   # every source that supplied one, in ladder order
store.winner(LoggingConfig, ("cli", "level"))   # what the fragment got
```

[Provenance](reporting.md#the-provenance-api) becomes a projection of this
rather than a parallel structure — `origin_of()` is `winner().origin`, and
`explain()` gains the ability to show the values that *lost*, which is what a
`--debug-config` reader actually wants.

**pytest is already heading here.** `_pytest.config.findpaths.ConfigValue` is a
frozen record of `value`, `origin: "file" | "override"` and
`mode: "ini" | "toml"`, and `Config._getini` already resolves a small precedence
ladder over it (a CLI `-o` override beats a file; a canonical name beats an
alias). That is a two-rung version of
[the ladder](sources.md#the-precedence-ladder) with the same shape. The
convergence is a good sign for the direction, and `mode` is a distinction this
library will need too — see [open questions](#open-questions).

## L4 — Views

**The typed view** is what exists: `get_config(config, T)` returns the built,
nested, cascaded instance.

**The legacy view** implements pytest's accessors over L3:

| pytest call | served from |
|---|---|
| `config.getoption(name)` | the CLI layer for `flat == name`, else the spec's pytest-facing default |
| `config.getoption("--log-cli-level")` | same, after option-string → `flat` resolution (pytest's `_opt2dest`) |
| `config.getini(name)` | the file layers for `flat == name` (or an alias), else the declared default |
| `get_option_ini(config, *names)` | the existing helper, unchanged, over the two above |

The reverse index this needs — option string and flat name back to field path —
is [`flat_index()`](names.md#the-qualified-path), which already exists.

Error behaviour is part of the contract, not an afterthought: `getoption` raises
`ValueError(f"no option named {name!r}")` for an undeclared name and `getini`
raises `ValueError(f"unknown configuration value: {name!r}")`. pytest's own test
suite asserts on those strings.

## Testability

Each layer gets the kind of test it can actually have, which is most of the
argument for the layering:

| Layer | How it is tested |
|---|---|
| L1 specs | pure comparison against an expected table; no pytest imported |
| L2 forward binder | a recording fake parser; assert the calls and their order |
| L2 ingest binder | round-trip: `addoption(...)` → spec → `addoption(...)` is a fixed point |
| L3 store | layer retention and ladder order, per source, with no host |
| L4 legacy view | **differential** against real pytest |

The differential harness is the acceptance test for the whole replacement.
Declare the same options twice — once through `pytest_addoption` the way pytest
does today, once as a ConfigPart — then assert that `getoption`, `getini` and
`get_option_ini` return **identical** values across a matrix of argv, ini, toml
and `-o` inputs.

pytest's logging plugin is the obvious first subject: it is already
[the yardstick](index.md#the-yardstick), it has thirteen ini options with
fallback chains, and `testing/test_pytest_logging.py` already declares it as a
ConfigPart. The harness turns that file from "the library can express this" into
"the library answers exactly what pytest answers".

## Stages

Each stage is independently useful and independently shippable.

| # | Stage | Delivers | Unblocks |
|---|---|---|---|
| 1 | L1 specs + L2 forward binder; remove the monkeypatch | `add_config(parser, T)` and `get_config(config, T)`, importable and typed | everything |
| 2 | Adopt pytest 9 surface | `addini(aliases=)`, `int`/`float`/`paths` ini types, `Config.stash` | 4, 6 |
| 3 | L3 layered store | `explain()` shows losing values; `origins` becomes a projection | 4 |
| 4 | L4 legacy view | `getoption`/`getini` answerable from fragments | 5 |
| 5 | Differential harness | proof the view is faithful | 6 |
| 6 | L2 ingest binder | old-style `addoption` calls join the store | a mixed-world migration |

**Stage 1 is the one that was asked for**, and it stands alone: it is worth
doing whether or not stages 3–6 ever happen, because it removes the
[monkeypatch](host-adapters.md#activation) and makes the mapping testable.

Stage 2 is cheap and independent. The PoC predates pytest 8.4/9, so
[`_ini_type_of`](host-adapters.md#division-of-labour) collapses every non-bool,
non-list field to `string` even though pytest now has `int`, `float`, `paths`,
`pathlist` and `args`; `named()` and legacy spellings map straight onto
`addini(aliases=...)`; and `config._parser` — the one private access in the
adapter — becomes `config.stash`.

Stage 3 is the architectural commitment ([D10](decisions.md#d10)). Nothing
before it changes the shape of the manager; nothing after it is possible without
it.

## Open questions

These are genuinely undecided, and stages 4–5 cannot be finished without
answers.

1. **Does the legacy view reproduce pytest's warts?** The logging plugin's
   `get_option_ini` ends with `if ret: return ret` — **truthiness**, not
   presence. An ini value of `0`, `""` or `[]` falls through to the next name,
   which is not what the declaration means. This library's
   [`from_parent` cascade](merging.md#the-from_parent-cascade) tests presence and
   gets it right. Faithful-but-wrong, or correct-but-different? Fidelity argues
   for the first; the differential harness only passes with the first; the whole
   point of the exercise argues for the second.
2. **`mode: "ini" | "toml"`.** pytest distinguishes a value that arrived through
   the INI data model (only `str` and `list[str]` exist) from one that arrived
   as native TOML. This library's [type layer](types.md#values-from-typed-sources)
   draws the same line — coerce strings, check typed values — but does not record
   which happened. Does `LayeredValue` need `mode`, or is the source's identity
   enough to infer it?
3. **Where does the store live?** Per `ConfigManager` is the obvious answer, but
   the legacy view is reached from a `Config`, and a `Config` outlives the
   `Parser` the manager is currently keyed to. `Config.stash` resolves it for
   pytest; a host with no equivalent needs something else.
4. **Does `getoption` see `addopts`?** Today pytest splices `addopts` into argv,
   so `getoption` sees it. This library makes `addopts`
   [a source one rung below the CLI](lifecycle.md#the-addopts-feedback-loop),
   which is the better model — but it means the CLI layer alone no longer
   contains what pytest's `getoption` would have returned. The legacy view has to
   choose which of the two it reports, and they are not the same value.
5. **How much of pytest's parser is in scope?** `-p`, `-c`, `--rootdir` and
   `--override-ini` are consumed before the config file is known, which is the
   same bootstrap problem [`bootstrap_only`](lifecycle.md#the-addopts-feedback-loop)
   exists for. Whether those become fragments or stay hand-written in pytest is a
   question for stage 6, not before.
