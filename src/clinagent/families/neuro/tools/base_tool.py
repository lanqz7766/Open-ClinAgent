"""Base class for all neuro analysis tools."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Abstract base for analysis tools in the neuro pipeline.

    Every concrete tool must expose *name*, *description*, *parameters_schema*
    (for the VLM function-calling spec) and a ``run`` method that returns a
    JSON-serialisable ``dict``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name for registry lookup and VLM function-calling."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description used in VLM tool-calling prompts."""
        ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict:
        """JSON Schema for the tool's input parameters.

        Used for VLM function-calling (Config 5: dynamic tool selection).
        """
        ...

    @abstractmethod
    def run(self, **kwargs) -> dict:
        """Execute the tool and return a JSON-serialisable dict."""
        ...
