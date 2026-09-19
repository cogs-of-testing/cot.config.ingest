# Deferred and open questions

## Deferred

Present in the design as intent, and not to be assumed by anything that
depends on it:

- **Plugin discovery.** The `Discoverable` protocol has no implementors
  ([lifecycle](lifecycle.md#discover)). The iteration it needs is core; the
  first implementor is a host's decision.
- **List merge semantics.** Append and reset modes ([types](types.md#lists)).
- **Validation hooks.** Field validators, cross-field constraints, "is this
  file readable". Construction checks required fields, rejects unknown kwargs
  and [checks types](types.md#construction-checks), and nothing beyond that.
- **Change notification and hot reload.** An observer API, dependency
  declaration between parts, reload on file change, error recovery when an
  observer raises. Everything about this is open, starting with whether a
  frozen configuration that can be replaced wholesale is a better answer than a
  mutable one that can be updated in place.
- **Environment templating.** `host = "${DB_HOST}"` substitution.
- **Custom name transformers.** User-supplied path-to-name functions.

## Open questions

Undecided. Unlike a decision, these have no committed answer.

1. **`help` shadows the builtin.** `from cot.config import help` is aggressive
   for a name that common. `T @ help("...")` reads better than any alternative
   considered, and the shadowing is scoped to what the user imports. Rename,
   alias, or leave it?
2. **YAML's unanswered half.** [D17](decisions.md#d17) admits
   [YAML](sources.md#yaml) as a file format and stops there. Four questions
   stay open: the third-party parser dependency and what its absence does;
   safe-loading, aliases and merge keys competing with the ladder;
   multi-document streams; and YAML 1.1's duplicate keys and `no`-means-`False`
   conversions. The first implementation answers all four whether or not it
   means to.
3. **Per-source list tokenisation.** Newline-preferred-over-comma is an INI
   convention ([types](types.md#lists)). Does a TOML string field holding
   `"a,b"` want splitting, or should only INI do it?
4. **`invocation_dir` without a CLI source.** Relative `config_source` paths
   fall back to `Path.cwd()` ([sources](sources.md#config-file-discovery)).
   Should a manager with no `CLISource` be required to state its own base
   directory instead?
5. **How much of a fragment's lifetime is the library's?**
   [D11](decisions.md#d11) gives a root a context manager and the manager
   enters it "when the host asks". A host with no obvious configure/teardown
   pair has nowhere natural to put that. Does the library offer a default
   scope, or is entering always the host's call?
6. **The iteration bound.** [D23](decisions.md#d23) bounds the resolution
   loop and leaves the number to the manager. A fixed count, a multiple of the
   declared set's size, or a host-supplied limit?
