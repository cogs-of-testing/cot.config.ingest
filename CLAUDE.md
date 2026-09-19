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
| why is it like that? | `docs/design/decisions.md` — D1 to D19, each with a cost |
| what is still wrong with the code? | `docs/design/index.md#gap-list`, sequenced by `#order-of-work` |

Every rule carries **[built]**, **[change]** (the code does something else and
the *code* is wrong) or **[new]**. A **[change]** rule is a commitment, not a
suggestion: implement it, or amend the decision that records it. Do not "fix" the
code to match a **[change]** description of today's behaviour.

**Core and host policy are separate.** Everything directly under `docs/design/`
is core — true for every host and for an application with none.
`docs/design/pytest/` is pytest policy. `docs/design/binding-contract.md` is the
boundary. Core code must never import, name or accommodate a host, and a core
document may never cite a `pytest/` one.

### Keeping the design and the code in step

The markers are the whole value of these documents, and they only stay true if
they are maintained with the code. When you change behaviour:

1. flip the rule's marker in the component document (**[change]**/**[new]** →
   **[built]**),
2. delete its row from the gap list in `docs/design/index.md`,
3. if you did something the design did not call for, add the rule *first* — and
   a decision if it has a cost worth arguing.

A change that leaves a **[change]** rule describing code that no longer does that
is worse than no documentation, because the next reader trusts it.

## Layout

```
src/cot/config/     the library; every _-prefixed module is internal
  _fields.py        the field model — the only place class shape is derived
  _names.py         path -> every source-facing spelling
  _coerce.py        string -> declared type
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
5. **Derive names through `_names.py`**, never by string manipulation. Five sites
   currently do it by hand and all five are wrong at the edges — that is
   invariant I1 and decision D7.
6. `cot` is a **PEP 420 namespace package** — do not add `src/cot/__init__.py`.
   The PEP 561 marker lives at `src/cot/config/py.typed`.
7. Keep inheritance simple. Sub-configs pick up fields via `__mro__`; elaborate
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

- **Installing the package patches pytest.** `pytest_plugin.py` monkeypatches
  `Parser` and `Config` through a `pytest11` entry point, at import time. It is
  additive only, `-p no:cot_config` disables it, and P1 removes it. A type
  checker cannot see the patched methods; `manager_for_config(config).get(T)` is
  the typed equivalent.
- **`resolve()` is multi-pass on purpose**, because you cannot know every source
  until you have read some configuration. Each pass runs for *every* declared
  type before the next begins — that is invariant I3, and
  `testing/test_lifecycle.py` pins it.
- **The library never prints and never exits** (I4). `format_help()` returns
  text; the application owns the process.

## Absent from the code entirely

Do not assume these exist: plugin discovery (the `Discoverable` protocol has no
implementors), list append/reset merge semantics, YAML files, the spec layer,
the layered store, the runtime layer, change notification and hot reload, and
validation hooks beyond required-field and unknown-kwarg checks.

Injected arguments (`addopts`) *do* accumulate: every contribution is appended to
the one source, later ones winning.

## Running things

```bash
uv run pytest -q
uv run mypy src
pre-commit run -a
```
