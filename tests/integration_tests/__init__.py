"""End-to-end journeys against the REAL accounts + agent services. Opt-in: `make integration`.

EMPTY ON PURPOSE. The BFF owns no database and no private key -- every seam it has is a call to
another service, so the unit suite fakes both and covers the proxy logic offline. A journey that
exercises the real chain (accounts issues a token -> the BFF verifies it and injects identity -> the
agent streams a turn back) needs the whole platform up, which is the `book-recommendation-deploy`
repo's job; when we automate that, the driving test goes here, named after the FLOW.

Kept out of the blocking `make ci` gate: it needs live services. `make integration` is the
entrypoint (it treats an empty suite as a pass while this stays a placeholder).
"""
