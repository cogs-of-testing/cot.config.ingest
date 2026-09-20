# pytest decisions

Policy for [the pytest binding](index.md). Each records the decision, why, and
what it costs.

These are not core decisions. A second binding is free to decide every one of
them differently. What it may not do is violate an
[invariant](../invariants.md); that boundary is
[the contract](../binding-contract.md).

!!! note "Renumbering"

    These were D11 to D17 in the core register before the core/binding split.
    D11 became P1, D12 P2, D13 P3 (core half now [D11](../decisions.md#d11)),
    D14 P4 (core half now [D12](../decisions.md#d12)), D15 P5, D16 P7 (core
    half now [D13](../decisions.md#d13)), D17 P8. P6 was an amendment to
    [D1](../decisions.md#d1).

## P1

**There is no monkeypatch.** ([binding](index.md#division-of-labour))

`Parser.add_config`, `Config.get_config` and `Config.explain_config` are
patched on at import time, through an entry point, into every environment the
package lands in. No type checker can see the methods, so every call site needs
a `type: ignore`.

`add_config(parser, T)` and `get_config(config, T)` as importable functions are
fully typed and do not touch anyone who has not imported them. Pre-1.0,
breaking changes are noted rather than deprecated.

*Cost:* breaking for anyone using the patched spelling, in practice
`example_plugin` and the acceptance tests. With the functions in place nothing
needs the entry point, so `pytest11` and `install()` both go.

## P2

**The legacy view is correct where pytest is wrong, and every divergence is
listed.** ([evolution](evolution.md#where-the-view-deliberately-differs))

The logging plugin's `get_option_ini` ends in `if ret: return ret`, a
truthiness test, so an ini value of `0`, `""` or `[]` falls through to the next
name in the chain. The [`from_parent` cascade](../merging.md#the-from_parent-cascade)
tests presence and gets it right.

Reproducing the wart would make the differential harness pass trivially and
leave pytest carrying a bug into its replacement. Fixing it means the harness
needs an explicit allowlist, where each entry names the input, both answers,
and why the library's is better. That allowlist is the list of behaviour
changes the migration makes, in one place.

An unlisted divergence is a bug. Adding an entry is a design decision, not a
test fix.

*Cost:* the migration is no longer strictly invisible. Each entry needs a
changelog line on the pytest side.

## P3

**`config.option` is the runtime view, and the five mutation sites keep
working.** ([evolution](evolution.md#the-legacy-view))

Five places in pytest 9.0.1 assign to `config.option.*` after parsing:
`setuponly`, `setupplan` twice, `stepwise`, and `logging`. They must keep
working through the migration, so `config.option` becomes a live view over the
store and a write lands in the core
[runtime layer](../lifecycle.md#the-runtime-layer).

The mechanism is core; using it for `config.option` is this binding's choice.

The first four happen in `pytest_configure`, deriving one option from another
before anything has been built. The fifth does not: `LoggingPlugin` sets
`config.option.verbose` from inside `pytest_runtestloop`, which is a live
plugin instance changing configuration mid-run. It is the reason a runtime
write rebuilds the fragment and stops there, rather than replacing the objects
built from it ([D32](../decisions.md#d32)) — doing that eagerly would tear down
a plugin inside its own hook.

*Cost:* every one of those five writes now warns. That is intended
([D11](../decisions.md#d11)), but pytest's own test suite gets five new
warnings until those sites are converted to derived fields in
[stage 9](evolution.md#stages). The fifth is not a derived field: it is a
decision made after the run has started, so stage 9 has to answer it
differently or leave it warning.

## P4

**pytest adopts the library's `--help` format.**
([evolution](evolution.md#stages))

Help rendered from [specs](../specs.md) can show what pytest's formatter cannot:
choices from a `Literal`, the `--no-` form of a boolean, which ini key an
option corresponds to, and grouping that follows the declared structure.
Reproducing pytest's current layout would forfeit all of that to preserve a
format nobody chose deliberately.

During the migration, ingested hand-written options render through the same
path, so `--help` stays uniform.

*Cost:* visibly breaking, and the one place the replacement is not invisible
from the outside. pytest's own test suite asserts on help output. This needs to
be an announced change.

## P5

**pytest's file dialects are pytest-specific sources.**
([evolution](evolution.md#the-file-dialects))

pytest reads five file shapes with two data models: ini mode, where every value
is `str` or `list[str]`, and native TOML mode, where types survive. Using both
`[tool.pytest]` and `[tool.pytest.ini_options]` in one file is already a
`UsageError`, so pytest already treats them as two namespaces.

Teaching the core name model about that split would put host compatibility
policy into [names](../names.md). Making each dialect its own source keeps the
core with one name model and puts the compatibility surface here, where it can
be deleted when the legacy namespace is. It also settles which values get
[converted and which get checked](../types.md#two-dialects).

*Cost:* two more source classes, and their relative ladder positions have to
be decided.

## P6

**`-o` is scoped to fields with a file spelling.**
([names](../names.md#the-o-override-key))

[D1](../decisions.md#d1) settles that `-o` addresses a field by its flat name.
pytest's `--override-ini` means "override an ini setting", and this binding
keeps that scope: `-o` reaches only fields that have a file spelling, and
addressing a command-line-only field is an error naming the field.

*Cost:* a field with no file spelling is unreachable by `-o` under this
binding even though the core permits it. `-o` therefore means slightly
different things in a pytest run and a standalone application.

## P7

**No pytest option is environment-settable unless it is converted and marked.**
([evolution](evolution.md#stages))

[D13](../decisions.md#d13) makes opt-in the core rule, so the binding gets the
behaviour it needs by doing nothing. What remains is this binding's own:
converting an option is not the moment to give it an environment spelling.
Roughly two hundred options would become environment-settable in one step
otherwise. `from_env` is added per option, by someone who wants it.

`PYTEST_ADDOPTS` is untouched: it stays a hand-wired injected-arguments source
at [its own rung](../sources.md#the-precedence-ladder), not an env spelling of
a field.

*Cost:* none. The entry stays because "converted" and "environment-settable"
being separate steps is a policy someone will otherwise collapse during
[stage 8](evolution.md#stages).

## P8

**Conversion is plugin-first; ingested options share one flat legacy part.**
([evolution](evolution.md#stages))

Plugin options are self-contained and low-risk, so they prove the replacement
before it touches anything load-bearing. pytest's core options are entangled
with the runner. The pre-config bootstrap set (`-p`, `-c`, `--rootdir`) comes
last, because before a config file exists there is no config system, and
because `findpaths.py` is in flux upstream.

Options not yet converted are ingested into a single flat ConfigPart with no
structure, no cascade and no nesting. Giving it structure would invite it to
become permanent.

*Cost:* the legacy part has no meaningful provenance beyond "ingested". The
flat shape also means two ingested options that would collide by `dest`
collide for real.
