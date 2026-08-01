# Host adapters

An adapter lets a host that already parses arguments and reads config files use
this library for structure. There is one today, for pytest, and it is a proof of
concept.

## Division of labour

`cot/config/pytest_plugin.py` **monkeypatches pytest**, adding
`Parser.add_config`, `Config.get_config` and `Config.explain_config`. The patch
is additive only: no option, ini key, hook or behaviour of pytest's is replaced.
**[built]**

pytest keeps argument parsing; this library supplies the structure:

- **declare** — each leaf field becomes a `parser.addoption` and/or
  `parser.addini` under [the same name mapping every other source
  uses](names.md#the-qualified-path)
- **load** — values come back through `config.getoption` then `config.getini`
  (pytest's own `get_option_ini` precedence) and are reassembled into the nested
  shape, where defaults and the
  [`from_parent` cascade](merging.md#the-from_parent-cascade) apply

That split is the interesting part: pytest is good at parsing argv and reading
ini files and has no notion of structure. The intended end state is the reverse
of this arrangement — pytest using the library directly — and the adapter exists
to find out what that would need. **[built]**

## Activation

A `pytest11` entry point, patching at import time. A conftest-level
`pytest_plugins = [...]` would be too late: that conftest's own
`pytest_addoption` runs before its plugin list is processed. Plugins loaded with
`-p` load before entry points and must call `install()` themselves; it is
idempotent. **[built]**

Auto-enabling means the patch reaches every environment the package lands in,
including as a transitive dependency. That is a deliberate trade for a proof of
concept and is not how a stable release should behave.

## Adapters must share semantics

`PytestOptionSource` is the *only* source in the pytest path, at a single
precedence, because pytest has already merged argv and ini by the time values
come back. That is correct — but it means nothing in
[the ladder](sources.md#the-precedence-ladder) is exercised there, and the two
backends have already diverged on
[collision handling](names.md#collisions).

**Every host adapter must satisfy one shared conformance suite**, parameterised
over backends, covering: name mapping, the `from_parent` cascade, collision
policy, type handling, unknown keys, and provenance kind. **[new]**

Today the [yardstick](index.md#the-yardstick) has two implementations —
`testing/test_pytest_logging.py` (native ladder) and
`test_pytest_logging_acceptance.py` (pytester) — and each only asks its own
backend what it does. Divergence is invisible by construction. Rationale in
[D6](decisions.md#d6).

The suite is also the answer to "is the eventual pytest replacement faithful?",
which is why it is a design requirement rather than a testing preference.
