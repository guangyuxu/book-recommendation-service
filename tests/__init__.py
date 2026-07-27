"""Test suite. Two suites, one layout law -- identical in the sibling repos (accounts, agent).

    unit_tests/         fast + offline; the tree MIRRORS `src/service/` (one dir per subpackage).
                        Run by the blocking gate: `make test` / `make coverage` / `make ci`.
    integration_tests/  end-to-end journeys against the real accounts + agent; organized by FLOW.
                        Opt-in: `make integration` (kept out of `make ci`).

Each suite's `__init__.py` states its own rules.
"""
