"""The model side of the agent: provider-neutral message types + a Gemini adapter.

The graph (graph.py) only knows `LLM.generate(system, messages, tools) -> ModelTurn`. Swapping
the model means writing one adapter. Tests use a scripted fake, so no test spends API quota.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

GEMINI_AGENT_MODEL = "gemini-3.1-flash-lite"  # free tier: 15 RPM / 500 RPD


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ModelTurn:
    """One model response: some text, some tool calls, or both."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    raw: Any = (
        None  # provider payload, echoed back verbatim (Gemini 3 needs its thought signatures)
    )


@dataclass(frozen=True)
class Message:
    role: Literal["user", "model", "tool"]
    text: str = ""  # user text
    turn: ModelTurn | None = None  # for role == "model"
    tool_name: str = ""  # for role == "tool"
    result: dict[str, Any] = field(default_factory=dict)  # for role == "tool"


class LLM(Protocol):
    def generate(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> ModelTurn: ...


def to_contents(messages: list[Message]) -> list[Any]:
    """Our messages -> Gemini `Content` objects. Consecutive tool results share one Content, as
    the API requires one response part per call in the call's turn."""
    from google.genai import types

    contents: list[Any] = []
    pending: list[Any] = []

    def flush() -> None:
        if pending:
            contents.append(types.Content(role="user", parts=list(pending)))
            pending.clear()

    for m in messages:
        if m.role == "tool":
            pending.append(
                types.Part.from_function_response(name=m.tool_name, response={"result": m.result})
            )
            continue
        flush()
        if m.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
        else:
            turn = m.turn or ModelTurn()
            if turn.raw is not None:
                contents.append(turn.raw)
            else:
                parts = [types.Part(text=turn.text)] if turn.text else []
                parts += [
                    types.Part(function_call=types.FunctionCall(name=c.name, args=c.args))
                    for c in turn.tool_calls
                ]
                contents.append(types.Content(role="model", parts=parts))
    flush()
    return contents


class GeminiLLM:
    def __init__(self, api_key: str, model: str = GEMINI_AGENT_MODEL, retries: int = 3) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self._retries = retries

    def generate(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        from google.genai import errors, types

        declarations = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters_json_schema=t["input_schema"],
            )
            for t in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for attempt in range(self._retries):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=to_contents(messages), config=config
                )
                break
            except errors.APIError as exc:
                code = int(getattr(exc, "code", 0) or 0)
                if attempt == self._retries - 1 or code not in (429, 500, 502, 503, 504):
                    raise
                time.sleep(
                    20.0 if code == 429 else 8.0 * (attempt + 1)
                )  # 429: 15 requests/minute free tier
        calls = tuple(
            ToolCall(c.name or "", dict(c.args or {})) for c in (resp.function_calls or [])
        )
        content = resp.candidates[0].content if resp.candidates else None
        text = (
            "".join(p.text for p in (content.parts or []) if p.text and not p.thought)
            if content
            else ""
        )
        return ModelTurn(text=text.strip(), tool_calls=calls, raw=content)
