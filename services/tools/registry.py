"""Tool registry: ONE definition of each tool, many front doors.

The same registry feeds the MCP server (services/mcp) and, next, the agent loop. A tool is a name,
a description the model reads, a pydantic model for its arguments, and a handler. Arguments are
validated here, so every front door gets identical behaviour and identical error messages.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError


class ToolError(Exception):
    """A tool call that failed in a way the caller (a model or a person) can act on."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: type[BaseModel]
    handler: Callable[[Any, BaseModel], dict[str, Any]]  # (context, validated params) -> JSON-able


class ToolRegistry:
    def __init__(self, context: Any) -> None:
        self._context = context
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(
                f"unknown tool {name!r}; available: {', '.join(self.names())}"
            ) from None

    def specs(self) -> list[dict[str, Any]]:
        """What a model needs to choose and call a tool: name, description, JSON schema."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.params.model_json_schema(),
            }
            for t in (self._tools[n] for n in self.names())
        ]

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = self.get(name)
        try:
            params = tool.params.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors()
            )
            raise ToolError(f"invalid arguments for {name}: {problems}") from exc
        return tool.handler(self._context, params)
