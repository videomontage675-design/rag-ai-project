"""Dafira RAG assistant: Arabic question answering over a private document knowledge base.

The package follows the layered architecture of ``docs/04_ARCHITECTURE_AND_DESIGN.md`` §3:
interface (``web``, ``cli``) → ``services`` → pipeline (``ingestion``, ``retrieval``,
``generation``, ``evaluation``) → infrastructure (``storage``, ``providers``) → foundation
(``domain``, ``config``, ``core``). Import rules are enforced by import-linter.
"""

__version__ = "0.1.0"
