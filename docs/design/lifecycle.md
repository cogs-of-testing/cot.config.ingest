# Lifecycle

When each thing happens, and why the order is not negotiable.

## Three phases

| Phase | Call | What happens |
|---|---|---|
| declare | `manager.declare(T)` | the type is recorded and its options registered with every [`DeclaringSource`](sources.md#the-protocol). Nothing is loaded. |
| resolve | `manager.resolve()` | the feedback passes run for *all* declared types, then every fragment is built. Idempotent; triggered lazily by the first `get()`. |
| access | `manager.get(T)` | the built, typed instance. |

**[built]**

## Why declaration is separate

A host collects declarations from independent plugins before any of them can be
resolved. In pytest every plugin's `pytest_addoption` runs before a single
argument is parsed — so a fragment built at declaration time could not see a
config file, or an `addopts`, contributed by a plugin loaded after it.

This is [I3](invariants.md#i3), and `testing/test_lifecycle.py` pins it:
declaration order must not change the result. **[built]**

It is also why [`DeclaringSource`](sources.md#the-protocol) exists at all. A
parser-backed source needs the declaration; a file source does not.

## The passes

`resolve()` is deliberately multi-pass, because you cannot know all the sources
until you have read some configuration:

1. collect class defaults
2. call [`discover()`](#discover) on every type that defines it — may add sources
3. process [`config_source`](sources.md#config-file-discovery) fields → add each
   named file as a source
4. load every source to obtain `addopts` values
5. hand those to [`AddoptsSource`](#the-addopts-feedback-loop), which parses them
   at its own precedence
6. re-load everything and [merge](merging.md#deep-merge) in precedence order
7. build nested `SubConfig` instances, applying the
   [`from_parent` cascade](merging.md#the-from_parent-cascade)
8. instantiate, [check types](types.md#values-from-typed-sources) and store

**Each pass runs for every declared type before the next begins**
([I3](invariants.md#i3)), so no fragment is built against a source a later
fragment was about to add. **[built]**

## The passes iterate to a fixpoint

A type declared *during* resolution — by a [`discover()`](#discover) hook, or by
a plugin loaded from a config file — must receive every pass, not just the ones
that have not run yet.

`resolve()` therefore repeats passes 2–5 until the set of declared types stops
growing, then runs 6–8 once. A type declared during the final build pass is an
error: the configuration is closing. **[change]** — the passes are a flat
sequence of `for t in self._declared` loops today. A type declared during pass 2
happens to be picked up (list iteration sees appends); a type declared during
pass 3 or later never gets `discover()` and contributes no config file, silently.

Since plugin discovery is *precisely* "read a config file, then declare more
types", the current loop structure cannot support the one goal the `Discoverable`
protocol exists for. Rationale in [D5](decisions.md#d5).

After resolution the configuration is **frozen**: `declare()` raises
`ConfigLifecycleError`. **[built]**

## discover()

```python
class PluginConfig(ConfigPart):
    plugins: list[str] = []

    @classmethod
    def discover(cls, manager: ConfigManager) -> None:
        for name in manager.load_for_part(cls).get("plugins", []):
            manager.declare(import_module(name).Config)
```

A classmethod, returning `None`, whose effect is on the manager — it adds sources
or declares types. It does not build or return an instance; the manager does that
in pass 8. **[built]** as a protocol, **[new]** as anything with an implementor.

The protocol has no implementors, which means its shape is a guess. The first
real one — plugin loading — is what will validate or refute it, and it is blocked
on [the fixpoint](#the-passes-iterate-to-a-fixpoint). Tracked in
[deferred](deferred.md).

## The addopts feedback loop

`addopts` is a **source**, not a splice into argv. That is what lets it sit
*below* env and above files on [the ladder](sources.md#the-precedence-ladder)
([I2](invariants.md#i2)), and lets an injected option be reported as
`addopts --level` rather than looking like something the user typed — an option
nobody typed is the hardest kind to debug. **[built]**

Tokens accumulate: several config files, or several ConfigParts, may each
contribute, and later contributions win, matching the parser's own rule. This is
the one place a value [accumulates rather than replacing](types.md#lists).
**[built]**

`bootstrap_only` refuses an addopts contribution that tries to set a field whose
decisions have already been made — which config file to open, above all.
Enforcement resolves the parsed tokens to field paths through the parser
([names](names.md#names-are-never-constructed-by-hand)), not by munging the token
string. **[change]**
