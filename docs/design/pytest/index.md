# The pytest binding

The only [binding](../binding-contract.md) that exists. It is a proof of
concept, and the direction it is heading — pytest's config layer implemented by
this library — is [Evolution](evolution.md).

Everything in this directory is **pytest policy**. Nothing here constrains the
core or another host; if a rule in here seems to, it belongs on the other side
of [the contract](../binding-contract.md).

| Document | What it settles |
|---|---|
| this page | the binding as it is today |
| [Evolution](evolution.md) | the staged plan to replace pytest's config layer |
| [Decisions](decisions.md) | P1–P8, pytest policy with rationale and cost |

## Division of labour

`cot/config/pytest_plugin.py` **monkeypatches pytest**, adding
`Parser.add_config`, `Config.get_config` and `Config.explain_config`. The patch
is additive only: no option, ini key, hook or behaviour of pytest's is replaced.
**[built]**, and **[change]** — it is replaced by importable
`add_config(parser, T)` / `get_config(config, T)` functions ([P1](decisions.md#p1)).

pytest keeps argument parsing; the library supplies the structure:

- **declare** — each leaf field becomes a `parser.addoption` and/or
  `parser.addini`, named by [the qualified path](../names.md#the-qualified-path).
  The derivation belongs to the core as [specs](../specs.md); this binding is a
  loop over them that translates into argparse's vocabulary.
- **load** — values come back through `config.getoption` then `config.getini`
  (pytest's own `get_option_ini` precedence) and are reassembled into the nested
  shape, where defaults and the
  [`from_parent` cascade](../merging.md#the-from_parent-cascade) apply.

That split is the interesting part: pytest is good at parsing argv and reading
ini files and has no notion of structure. The intended end state is the reverse
of this arrangement, and the adapter exists to find out what that would need.
**[built]**

## Activation

A `pytest11` entry point, patching at import time. A conftest-level
`pytest_plugins = [...]` would be too late: that conftest's own
`pytest_addoption` runs before its plugin list is processed. Plugins loaded with
`-p` load before entry points and must call `install()` themselves; it is
idempotent. **[built]**

Auto-enabling means the patch reaches every environment the package lands in,
including as a transitive dependency. That is a deliberate trade for a proof of
concept and is not how a stable release should behave — see
[P1](decisions.md#p1).

## Collisions

The binding raises `ConfigLifecycleError` when pytest already owns a CLI option,
naming the field and pointing at `named()`, `no_cli` and `name_prefix` rather
than letting argparse say "conflicting option string". **[built]**

An **ini key** pytest already declares is *adopted*, never clobbered: the
existing help and type survive and the value is read. **[built]**, and
load-bearing for a migration.

The native ladder currently disagrees with this binding about collisions — it
silently shares the registration instead of raising. That divergence is a core
bug, not pytest policy; see [collisions](../names.md#collisions) and
[D6](../decisions.md#d6).

## What the binding predates

The proof of concept was written against an earlier pytest. Three pieces of
current surface it does not use, all cheap to adopt
([stage 2](evolution.md#stages)):

| pytest surface | What the binding does instead |
|---|---|
| `addini(aliases=...)` | nothing — [`named()`](../names.md#per-field-overrides) and legacy spellings have no route to pytest |
| `int` / `float` / `paths` / `pathlist` / `args` ini types | collapses every non-bool, non-list field to `string` |
| `Config.stash` | reaches into the private `config._parser` |

**[change]**

## The example plugin

`cot/config/example_plugin.py` is a slow-test reporter built on the binding —
nested structure, `from_parent` cascade, `named()`, `no_cli`, help text, ini and
CLI. It is not auto-enabled:

```bash
pytest -p cot.config.example_plugin --timing-report --timing-threshold=0.5
```

Everything it adds lives under `timing_` / `--timing-*`, a namespace pytest does
not use. `testing/test_example_plugin.py` pins that it clobbers nothing: with no
options given it registers no hooks and the run output is unchanged, and pytest's
own `--durations` keeps working alongside it. **[built]**

It collapses to a declaration plus a context manager once
[plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) lands — its
`pytest_configure` disappears.
