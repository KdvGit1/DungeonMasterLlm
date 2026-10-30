"""
LLM client.

All model traffic goes through here. Two call styles:

* ``complete`` / ``stream`` — free text (narration).
* ``structured`` — JSON constrained by a JSON schema (Ollama ``format``),
  validated with a pydantic model, with one repair retry.

Errors never leak into game text: callers get ``LLMError`` and decide on a
fallback themselves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("dndm.llm")

T = TypeVar("T", bound=BaseModel)

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


class LLMError(RuntimeError):
    """Model unreachable, timed out, or returned unusable output."""


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    prompt_seconds: float = 0.0
    output_seconds: float = 0.0
    total_seconds: float = 0.0
    first_token_seconds: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_per_second(self) -> float:
        return self.output_tokens / self.output_seconds if self.output_seconds > 0 else 0.0

    @property
    def prompt_tokens_per_second(self) -> float:
        return self.prompt_tokens / self.prompt_seconds if self.prompt_seconds > 0 else 0.0


class LLMClient(Protocol):
    model: str

    async def complete(self, messages: list[dict], *, system: str | None = None,
                       temperature: float = 0.8, max_tokens: int = 600) -> LLMResult: ...

    def stream(self, messages: list[dict], *, system: str | None = None,
               temperature: float = 0.8, max_tokens: int = 600) -> AsyncIterator[str]: ...

    async def structured(self, messages: list[dict], schema: type[T], *, system: str | None = None,
                         temperature: float = 0.2, max_tokens: int = 800) -> tuple[T, LLMResult]: ...


def strip_thinking(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # unterminated think block (model cut off mid-thought)
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def _schema_for(model: type[BaseModel]) -> dict:
    """JSON schema suitable for Ollama's grammar-constrained ``format``."""
    schema = model.model_json_schema()
    return schema


def schema_hint(model: type[BaseModel]) -> str:
    """
    Compact, human-readable field guide appended to the system prompt.

    Ollama's ``format`` only constrains decoding — the model never sees the
    schema text — so without this hint it cannot know what a field means and
    tends to leave lists empty.
    """
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    lines: list[str] = []

    def describe(props: dict, indent: str, depth: int) -> None:
        for name, spec in props.items():
            ref = spec.get("$ref") or (spec.get("items") or {}).get("$ref")
            any_of = spec.get("anyOf") or []
            if not ref:
                ref = next((a.get("$ref") for a in any_of if a.get("$ref")), None)
                ref = ref or next(((a.get("items") or {}).get("$ref") for a in any_of if a.get("items")), None)
            typ = spec.get("type") or next((a.get("type") for a in any_of if a.get("type") != "null"), "")
            enum = spec.get("enum") or next((a.get("enum") for a in any_of if a.get("enum")), None)
            desc = spec.get("description", "")
            bits = [f"{indent}- {name}"]
            if typ == "array":
                bits.append("(list)")
            if enum:
                bits.append("one of: " + "|".join(map(str, enum)))
            if desc:
                bits.append(f"— {desc}")
            lines.append(" ".join(bits))
            if ref and depth < 2:
                sub = defs.get(ref.split("/")[-1], {})
                describe(sub.get("properties", {}), indent + "  ", depth + 1)

    describe(schema.get("properties", {}), "", 0)
    return "JSON FIELDS:\n" + "\n".join(lines)


class OllamaClient:
    """Async client for a local Ollama server (``/api/chat``)."""

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", *,
                 num_ctx: int = 8192, keep_alive: str = "30m", timeout: float = 180.0,
                 retries: int = 2, extra_options: dict | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.timeout = timeout
        self.retries = retries
        self.extra_options = extra_options or {}
        self._client: httpx.AsyncClient | None = None

    # ── plumbing ────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    def _payload(self, messages: list[dict], system: str | None, *, stream: bool,
                 temperature: float, max_tokens: int, fmt: dict | str | None = None) -> dict:
        msgs = list(messages)
        if system:
            msgs = [{"role": "system", "content": system}] + msgs
        options = {
            "num_ctx": self.num_ctx,
            "temperature": temperature,
            "num_predict": max_tokens,
            **self.extra_options,
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "stream": stream,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": options,
        }
        if fmt is not None:
            payload["format"] = fmt
        return payload

    @staticmethod
    def _result_from(data: dict, text: str, started: float, first_token: float | None) -> LLMResult:
        ns = 1e9
        return LLMResult(
            text=text,
            prompt_tokens=data.get("prompt_eval_count", 0) or 0,
            output_tokens=data.get("eval_count", 0) or 0,
            prompt_seconds=(data.get("prompt_eval_duration", 0) or 0) / ns,
            output_seconds=(data.get("eval_duration", 0) or 0) / ns,
            total_seconds=time.perf_counter() - started,
            first_token_seconds=first_token,
            raw={k: v for k, v in data.items() if k != "message"},
        )

    async def _post_chat(self, payload: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = await self._http().post("/api/chat", json=payload)
                if resp.status_code >= 400:
                    raise LLMError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
                return resp.json()
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                log.warning("LLM request failed (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM unreachable: {last_exc}")

    # ── public API ──────────────────────────────────────────────

    async def complete(self, messages: list[dict], *, system: str | None = None,
                       temperature: float = 0.8, max_tokens: int = 600) -> LLMResult:
        started = time.perf_counter()
        data = await self._post_chat(self._payload(messages, system, stream=False,
                                                   temperature=temperature, max_tokens=max_tokens))
        text = strip_thinking(data.get("message", {}).get("content", "") or "")
        return self._result_from(data, text, started, None)

    async def stream(self, messages: list[dict], *, system: str | None = None,
                     temperature: float = 0.8, max_tokens: int = 600,
                     stats: dict | None = None) -> AsyncIterator[str]:
        """Yield text chunks. If ``stats`` dict is given it is filled with an LLMResult at the end."""
        payload = self._payload(messages, system, stream=True, temperature=temperature, max_tokens=max_tokens)
        started = time.perf_counter()
        first_token: float | None = None
        full: list[str] = []
        in_think = False
        try:
            async with self._http().stream("POST", "/api/chat", json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise LLMError(f"Ollama HTTP {resp.status_code}: {body[:300]!r}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = chunk.get("message", {}).get("content", "") or ""
                    if piece:
                        # suppress stray <think> blocks some models emit despite think=false
                        if "<think>" in piece:
                            in_think = True
                            piece = piece.split("<think>", 1)[0]
                        if in_think:
                            if "</think>" in piece:
                                in_think = False
                                piece = piece.split("</think>", 1)[1]
                            else:
                                piece = ""
                        if piece:
                            if first_token is None:
                                first_token = time.perf_counter() - started
                            full.append(piece)
                            yield piece
                    if chunk.get("done"):
                        if stats is not None:
                            stats["result"] = self._result_from(chunk, "".join(full), started, first_token)
                        break
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise LLMError(f"LLM stream failed: {exc}") from exc

    async def structured(self, messages: list[dict], schema: type[T], *, system: str | None = None,
                         temperature: float = 0.2, max_tokens: int = 800) -> tuple[T, LLMResult]:
        fmt = _schema_for(schema)
        msgs = list(messages)
        system = f"{system}\n\n{schema_hint(schema)}" if system else schema_hint(schema)
        last_err = ""
        for attempt in range(2):
            started = time.perf_counter()
            data = await self._post_chat(self._payload(msgs, system, stream=False, temperature=temperature,
                                                       max_tokens=max_tokens, fmt=fmt))
            text = strip_thinking(data.get("message", {}).get("content", "") or "")
            result = self._result_from(data, text, started, None)
            try:
                return schema.model_validate_json(_extract_json(text)), result
            except (ValidationError, ValueError) as exc:
                last_err = str(exc)[:500]
                log.warning("structured output invalid (attempt %d): %s", attempt + 1, last_err)
                msgs = msgs + [
                    {"role": "assistant", "content": text[:2000]},
                    {"role": "user", "content": f"That JSON was invalid: {last_err}\nReturn ONLY corrected JSON."},
                ]
        raise LLMError(f"structured output invalid after retry: {last_err}")

    async def health(self) -> bool:
        try:
            r = await self._http().get("/api/version")
            return r.status_code == 200
        except httpx.HTTPError:
            return False


def _extract_json(text: str) -> str:
    """Pull the first JSON object/array out of model text (fences, chatter tolerated)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    if t.startswith("{") or t.startswith("["):
        return t
    m = re.search(r"[\[{].*[\]}]", t, re.S)
    if not m:
        raise ValueError("no JSON found in model output")
    return m.group(0)
