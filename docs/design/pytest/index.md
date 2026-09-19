# The pytest binding

The only [binding](../binding-contract.md) that exists. It is a proof of
concept, and the direction it is heading, pytest's config layer implemented by
this library, is [Evolution](evolution.md).

Everything in this directory is pytest policy. Nothing here constrains the core
or another host.

| Document | What it settles |
|---|---|
| this page | the binding |
| [Evolution](evolution.md) | the staged plan to replace pytest's config layer |
| [Decisions](decisions.md) | P1 to P8, pytest policy with rationale and cost |

## Division of labour

Two importable, typed functions in `cot.config.pytest_binding`:
`add_config(parser, T)` and `get_config(config, T)`. Nothing is patched onto
pytest, nothing is auto-enabled, and a plugin that does not import them is
untouched ([P1](decisions.md#p1)).

pytest keeps argument parsing; the library supplies the structure:

- **declare**: `add_config` declares `T` with a manager kept in
  `Config.stash` and runs the forward binder, the `bind()` of a
  [binding source](../sources.md#the-protocol): a loop over
  [`field_specs(T)`](../specs.md) that translates each spec into
  `parser.addoption` and `parser.addini` calls. The translation table is in
  [Evolution](evolution.md#binding-the-specs) and it is the only copy.
- **load**: the same source, at the host's rung, reads each spec's value back
  through `config.getoption` and `config.getini` and yields readings, so the
  [store](../merging.md#the-layered-store), the
  [`from_parent` cascade](../merging.md#the-from_parent-cascade) and
  provenance are the core's.

`get_config(config, T)` resolves the manager on first use and returns the
fragment.

## What the binder emits

| spec | pytest call |
|---|---|
| each [CLI form](../specs.md#cli-forms) | one `addoption(...)` with `dest=flat`; a form with a constant uses `store_const` |
| `file_key` | `addini(file_key, type=..., default=..., help=...)`, with the ini type chosen from the annotation: `bool`, `int`, `float`, `paths`, `linelist`, `args` or `string` |
| `aliases` | `addini(..., aliases=aliases)` |
| `values` | `choices=` |

A `getini` value comes back already typed for the ini types pytest knows, so
the source is a typed-dialect source for those keys and a string-dialect one
for `string`; it says which per reading.

## Collisions

The binding raises [`ConfigCollisionError`](../diagnostics.md#errors) when
pytest already owns a CLI option, naming the field and pointing at `named()`,
`no_cli` and `name_prefix`, exactly as the native parser does
([collisions](../names.md#collisions)).

An ini key pytest already declares is adopted, never clobbered: the existing
help and type survive and the value is read.

## The example plugin

`cot/config/example_plugin.py` is a slow-test reporter built on the binding:
nested structure, `from_parent` cascade, `named()`, `no_cli`, help text, ini
and CLI. It is not auto-enabled:

```bash
pytest -p cot.config.example_plugin --timing-report --timing-threshold=0.5
```

Everything it adds lives under `timing_` and `--timing-*`, a namespace pytest
does not use. `testing/test_example_plugin.py` pins that it clobbers nothing.

It collapses to a declaration plus a context manager once
[plugin lifetime](../lifecycle.md#plugin-instances-and-lifetime) lands.
