"""ORM models for the service.

Placeholder: the service shares the agent's schema (family / members / children / reading
profiles / policies / recommendation sessions / token_usage). The model-sharing strategy --
import from the agent package vs. duplicate the model definitions here -- is an open decision
tracked in TODO.md. Until it is settled, `init_db()` creates no tables from this package (the
agent owns schema creation). Add model modules here and they register on `Base.metadata`.
"""
