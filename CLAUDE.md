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

## Building & Publishing

```bash
uv build                             # sdist + wheel into dist/
uv publish                           # upload to PyPI (needs a token)
```

- The version in `pyproject.toml` is the single source of truth;
  `src/aspalchemy/version.py` reads the installed metadata at runtime.
- The wheel must contain only package code: `src/aspalchemy/CLAUDE.md` is
  kept out via `source-exclude`, the PyPI readme is `docs/README.md`, and
  `LICENSE.txt` ships via `license-files`.
- Sanity-check artifacts before publishing:
  `unzip -l dist/*.whl` and `tar -tzf dist/*.tar.gz`.
