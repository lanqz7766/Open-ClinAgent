"""Registry for managing and invoking analysis tools."""
from __future__ import annotations

from clinagent.families.neuro.tools.base_tool import BaseTool


class ToolRegistry:
    """Central registry for all analysis tools.

    Supports two usage modes:
    - *Hardcoded*: caller explicitly invokes tools by name (Config 4).
    - *Dynamic*: provides tool list to VLM for function-calling (Config 5).
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    # ------------------------------------------------------------------
    # Registration & lookup
    # ------------------------------------------------------------------

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Raises ``ValueError`` on duplicate names."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Return a tool by name. Raises ``KeyError`` if not found."""
        if name not in self._tools:
            raise KeyError(f"Tool not found: {name}")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        """Return metadata for every registered tool."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters_schema": t.parameters_schema,
            }
            for t in self._tools.values()
        ]

    def list_tool_names(self) -> list[str]:
        return list(self._tools.keys())

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_tool(self, name: str, **kwargs) -> dict:
        """Look up a tool by *name* and execute it with the given kwargs."""
        return self.get(name).run(**kwargs)

    # ------------------------------------------------------------------
    # OpenAI function-calling spec (Config 5)
    # ------------------------------------------------------------------

    def get_openai_tools_spec(self) -> list[dict]:
        """Format all registered tools as an OpenAI function-calling tools spec."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters_schema,
                },
            }
            for t in self._tools.values()
        ]
