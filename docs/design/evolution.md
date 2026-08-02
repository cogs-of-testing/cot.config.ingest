# Evolution

The staged plan from *adapter* to *replacement*: pytest's CLI and config
handling implemented by this library, with `getoption` and `getini` served as a
legacy view over fragments, and plugin instances derived from those fragments.

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
view over it; and a plugin instance is derived from the fragment that configures
it.

```
argv, ini  ->  sources  ->  layered store  ->  fragment  ->  plugin instance
                                          \                  (context-managed)
                                           \-> getoption / getini / config.option
                                                  (legacy views)
```

Nothing here requires pytest's public API to change, with one deliberate
exception ([D14](decisions.md#d14), `--help` output). `config.getini("log_cli_level")`
keeps returning what it returns today; it is simply answered from a different
place. That is what makes the migration tractable — the replacement can be
correct before anything downstream is aware of it.

## The layers

| Layer | What it is | Depends on pytest |
|---|---|---|
| L0 | the [field model](config-parts.md#fields) — `FieldInfo`, paths, markers | no |
| L1 | **option specs** — what an option *is*, as data | no |
| L2 | **binders** — specs → a host's registration calls, and back | yes, thinly |
| L3 | **layered value store** — every source's value retained, not just the winner | no |
| L4 | **views** — the typed fragment, the legacy accessors, plugin instances | no |

L0 exists. L1–L4 are the work.

## L1 — Option specs

A pure function of a ConfigPart. No parser, no `Config`, no I/O.

```python
@dataclass(frozen=True)
class OptionSpec:
    path: tuple[str, ...]        # ("cli", "level") — the identity (I1)
    flat: str                    # "log_cli_level"  — dest, ini key
    long: str | None             # "--log-cli-level", None when no_cli
    negative: str | None         # "--no-log-cli",    booleans only
    short: str | None            # "-v"
    annotation: Any
    default: Any
    action: str                  # store | store_true | store_false
                                 # store_const | count | append
    const: Any | None
    nargs: str | int | None
    choices: tuple[Any, ...] | None
    metavar: str | None
    ini_type: str | None         # pytest's vocabulary; None = no ini spelling
    aliases: tuple[str, ...]     # legacy spellings
    help: str
    group: str
```

`option_specs(T) -> tuple[OptionSpec, ...]` is the single derivation. Everything
that needs to know what options exist reads specs: [help](reporting.md#help),
the pytest binder, the
[conformance suite](host-adapters.md#adapters-must-share-semantics), and
eventually pytest's own `--help`.

Two properties earn it a layer of its own rather than inlining the derivation
into the binder:

- **it is assertable without a host.** `option_specs(LoggingConfig)` is a value.
  A test says what it should be and compares; no `Parser` to stand up, no pytest
  to run.
- **it is where the vocabularies meet.** `action` and `ini_type` are pytest's
  words. Keeping them in a spec derived from the annotation means exactly one
  place translates between the two type systems, and it is a place that can be
  tested exhaustively against a table.

### Derivation over declaration

The spec models pytest's whole `addoption` surface, but almost all of it is
**derived** from the annotation. A marker is added only where nothing can be
inferred ([D9](decisions.md#d9)).

| pytest needs | derived from | marker |
|---|---|---|
| `store` | any scalar annotation | – |
| `store_true` | `bool` | – |
| `store_false` | `bool` with default `True`, via the `--no-` form | – |
| `--no-x` pair | `bool` | – |
| `append` | `list[T]` | – |
| `choices` | `Literal[...]` | – |
| `metavar` | the unwrapped type's name | override only |
| `nargs="?"` | `T \| None` | – |
| `ini_type` | the unwrapped type → pytest's `string`/`bool`/`int`/`float`/`linelist`/`paths` | – |
| `aliases` | [`named()`](names.md#per-field-overrides) plus legacy spellings | – |
| `count` | **nothing** — `-j 4` and `-v -v` are both `int` with a short option | required |
| `store_const` | **nothing** — the constant is not in the type | required |
| `type=` callable | **nothing** | ingest only |

The three that resist derivation are the honest residue: `count` and
`store_const` need a marker, and an arbitrary argparse `type=` converter has no
annotation that implies it, so options using one stay hand-written and are
picked up by the [ingest binder](#l2-binders).

`store_false` disappearing into the `--no-` pair ([D2](decisions.md#d2)) is a
small win worth noting: pytest uses it once, and the boolean-negation rule
already covers it.

## L2 — Binders

**Forward** — `add_config(parser, T)`: for each spec, `parser.addini(...)` and
`group.addoption(...)`. This is the PoC's `PytestOptionSource.declare` with the
derivation lifted out, so what remains is a loop over specs and nothing else.

**Ingest** — the reverse: existing `parser.addoption(...)` / `addini(...)` calls
become specs, and their values join the store. Without it the legacy view is
only correct for the plugins already converted, which would make the migration
all-or-nothing.

Ingested options land in **one flat legacy ConfigPart**. It carries no
structure, no cascade and no nesting — it is a holding pen, and everything in it
is waiting to be replaced by a real declaration. Its fields are synthesised from
the `addoption` call: `dest` becomes the field name, `type`/`action` become the
annotation, and `help` carries over.

Ingest is also the answer to "ingestion of backward compatibility fields", which
has been an open question in the README since the beginning.

## L3 — The layered value store

**This is the load-bearing new thing, and the reason the current design cannot
serve the legacy API.**

`getoption` and `getini` are *per-layer* accessors. A fragment holds a *merged*
value. One declaration has to answer three different questions:

```python
config.getoption("log_cli_level")             # the CLI layers, else the declared default
config.getini("log_cli_level")                # the file layers, else the declared default
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
    source: ConfigSource      # carries its own dialect — see below
    origin: Origin

store.layers(LoggingConfig, ("cli", "level"))   # every source that supplied one, in ladder order
store.winner(LoggingConfig, ("cli", "level"))   # what the fragment got
```

[Provenance](reporting.md#the-provenance-api) becomes a projection of this
rather than a parallel structure — `origin_of()` is `winner().origin` — and
`explain()` gains the ability to show the values that *lost*, which is what a
`--debug-config` reader actually wants.

**pytest is already heading here.** `_pytest.config.findpaths.ConfigValue` is a
frozen record of `value`, `origin` and `mode`, and `Config._getini` resolves a
small precedence ladder over it. That is a two-rung version of
[the ladder](sources.md#the-precedence-ladder) with the same shape.

### The runtime layer

Four places in pytest assign to `config.option.*` — `setuponly`, `setupplan`
(twice) and `stepwise` — deriving one option from another after parsing. That
has to keep working, and it collides with frozen fragments.

`config.option` becomes a live view over the store. A write lands in a
**runtime source** at the top of the ladder, the affected fragment is rebuilt,
and a warning is issued naming the fragment and the writer
([D13](decisions.md#d13)).

The warning is not incidental. A fragment implies a
[plugin instance](#plugin-instances-and-lifetime); mutating it after that
instance exists means tearing the instance down and building a new one, which is
observable. Runtime mutation is a migration affordance, not a blessed pattern,
and the warning is what says so.

### Dialects belong to sources, not values

pytest reads four file shapes with two different data models:

| file | table | data model |
|---|---|---|
| `pytest.ini`, `.pytest.ini` | `[pytest]` | ini — everything is `str` / `list[str]` |
| `setup.cfg` | `[tool:pytest]` | ini |
| `pyproject.toml` | `[tool.pytest.ini_options]` | ini — values stringified on load |
| `pyproject.toml` | `[tool.pytest]` | **toml — native types** |
| `pytest.toml`, `.pytest.toml` | `[pytest]` | **toml — native types** |

Using both `[tool.pytest]` and `[tool.pytest.ini_options]` is a `UsageError`
today, which is pytest saying the same thing this design says: they are two
namespaces, not two spellings.

Rather than teaching the core name model about pytest's dialects, each becomes a
**pytest-specific source** ([D15](decisions.md#d15)). The ini-mode dialect is a
compatibility namespace with its own source; the native-TOML dialect is another.
`mode` is then a property of the source, not a field on `LayeredValue` — which
answers what was open question 2 without inventing anything.

That distinction is exactly the one [types](types.md#values-from-typed-sources)
already draws: an ini-mode source hands over strings and its values are
**coerced**; a toml-mode source hands over native types and its values are
**checked**.

## L4 — Views

### The typed view

`get_config(config, T)` returns the built, nested, cascaded instance. The
manager owns the store, and `Config.stash` holds the manager
([D13](decisions.md#d13)), so the single private `config._parser` access in the
adapter disappears.

### The legacy view

| pytest call | served from |
|---|---|
| `config.getoption(name)` | the CLI **and addopts** layers for `flat == name`, else the declared default |
| `config.getoption("--log-cli-level")` | same, after option-string → `flat` resolution |
| `config.getini(name)` | the file layers for `flat == name` or an alias, else the declared default |
| `config.option.<dest>` | the same as `getoption`, writable via the [runtime layer](#the-runtime-layer) |
| `get_option_ini(config, *names)` | the existing helper, unchanged, over the two above |

`getoption` reports **CLI and addopts merged**, because that is what pytest
returns today: it splices `addopts` into argv before parsing. The ladder still
holds them apart internally, so provenance can say `addopts --log-level` while
the legacy accessor gives the flattened answer. Faithful on the outside, honest
on the inside.

The reverse index this needs — option string and flat name back to field path —
is [`flat_index()`](names.md#the-qualified-path), which already exists.

Error behaviour is part of the contract: `getoption` raises
`ValueError(f"no option named {name!r}")` for an undeclared name and `getini`
raises `ValueError(f"unknown configuration value: {name!r}")`. pytest's own test
suite asserts on those strings.

### Where the view deliberately differs

The legacy view is **correct rather than faithful** where pytest is wrong
([D12](decisions.md#d12)). The known case is the logging plugin's
`get_option_ini`, which ends in `if ret: return ret` — a **truthiness** test, so
an ini value of `0`, `""` or `[]` falls through to the next name. The
[`from_parent` cascade](merging.md#the-from_parent-cascade) tests presence and
gets it right.

Every such divergence is an explicit entry in the differential harness's
allowlist, and each entry is an argument for the migration rather than a bug in
it.

`-o` keeps pytest's narrower meaning: it addresses a field by
[flat name](names.md#the-o-override-key) but only one that has an ini spelling.
A field with no ini key is an error naming the field. This narrows
[D1](decisions.md#d1) — see the amendment there.

## Plugin instances and lifetime

A fragment does not just configure a plugin; it **implies** one. A ConfigPart
exposes a context manager that creates the plugin instance and destroys it:

```python
class TimingConfig(ConfigPart, prefix="pytest", name_prefix="timing"):
    report: bool = False
    file: FileOutput

    @contextmanager
    def plugin(self) -> Iterator[object | None]:
        if not (self.report or self.file.path):
            yield None                      # not configured; nothing to register
            return
        reporter = TimingReporter(self)
        try:
            yield reporter
        finally:
            reporter.close()
```

The manager enters every declared fragment's context at `pytest_configure` and
exits at `pytest_unconfigure`; a yielded non-`None` value is registered with the
plugin manager ([D13](decisions.md#d13)).

Two things fall out of using a context manager rather than a constructor:

- **teardown becomes expressible.** A pytest plugin has no config-scoped cleanup
  hook today; anything holding a file handle or a socket does it by hand.
- **invalidation has a protocol.** A [runtime](#the-runtime-layer) mutation exits
  the context, rebuilds the fragment, and enters a new one. Without a defined
  exit there is no correct way to react to a mutation at all, which is the
  concrete reason mutation is hostile to deriving instances.

`example_plugin` collapses to the class above plus the declaration — its
`pytest_configure` disappears entirely.

## Testability

Each layer gets the kind of test it can actually have, which is most of the
argument for the layering:

| Layer | How it is tested |
|---|---|
| L1 specs | pure comparison against an expected table; no pytest imported |
| L2 forward binder | a recording fake parser; assert the calls and their order |
| L2 ingest binder | round-trip: `addoption(...)` → spec → `addoption(...)` is a fixed point |
| L3 store | layer retention and ladder order, per source, with no host |
| L3 runtime layer | a write rebuilds the fragment, warns, and re-enters the plugin context |
| L4 legacy view | **differential** against real pytest |

The differential harness is the acceptance test for the whole replacement.
Declare the same options twice — once through `pytest_addoption` the way pytest
does today, once as a ConfigPart — then assert that `getoption`, `getini`,
`config.option` and `get_option_ini` return **identical** values across a matrix
of argv, ini, toml and `-o` inputs.

It carries one explicit **divergence allowlist**. An entry names the input, both
answers, and why the library's is the better one. An unlisted divergence is a
bug; adding an entry is a design decision, not a test fix.

pytest's logging plugin is the obvious first subject: it is already
[the yardstick](index.md#the-yardstick), it has thirteen ini options with
fallback chains, and `testing/test_pytest_logging.py` already declares it as a
ConfigPart.

## Stages

Each stage is independently useful and independently shippable.

| # | Stage | Delivers | Unblocks |
|---|---|---|---|
| 1 | L1 specs + L2 forward binder; remove the monkeypatch | `add_config(parser, T)` and `get_config(config, T)`, importable and typed | everything |
| 2 | Adopt pytest 9 surface | `addini(aliases=)`, `int`/`float`/`paths` ini types, `Config.stash` | 4, 6 |
| 3 | L3 layered store + runtime layer | `explain()` shows losing values; `config.option` writable | 4, 7 |
| 4 | L4 legacy view | `getoption`/`getini` answerable from fragments | 5 |
| 5 | Differential harness + allowlist | proof the view is faithful where it means to be | 6 |
| 6 | L2 ingest binder | hand-written options join the store; `--help` is uniform | a mixed-world migration |
| 7 | Plugin context managers | instances derived from fragments | — |
| 8 | Convert plugin options | logging first, then the rest of the built-ins | 9 |
| 9 | Convert pytest core options | `-x`, `--tb`, `-k`, `-m`, … | 10 |
| 10 | Discovery and bootstrap | `-p`, `-c`, `--rootdir`, rootdir determination | — |

**Stage 1 is the one that was asked for**, and it stands alone: it is worth
doing whether or not the later stages happen, because it removes the
[monkeypatch](host-adapters.md#activation) and makes the mapping testable.

**Conversion is plugin-first** ([D17](decisions.md#d17)). Plugin options are
self-contained and individually verifiable; pytest's core options are entangled
with the runner; the pre-config bootstrap set is last because before a config
file exists there is no config system.

**Stage 10 is blocked on pytest, not on this library.** `findpaths.py` — args to
common ancestor, upward search, `-c` and `--rootdir` overrides, "pytest.ini wins
even when empty" — stays pytest's for now, and its result is handed to the
library as constructed sources. There is a pytest PR in flight that alters this;
the shape of the eventual handover should be settled against that PR rather than
against today's code.

## Open questions

1. **How far does env opt-in reach?** [D16](decisions.md#d16) makes environment
   variables opt-in per field for pytest, which is a change from today's
   `EnvSource`, where every field is readable from the environment. Does the
   opt-in become the library-wide default — breaking standalone users who rely
   on the current behaviour — or is it a source-level policy
   (`EnvSource(fields="marked")`) that the pytest binding selects and everyone
   else can ignore? The second is written into the plan as the assumption; it is
   the less disruptive reading, not a settled one.
2. **`no_ini` does not exist.** [`no_cli`](names.md#per-field-overrides)
   suppresses the CLI spelling; there is no mirror suppressing the ini spelling,
   and the adapter declares an ini key for every field. With `-o` scoped to
   ini-backed fields, "has an ini spelling" becomes load-bearing and needs a way
   to be false. Is that a `no_ini` marker, or is it derived from something —
   and what?
3. **What owns option groups?** `--help` is rendered by the library
   ([D14](decisions.md#d14)), so group names, descriptions and ordering come
   from specs. `_group_name()` currently derives one from `name_prefix`/`prefix`,
   which is not the same as pytest's hand-written group descriptions
   ("logging", "collection", …). Are groups a class keyword, derived, or
   ingested?
4. **Does the runtime layer survive the migration?** It exists because four
   pytest sites mutate `config.option`. If those four are converted to derived
   fields during stage 9, the layer has no users — and a mechanism that warns on
   every use is a mechanism asking to be deleted. Keep it as permanent public
   surface, or as scaffolding with a removal stage?
