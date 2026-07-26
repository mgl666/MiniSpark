"""Tool 抽象：用 Python 类型注解 + docstring 自动生成 JSON Schema。

写一个新工具只需写一个带类型注解和 docstring 的函数（支持 sync/async），
FunctionTool 借助 pydantic 自动完成 schema 生成与参数校验。
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, create_model


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """从 Google 风格 docstring 中提取 ``:param name: 描述``。"""
    docs: dict[str, str] = {}
    for match in re.finditer(r":param\s+(\w+)\s*:\s*(.+)", docstring):
        docs[match.group(1)] = match.group(2).strip()
    return docs


def _build_params_model(fn: Callable[..., Any]) -> type[BaseModel]:
    """根据函数签名生成 pydantic 参数模型（用于校验与 schema 导出）。"""
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
    """把一个 Python 函数包装成 Agent 可调用的工具。"""

    def __init__(self, fn: Callable[..., Any], name: str | None = None) -> None:
        doc = inspect.getdoc(fn) or ""
        self.fn = fn
        self.name = name or fn.__name__
        self.description = self._extract_description(doc)
        self._params_model = _build_params_model(fn)

    @staticmethod
    def _extract_description(doc: str) -> str:
        """提取 docstring 正文（:param 之前的所有行），去掉空行首尾。"""
        lines = []
        for line in doc.splitlines():
            if line.strip().startswith(":param"):
                break
            lines.append(line.strip())
        return "\n".join(lines).strip()

    @property
    def schema(self) -> dict[str, Any]:
        """OpenAI tools 格式的 JSON Schema。"""
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
        """校验参数并执行函数，返回值统一转成字符串。

        参数校验失败时抛出 ValueError，由注册表捕获后回填给模型自我修正。
        """
        try:
            validated = self._params_model.model_validate(arguments or {})
        except Exception as exc:
            raise ValueError(f"参数校验失败: {exc}") from exc
        result = self.fn(**validated.model_dump())
        if asyncio.iscoroutine(result):
            result = await result
        return str(result)


def tool(fn: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """装饰器：把函数标记为工具。

    用法::

        @tool
        def read_file(path: str) -> str:
            '''读取文件内容。

            :param path: 文件路径
            '''
            ...
    """

    def wrap(f: Callable[..., Any]) -> FunctionTool:
        return FunctionTool(f, name=name)

    return wrap(fn) if fn is not None else wrap