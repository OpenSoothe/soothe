"""Internal tool implementations used by the consolidated capability tools.

These modules are not exposed directly to the LLM.  They are consumed
by the user-facing tools (workspace, execute, data, websearch)
and by the InquiryEngine's information sources.

External code should import from the public tool modules instead:
- ``soothe.tools.workspace``
- ``soothe.tools.execute``
- ``soothe.tools.data``
- ``soothe.tools.websearch``

For deep multi-source research, use the built-in **research** subagent
(``soothe.subagents.deep_research``) via the ``task`` tool, not a tool group.
"""
