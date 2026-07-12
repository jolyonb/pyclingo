# Changelog

## 1.0.1 — 2026-07-11

Documentation and packaging release — no library changes.

- New PyPI readme (now the repository root README): a worked map-coloring
  example executed by the test suite, the "Why ASPAlchemy?" story, and
  positioning relative to clorm
- Documentation published to
  [jolyonb.github.io/aspalchemy](https://jolyonb.github.io/aspalchemy/) via
  GitHub Pages, with a shared navigation header
- Release automation: CI runs the full quality gauntlet on pushes and pull
  requests; version tags publish to PyPI via Trusted Publishing

## 1.0.0 — 2026-07-11

Initial public release.

`aspalchemy` is a Python ORM for clingo: constraints are expressed as typed
Python objects, rendered to ASP source, solved via the clingo API, and
reconstructed back into typed Python values. Highlights:

- Full term hierarchy: variables, constants, predicates, pools, expressions,
  comparisons, aggregates, choices, conditional literals, negation (default
  and classical), and optimization directives
- Typed predicate fields with validation on write and plain-Python reads on
  solution atoms
- Solving surface: model iteration, brave/cautious consequences with
  refinement iterators, timeouts, and clingo-style statistics
- Source-location stamping: diagnostics name the Python line that authored
  the offending ASP statement
- Ground-program inspection via `ground_text()` and `aspif()`
- 100% test line coverage
