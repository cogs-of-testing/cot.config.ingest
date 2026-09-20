# AI Coding Agent Instructions

## What this is

An **experimental** Python library for type-safe configuration management: you
declare configuration as dataclass-like `ConfigPart` classes and ingest values
from CLI args, environment variables and TOML/INI files, merged by precedence.

**`docs/design/` is normative.** This file is not a summary of it — it is the
part an agent needs that the design does not cover: where things live, how to
run them, and which mistakes this codebase has already made.

## Read before changing behaviour

| Question | Document |
|---|---|
| what are the rules everything follows from? | `docs/design/invariants.md` — eight, short, cited by number |
| what does this name/spelling become? | `docs/design/names.md` |
| when does what happen? | `docs/design/lifecycle.md` |
| which source wins? | `docs/design/sources.md` |
| does this warn or raise? | `docs/design/diagnostics.md` |
| why is it like that? | `docs/design/decisions.md` — D1 to D31, each with a cost |
| in what order is the core built? | `docs/design/index.md#build-order` |

**Core and host policy are separate.** Everything directly under `docs/design/`
is core — true for every host and for an application with none.
`docs/design/pytest/` is pytest policy. `docs/design/binding-contract.md` is the
boundary. Core code must never import, name or accommodate a host, and a core
document may never cite a `pytest/` one.

### Where the code stands

Nothing is published, and the code is being rebuilt to the design
(`docs/design/decisions.md#d20`). Until the rebuild lands:

- the design describes the target and carries no status markers;
- the code under `src/` is the pre-rebuild shape and is **not evidence** of
  what the design says. Do not port its behaviour into the documents, and do
  not "fix" the documents to match it;
- a behaviour change is a change to the design first, with a decision if it
  has a cost worth arguing, and the code follows;
- the tests under `testing/` are the acceptance criteria for the rebuild,
  renamed where the public API changed (`docs/design/index.md#build-order`
  lists the renames).

When the new core is in place, every rule is built by construction and the
marker discipline (**[built]** / **[change]** / **[new]**, maintained with the
code) resumes for whatever drifts after that.

## Layout

The pre-rebuild layout. The rebuild keeps the module split where it matches
the pipeline in `docs/design/index.md#the-pipeline` and renames where it does
not; update this block as modules land.

```
src/cot/config/     the library; every _-prefixed module is internal
  _bases.py         ConfigPart: one class, root or nested by declaration
  _annotations.py   the markers, and the Marker base that identifies them
  _fields.py        the field model — the only place class shape is derived
  _names.py         path -> every source-facing spelling
  _specs.py         field -> FieldSpec, the one derivation of what an option is
  _index.py         spelling -> field; collisions and adoption
  _diagnostics.py   the warning and error set, aggregation, strict mode
  _convert.py       raw value -> declared type; the registry, origin-aware
  _coerce.py        the pre-rebuild coercion, until sources are rebuilt
  _sources.py       the source implementations
  _manager.py       declare/resolve/get, merging, provenance
  _cli_parser.py    the re-parsing argument parser
  pytest_plugin.py  the pytest binding (public)
  example_plugin.py a worked example plugin (public)
testing/            the tests — note: not tests/
docs/design/        normative design
```

`__init__.py` is a pure re-export facade with an explicit `__all__`;
`no_implicit_reexport` is on, so anything public must be listed there.

## Constraints

1. **Type annotations are required** on fields — there is no inference.
2. **Tests live in `testing/`**, not `tests/` (`testpaths = ["testing"]`).
3. **`mypy --strict` must stay clean.** Use `from __future__ import annotations`,
   `if TYPE_CHECKING:` blocks, and keep `Annotated` metadata by passing
   `include_extras=True` to `get_type_hints`.
4. **Read field metadata through `_fields`**, never by re-implementing a
   `get_origin(x) is Annotated` loop. That duplication, in eight places, is what
   the field model replaced.
5. **Derive names through `_names.py` and resolve them through the index**,
   never by string manipulation. That is invariant I1 and decisions D7 and D21.
6. `cot` is a **PEP 420 namespace package** — do not add `src/cot/__init__.py`.
   The PEP 561 marker lives at `src/cot/config/py.typed`.
7. Keep inheritance simple. Parts pick up fields via `__mro__`; elaborate
   multiple inheritance causes field resolution nobody can follow.

## The acceptance test

`testing/test_pytest_logging.py` declares pytest's whole logging plugin — the 13
ini options in `docs/pytest-logging-options.txt` plus the CLI-only `log_disable`
— as one nested structure, and checks each is reachable by its real pytest name
from ini, TOML, env and CLI, with the fallback chains, the provenance and the
help output.

**A change that makes that file harder to write is going the wrong way.**

`testing/test_readme.py` executes the README's declaration for the same reason:
the README once shipped a proposed API that had never existed. Any example
anywhere in this repo is either executed by a test or explicitly marked as not
yet buildable.

## Things that will surprise you

- **Installing the pre-rebuild package patches pytest.** `pytest_plugin.py`
  monkeypatches `Parser` and `Config` through a `pytest11` entry point, at
  import time. It is additive only and `-p no:cot_config` disables it. The
  rebuilt binding has no patch and no entry point (P1).
- **`resolve()` is multi-pass on purpose**, because you cannot know every source
  until you have read some configuration. Each pass runs for *every* declared
  type before the next begins — that is invariant I3, and
  `testing/test_lifecycle.py` pins it.
- **The library never prints and never exits** (I4). `format_help()` returns
  text; the application owns the process.

## Absent from the code entirely

Do not assume these exist in either the old code or the rebuild: plugin
discovery (the `Discoverable` protocol has no implementors), list append/reset
merge semantics, YAML files, change notification and hot reload, and validation
hooks beyond required-field, unknown-kwarg and type checks.

Injected arguments (`addopts`) *do* accumulate: every contribution is appended to
the one source, later ones winning.

## Running things

```bash
uv run pytest -q
uv run mypy src
pre-commit run -a
```
