# pytest decisions

Policy for [the pytest binding](index.md). Each records the decision, why, and
what it costs.

These are **not** core decisions. Nothing here constrains the library or another
host; a second binding is free to decide every one of them differently. What it
may *not* do is violate an [invariant](../invariants.md) — that boundary is
[the contract](../binding-contract.md).

!!! note "Renumbering"

    These were D11–D17 in the core register before the core/binding split.
    D11→P1, D12→P2, D13→P3 (core half now [D11](../decisions.md#d11)), D14→P4
    (core half now [D12](../decisions.md#d12)), D15→P5, D16→P7 (core half now
    [D13](../decisions.md#d13)), D17→P8. P6 was an amendment to
    [D1](../decisions.md#d1).

## P1

**The monkeypatch is removed.** ([binding](index.md#activation))

`Parser.add_config`, `Config.get_config` and `Config.explain_config` are patched
on at import time, through an entry point, into every environment the package
lands in — including ones that acquired it as a transitive dependency and never
asked for it. Because the patch happens at import time no type checker can see
the methods, so every call site needs a `type: ignore`.

`add_config(parser, T)` and `get_config(config, T)` as importable functions are
barely longer to write, fully typed, and do not touch anyone who has not imported
them. The CHANGELOG already states the policy this falls under: pre-1.0, breaking
changes are noted rather than deprecated.

*Cost:* breaking for anyone using the patched spelling — in practice
`example_plugin` and the acceptance tests. With the functions in place nothing
needs the entry point, so `pytest11` and `install()` both go.

## P2

**The legacy view is correct where pytest is wrong, and every divergence is
listed.** ([evolution](evolution.md#where-the-view-deliberately-differs))

The logging plugin's `get_option_ini` ends in `if ret: return ret` — a
truthiness test, not a presence test — so an ini value of `0`, `""` or `[]`
falls through to the next name in the chain. That is not what the declaration
means, and the [`from_parent` cascade](../merging.md#the-from_parent-cascade)
already gets it right.

Reproducing the wart would make the differential harness pass trivially and
leave pytest carrying a bug into its replacement. Fixing it means the harness
needs an explicit allowlist, where each entry names the input, both answers, and
why the library's is better. That allowlist is the honest artifact: the list of
behaviour changes the migration actually makes, in one place, reviewable.

An unlisted divergence is a bug. Adding an entry is a design decision, not a test
fix.

*Cost:* the migration is no longer strictly invisible. Each entry is a potential
surprise for someone relying on the old behaviour and needs a changelog line on
the pytest side.

## P3

**`config.option` is the runtime view, and the four mutation sites keep
working.** ([evolution](evolution.md#the-legacy-view))

Four places in pytest assign to `config.option.*` after parsing — `setuponly`,
`setupplan` twice, and `stepwise` — deriving one option from another. They must
keep working through the migration, so `config.option` becomes a live view over
the store and a write lands in the core [runtime
layer](../lifecycle.md#the-runtime-layer).

The mechanism is core; using it for `config.option` is this binding's choice.
Another host with immutable parsed options would never enable it.

*Cost:* every one of those four writes now warns. That is intended — see
[D11](../decisions.md#d11) — but it means pytest's own test suite gets four new
warnings until those sites are converted to derived fields in
[stage 9](evolution.md#stages).

## P4

**pytest adopts the library's `--help` format.**
([evolution](evolution.md#stages))

Help rendered from [specs](../specs.md) can show what pytest's formatter cannot:
choices from a `Literal`, the `--no-` form of a boolean, which ini key an option
corresponds to, and grouping that follows the declared structure rather than
hand-maintained `getgroup` calls. Reproducing pytest's current layout through an
adapter would forfeit all of that to preserve a format nobody chose deliberately.

During the migration, ingested hand-written options render through the same path,
so `--help` stays uniform and a reader cannot tell which options have been
converted.

*Cost:* visibly breaking, and the one place the replacement is not invisible from
the outside. pytest's own test suite asserts on help output. This needs to be an
announced change rather than a side effect.

## P5

**pytest's file dialects are pytest-specific sources.**
([evolution](evolution.md#the-file-dialects))

pytest reads five file shapes with two data models: ini mode, where every value
is `str` or `list[str]`, and native TOML mode, where types survive. Using both
`[tool.pytest]` and `[tool.pytest.ini_options]` in one file is already a
`UsageError` — pytest saying they are two namespaces rather than two spellings of
one.

Teaching the core name model about that split would put host compatibility policy
into [names](../names.md), the layer everything else derives from. Making each
dialect its own source keeps the core with one name model and puts the
compatibility surface here, where it can be deleted when the legacy namespace is.

It also settles which values get [coerced and which get
checked](../types.md#values-from-typed-sources): an ini-mode source hands over
strings, a toml-mode source hands over native types, and the dialect is a
property of the source.

*Cost:* two more source classes, and their relative ladder positions have to be
decided rather than inherited.

## P6

**`-o` is scoped to fields with a file spelling.**
([names](../names.md#the-o-override-key))

[D1](../decisions.md#d1) settles that `-o` addresses a field by its flat name.
pytest's `--override-ini` means specifically "override an ini setting", and this
binding keeps that narrower scope: `-o` reaches only fields that have a file
spelling, and addressing a command-line-only field is an error naming the field.

Widening it would have made pytest's two `-o` flags differ in more than spelling,
which is worse than either behaviour on its own.

*Cost:* a field with no file spelling is unreachable by `-o` under this binding
even though the core permits it. That is the contract working as intended —
[a binding may suppress a spelling](../binding-contract.md#what-a-binding-may-decide)
— but it does mean `-o` means slightly different things in a pytest run and a
standalone application.

## P7

**Only opted-in fields get environment variables.**
([evolution](evolution.md#stages))

The core gives every field an env spelling by default. Carrying that into pytest
would make roughly two hundred options environment-settable in one step — a real
behaviour change, a CI surprise, and a mild attack surface, none of it requested.

This binding selects the marked-fields-only policy that [D13](../decisions.md#d13)
provides. `PYTEST_ADDOPTS` stays what it is: a hand-wired injected-arguments
source at its own rung.

*Cost:* a pytest option is not environment-settable unless someone says so,
which is a smaller capability than the core offers. That asymmetry is deliberate
and is the binding's to make.

## P8

**Conversion is plugin-first; ingested options share one flat legacy part.**
([evolution](evolution.md#stages))

Plugin options are self-contained, individually verifiable and low-risk, so they
prove the replacement before it touches anything load-bearing. pytest's core
options are entangled with the runner. The pre-config bootstrap set (`-p`, `-c`,
`--rootdir`) comes last, because before a config file exists there is no config
system — and because `findpaths.py` is in flux upstream.

Options not yet converted are ingested into a single flat ConfigPart with no
structure, no cascade and no nesting. It is a holding pen: everything in it is
waiting to be replaced by a real declaration, and giving it structure would
invite it to become permanent.

*Cost:* the legacy part has no meaningful provenance beyond "ingested", and until
a plugin is converted its options get none of the library's benefits. The flat
shape also means two ingested options that would collide by `dest` collide for
real, where per-plugin parts would have kept them apart.
