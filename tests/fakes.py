"""Deterministic fake LLM for tests."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import AsyncIterator

from pydantic import BaseModel

from dndm.llm.client import LLMResult


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.queues: dict[str, deque] = defaultdict(deque)
        self.narrations: deque[str] = deque()
        self.calls: list[tuple[str, str]] = []

    def queue(self, schema_name: str, obj: dict) -> None:
        self.queues[schema_name].append(obj)

    async def complete(self, messages, *, system=None, temperature=0.8, max_tokens=600) -> LLMResult:
        self.calls.append(("complete", messages[-1]["content"][:200]))
        return LLMResult(text="Özet: grup ilerliyor.")

    async def stream(self, messages, *, system=None, temperature=0.8, max_tokens=600, stats=None) -> AsyncIterator[str]:
        self.calls.append(("stream", messages[-1]["content"][:400]))
        text = self.narrations.popleft() if self.narrations else "Rüzgâr uğulduyor ve herkes nefesini tutuyor."
        for word in text.split(" "):
            yield word + " "

    async def structured(self, messages, schema: type[BaseModel], *, system=None, temperature=0.2, max_tokens=800):
        name = schema.__name__
        self.calls.append(("structured:" + name, messages[-1]["content"][:400]))
        q = self.queues.get(name)
        obj = q.popleft() if q else ({"rulings": []} if name == "ExploreAdjudication" else {})
        return schema.model_validate(obj), LLMResult(text="{}")
