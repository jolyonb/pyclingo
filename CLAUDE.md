# ASPAlchemy: A Python ORM for clingo

## Mental Model

`aspalchemy` is an object-oriented Python interface for building and solving
clingo ASP (Answer Set Programming) programs:

```
High Level:  aspalchemy - Python-to-ASP translation layer (this repo)
Low Level:   clingo     - ASP solver engine
```

**Core Insight**: The library lets callers express logical constraints as
typed Python objects, renders them to ASP source, solves via the clingo API,
and reconstructs answer sets back into typed Python values.

## Repo Layout

- `src/aspalchemy/` — the package.
- `tests/` — unit suite + module doctests. Line coverage of `aspalchemy` is 
  gated at 100%.
- `docs/` — user-facing documentation. Python code blocks are executed by
  `tests/aspalchemy/test_readme.py` to keep them runnable.
- `pyproject.toml` — packaging (uv_build, src layout), strict mypy/pyright,
  ruff.
- `.pre-commit-config.yaml` — the full quality gauntlet.
- `.github/workflows/` — CI (`ci.yml`) and the release pipeline
  (`publish.yml`); see below.

## Tooling

```bash
uv sync                              # install environment
uv run pytest                        # unit suite + doctests
uv run pre-commit run --all-files    # ruff lint+format, mypy, pyright,
                                     # pytest with the 100% coverage gate
```

Every commit must pass the whole gauntlet. The coverage gate is a hard
policy: genuinely unexecutable lines are excluded centrally in
`[tool.coverage.report]` (never with scattered pragmas).

## CI

`.github/workflows/ci.yml` runs the same gauntlet (`uv sync` +
`uv run pre-commit run --all-files`) on every push to main and on every
pull request. CI and the local hooks are deliberately identical: if it
passed locally, it passes CI.

## Building & Publishing

Releases are published by CI via PyPI Trusted Publishing — GitHub Actions
authenticates to PyPI with short-lived OIDC tokens (the `pypi` environment
+ `id-token: write` in the workflow, matched by a trusted publisher on
PyPI), so there are no stored secrets to rotate or leak.

To release: bump the version in `pyproject.toml`, update `CHANGELOG.md`,
commit, then tag and push. `.github/workflows/publish.yml` takes it from
there: it fails the release if the tag doesn't match the pyproject
version, runs the full gauntlet, and only then builds and uploads.

```bash
git tag -a v1.x.y -m "..."
git push origin v1.x.y               # this is the release trigger

uv build                             # local build: sdist + wheel into dist/
```

- The version in `pyproject.toml` is the single source of truth;
  `src/aspalchemy/version.py` reads the installed metadata at runtime.
- The wheel must contain only package code: `src/aspalchemy/CLAUDE.md` is
  kept out via `source-exclude`, the PyPI readme is `docs/README.md`, and
  `LICENSE.txt` ships via `license-files`.
- Sanity-check artifacts before publishing:
  `unzip -l dist/*.whl` and `tar -tzf dist/*.tar.gz`.
