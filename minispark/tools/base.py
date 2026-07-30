"""Tool abstraction: auto-generate JSON Schema from Python type annotations + docstrings.

To create a new tool, simply write a function with type annotations and a docstring (supports sync/async).
FunctionTool uses pydantic to automatically generate schemas and validate parameters.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, create_model


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Extract ``:param name: description`` from Google-style docstrings."""
    docs: dict[str, str] = {}
    for match in re.finditer(r":param\s+(\w+)\s*:\s*(.+)", docstring):
        docs[match.group(1)] = match.group(2).strip()
    return docs


def _build_params_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """Generate a pydantic parameter model from the function signature (for validation and schema export)."""
    sig = inspect.signature(fn)
    param_docs = _parse_param_docs(inspect.getdoc(fn) or "")
    fields: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        default = ... if param.default is inspect.Parameter.empty else param.default
        if name in param_docs:
            from pydantic import Field

            fields[name] = (annotation, Field(default=default, description=param_docs[name]))
        else:
            fields[name] = (annotation, default)
    return create_model(f"{fn.__name__.title()}Params", **fields)


class FunctionTool:
    """Wrap a Python function as a tool callable by the Agent."""

    def __init__(self, fn: Callable[..., Any], name: str | None = None) -> None:
        doc = inspect.getdoc(fn) or ""
        self.fn = fn
        self.name = name or fn.__name__
        self.description = self._extract_description(doc)
        self._params_model = _build_params_model(fn)

    @staticmethod
    def _extract_description(doc: str) -> str:
        """Extract the docstring body (all lines before :param), trim leading/trailing blank lines."""
        lines = []
        for line in doc.splitlines():
            if line.strip().startswith(":param"):
                break
            lines.append(line.strip())
        return "\n".join(lines).strip()

    @property
    def schema(self) -> dict[str, Any]:
        """JSON Schema in OpenAI tools format."""
        params = self._params_model.model_json_schema()
        params.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }

    async def run(self, arguments: dict[str, Any]) -> str:
        """Validate parameters and execute the function, always returning a string.

        Validation errors raise ValueError, caught by the registry and backfilled to the model for self-correction.
        """
        try:
            validated = self._params_model.model_validate(arguments or {})
        except Exception as exc:
            raise ValueError(f"Parameter validation failed: {exc}") from exc
        result = self.fn(**validated.model_dump())
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Decorator: mark a function as a tool.

    Usage::

        @tool
        def read_file(path: str) -> str:
            '''Read file contents.

            :param path: File path
            '''
            ...
    """

    def wrap(f: Callable[..., Any]) -> FunctionTool:
        return FunctionTool(f, name=name)

    return wrap(fn) if fn is not None else wrap