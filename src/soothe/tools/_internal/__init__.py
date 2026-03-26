"""Internal tool implementations used by the consolidated capability tools.

These modules are not exposed directly to the LLM.  They are consumed
by the user-facing tools (workspace, execute, data, websearch)
and by the InquiryEngine's information sources.

External code should import from the public tool modules instead:
- ``soothe.tools.workspace``
- ``soothe.tools.execute``
- ``soothe.tools.data``
- ``soothe.tools.websearch``

For research capability, use the research subagent:
- ``soothe.subagents.research``
"""
