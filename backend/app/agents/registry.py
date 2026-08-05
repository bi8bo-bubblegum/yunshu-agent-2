# backend/app/agents/registry.py
from collections.abc import Callable
from typing import Any


class AgentRegistry:
    def __init__(self):
        self._nodes: dict[str, Callable[..., Any]] = {}

    def register(self, code: str, node: Callable[..., Any]) -> None:
        self._nodes[code] = node

    def get(self, code: str) -> Callable[..., Any]:
        return self._nodes[code]

    def list(self) -> list[str]:
        return list(self._nodes.keys())