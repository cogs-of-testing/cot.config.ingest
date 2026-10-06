# Releasing

Versions come from git tags (hatch-vcs). Pushing a `v*` tag runs
`.github/workflows/release.yml`, which tests, builds, smoke-tests the wheel
and publishes `cot-config` to PyPI through trusted publishing.

## Once: trusted publisher

PyPI knows this repository as the publisher of `cot-config`:

| field | value |
|---|---|
| owner | `cogs-of-testing` |
| repository | `cot.config.ingest` |
| workflow | `release.yml` |
| environment | `pypi` |

## Each release

1. Update `CHANGELOG.md` on `main`, if the project keeps one.
2. Tag the commit on `main` and push the tag:

       git tag vX.Y.Z
       git push origin vX.Y.Z
