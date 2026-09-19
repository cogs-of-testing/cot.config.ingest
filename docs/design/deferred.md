# Deferred and open questions

## Deferred

Present in the design as intent, absent from the code, and not to be assumed:

- **Plugin discovery.** The `Discoverable` protocol has no implementors
  ([lifecycle](lifecycle.md#discover)). Blocked on
  [the fixpoint resolve](lifecycle.md#the-passes-iterate-to-a-fixpoint).
- **List merge semantics.** Append and reset modes ([types](types.md#lists)).
- **Validation hooks.** Field validators, cross-field constraints, "is this
  file readable". Construction checks required fields, rejects unknown kwargs
  and [checks types](types.md#values-from-typed-sources), and nothing beyond
  that.
- **Change notification and hot reload.** An observer API, dependency
  declaration between parts, reload on file change, error recovery when an
  observer raises. Everything about this is open, starting with whether a
  frozen configuration that can be replaced wholesale is a better answer than a
  mutable one that can be updated in place.
- **The conversion registry and origin-aware conversion.**
  [D18](decisions.md#d18) and [D19](decisions.md#d19) are decided, not
  sequenced. Their one prospective consumer is
  [vcs-versioning](vcs-versioning/index.md), and they are implemented against
  its requirements when it is ported. `Literal` is not deferred with them.
- **Environment templating.** `host = "${DB_HOST}"` substitution.
- **Custom name transformers.** User-supplied path-to-name functions.

## Open questions

Undecided. Unlike a **[change]** rule, these have no committed answer.

1. **`help` shadows the builtin.** `from cot.config import help` is aggressive
   for a name that common. `T @ help("...")` reads better than any alternative
   considered, and the shadowing is scoped to what the user imports. Rename,
   alias, or leave it?
2. **`ConfigPart` versus `SubConfig`.** They share every behaviour; the split
   exists only so nesting can be detected
   ([config parts](config-parts.md#configpart-and-subconfig)). Is a single
   class with a `nested=` marker simpler, or is the type-level distinction
   worth keeping for the reader?
3. **YAML's unanswered half.** [D17](decisions.md#d17) admits
   [YAML](sources.md#yaml) as a file format and stops there. Four questions
   stay open: the third-party parser dependency and what its absence does;
   safe-loading, aliases and merge keys competing with the ladder;
   multi-document streams; and YAML 1.1's duplicate keys and `no`-means-`False`
   conversions. The first implementation answers all four whether or not it
   means to.
4. **Per-source list tokenisation.** Newline-preferred-over-comma is an INI
   convention ([types](types.md#lists)). Does a TOML string field holding
   `"a,b"` want splitting, or should only INI do it?
5. **`invocation_dir` without a CLI source.** Relative `config_source` paths
   fall back to `Path.cwd()` ([sources](sources.md#config-file-discovery)).
   Should a manager with no `CLISource` be required to state its own base
   directory instead?
6. **How much of a fragment's lifetime is the library's?**
   [D11](decisions.md#d11) gives a ConfigPart a context manager and the manager
   enters it "when the host asks". A host with no obvious configure/teardown
   pair has nowhere natural to put that. Does the library offer a default
   scope, or is entering always the host's call?
7. **Bulk environment opt-in.** [D13](decisions.md#d13) makes `from_env`
   per-field, which is verbose for a twelve-factor application where every
   field is meant to be readable. A class keyword would restore the bulk case
   without restoring the implicit default, but a whole-class opt-in is one edit
   away from being the thing D13 removed.
