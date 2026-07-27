"""Fast, offline unit tests. This tree MIRRORS `src/service/`.

One directory per source subpackage (`routers/` covers `src/service/routers/`), so a test's location
tells you what it covers and a source package with no mirror directory is a visible coverage gap.
Filenames stay descriptive rather than strictly 1:1 with module names.

Tests for `src/service/*.py` top-level modules sit at this root, including one deliberate
cross-cutting exception: `test_ops.py` (readiness / error envelope / correlation id) spans
main/errors/middleware by nature.

The BFF holds no DB and no private key: the agent and the accounts service are replaced by fakes, so
everything here runs offline. End-to-end journeys against the real services belong in
`tests/integration_tests/`.
"""
