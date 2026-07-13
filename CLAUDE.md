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
- `docs/` — user-facing documentation, published to
  [jolyonb.github.io/aspalchemy](https://jolyonb.github.io/aspalchemy/) via
  GitHub Pages (see "Docs Site" below). Python code blocks are executed by
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

## Docs Site

GitHub Pages serves `docs/` from main (Settings → Pages → deploy from
branch), rendering the markdown with Jekyll's Primer theme plus our own
layout and stylesheet (`docs/_layouts/default.html`,
`docs/assets/css/style.scss`). The home page is `docs/index.md`; the
grouped sidebar nav lives in the layout — add new pages to the `<nav>`
there, not to individual markdown files. `docs/_config.yml` lists the
plugins Pages enables by default, so local and production builds match.

### Docs conventions

The docs are executable: `tests/aspalchemy/test_readme.py` runs every
` ```python ` fence in the repo README and each top-level `docs/*.md` —
fences concatenate per file and exec in one shared namespace, so each
page is one runnable script (zero-fence pages skip visibly). The rules
that keep this honest:

- The fence must be exactly ` ```python `; a python-adjacent variant
  (` ```python3 `, ` ```Python `, ` ```py `, ` ```python title="x" `) is
  rejected by the harness, because it would render as code, read as
  verified, and never run. Two flavors, sharing the page's namespace: a
  SCRIPT fence (no prompts) execs as-is — the paste-and-run narrative
  form — and a DOCTEST fence (first line starts with `>>>`) runs through
  doctest, so the output it shows is verified, not decorative. ELLIPSIS
  is on globally (`...` matches anything).
- Prefer doctest fences for receipts: term renders, small deterministic
  outputs, boolean checks, and refusal demos (show the teaching error as
  a real traceback — full text when short, `...`-elided when long).
  Prefer script fences for program construction and anything a reader
  should paste and run.
- Blank lines in output are written as themselves — never spell
  `<BLANKLINE>`. The harness inserts doctest's marker for you, so a full
  program render (which always carries a blank line before its `#show`
  block) is doctestable and reads on the page exactly as it prints.
  Trailing blank lines are ignored (a fence cannot express them), so
  `print(program.render())` is written the way a reader would type it.
  Version strings are elided with `...` (ELLIPSIS is on).
- Text fences are NEVER verified by CI. Anything load-bearing that a page
  displays — above all generated ASP — belongs in a doctest, not a text
  fence: a picture of output that nothing checks will eventually lie.
- Asserts pin properties (validity, key lines present), never exact solver
  output (enumeration order is not stable). Error wording is not API:
  full messages in doctests are fine (docs *should* update when a message
  improves), but never assert full prose. Empirical asserts are
  comparative (A == B), never absolute byte counts.
- Each topic has one home page; elsewhere link, don't re-explain. One
  executable demo per refusal, homed where the reader first hits it.
- No YAML front matter (the H1 is the page title, via
  jekyll-titles-from-headings); filenames lowercase; anchors are kramdown
  auto-ids, so renaming a linked heading means grepping `docs/` for the
  old anchor in the same commit. Internal links are relative `.md` paths
  (jekyll-relative-links rewrites them); CHANGELOG is not in the site —
  link it absolutely. The docs are self-contained: never lean on the root
  README for content (the pitch lives on `index.md`, the clorm positioning
  on `clingo-map.md#positioning`) — the README is the PyPI/GitHub
  storefront, so keep the two tellings in sync when either changes.
- Drift tripwires: `docs/clingo-map.md` ends in a CI-pinned assert block,
  and `test_architecture.py` checks that every `__all__` symbol appears in
  `docs/reference.md` with `##` sections mirroring the `__all__`
  categories. If a refusal is lifted or a construct ships, update
  `docs/unsupported.md` and `docs/clingo-map.md` in the same commit (see
  the release section below).

Preview locally before pushing (needs Homebrew Ruby — the `github-pages`
gem itself requires an EOL Ruby, so the Gemfile uses Jekyll 4 with the
same plugin set):

```bash
cd docs
PATH="/opt/homebrew/opt/ruby/bin:$PATH" BUNDLE_PATH=vendor/bundle \
  bundle install                   # first time only
PATH="/opt/homebrew/opt/ruby/bin:$PATH" BUNDLE_PATH=vendor/bundle \
  bundle exec jekyll serve         # http://localhost:4000, rebuilds on edit
```

The generated litter (`vendor/`, `_site/`, `.jekyll-cache/`,
`Gemfile.lock`) is gitignored; only `docs/Gemfile` is tracked.

## Building & Publishing

Releases are published by CI via PyPI Trusted Publishing — GitHub Actions
authenticates to PyPI with short-lived OIDC tokens (the `pypi` environment
+ `id-token: write` in the workflow, matched by a trusted publisher on
PyPI), so there are no stored secrets to rotate or leak.

To release: bump the version in `pyproject.toml`, update `CHANGELOG.md`,
commit, then tag and push. If a refusal is lifted or a new construct
ships, update `docs/unsupported.md` and `docs/clingo-map.md` in the same
commit. `.github/workflows/publish.yml` takes it from
there: it fails the release if the tag doesn't match the pyproject
version, runs the full gauntlet, builds and uploads to PyPI, and finally
cuts the GitHub Release with notes taken from the `CHANGELOG.md` entry
for that version — so a tag whose version has no changelog entry fails
the release, and the notes can never drift from the changelog.

```bash
git tag -a v1.x.y -m "..."
git push origin v1.x.y               # this is the release trigger

uv build                             # local build: sdist + wheel into dist/
```

- The version in `pyproject.toml` is the single source of truth;
  `src/aspalchemy/version.py` reads the installed metadata at runtime.
- The wheel must contain only package code: `src/aspalchemy/CLAUDE.md` is
  kept out via `source-exclude`, the PyPI readme is the root `README.md`
  (per `readme` in `pyproject.toml`), and `LICENSE.txt` ships via
  `license-files`.
- Sanity-check artifacts before publishing:
  `unzip -l dist/*.whl` and `tar -tzf dist/*.tar.gz`.
