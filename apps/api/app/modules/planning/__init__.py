"""Academic planning module.

Application-layer orchestration for the Academic Planning Engine. Depends on the
provider-neutral AI abstraction in ``app.ai`` and never on a concrete provider.
Authoritative specification and analysis tables are read-only from this module.

The division of responsibility inside the module:

* ``graph`` is the authority on whether a task graph is sound. It is
  deterministic, and it refuses plans rather than repairing them.
* ``planner`` builds the planning prompt and turns a validated provider response
  into persisted, traceable plan data.
* ``router`` picks between the efficient and advanced model tiers and explains
  the choice for a human.
* ``service`` owns versioning, human approval, partial regeneration and the
  audit trail.
"""
