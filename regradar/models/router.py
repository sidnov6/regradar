"""LLM gateway + failover chain + structured-output repair (Parts 11.2 & 11.4).

The blueprint routes every agent through LiteLLM with an ordered fallback chain
ending at a local floor, so a 429/5xx on one provider transparently falls through
to the next and the system cannot hard-fail on rate limits.

Chain (only providers with credentials/reachability are included):
    Groq -> Gemini -> OpenRouter(:free) -> Ollama(local) -> deterministic mock floor

The mock floor means the pipeline (and CI) runs with zero keys: deterministic code
paths are exercised and LLM calls return a clearly-labelled stub rather than crashing.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from regradar import config

T = TypeVar("T", bound=BaseModel)


class SchemaRepairFailed(Exception):
    """Raised when structured output fails validation after all repair retries.
    Callers catch this, flag it, and route to a human gate (never pass garbage on)."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: float
    tokens: Optional[int] = None
    is_mock: bool = False


# ---------------------------------------------------------------------------
# Provider definitions — declarative, so the chain is data not branching code.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Provider:
    name: str
    model: str          # litellm-style model id
    available: Callable[[], bool]


def _groq_available() -> bool:
    return bool(config.GROQ_API_KEY)


def _gemini_available() -> bool:
    return bool(config.GOOGLE_API_KEY)


def _openrouter_available() -> bool:
    return bool(config.OPENROUTER_API_KEY)


def _ollama_available() -> bool:
    try:
        import httpx

        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


# Ordered chain. "reason" workhorse uses Gemini-first per the blueprint; Groq is the
# fast classifier. Here we keep one general chain and let callers pick a role hint.
DEFAULT_CHAIN: tuple[Provider, ...] = (
    Provider("groq", "groq/llama-3.3-70b-versatile", _groq_available),
    Provider("gemini", "gemini/gemini-2.5-flash", _gemini_available),
    Provider("openrouter", "openrouter/meta-llama/llama-3.3-70b-instruct:free", _openrouter_available),
    Provider("ollama", "ollama/qwen2.5", _ollama_available),
)


class Router:
    """Thin wrapper over LiteLLM with an availability-filtered failover chain.

    Falls back to a deterministic mock if no provider is reachable, so nothing
    in the pipeline hard-fails on missing keys (worst case is slower / stubbed).
    """

    def __init__(self, chain: tuple[Provider, ...] = DEFAULT_CHAIN, temperature: float = 0.0):
        self.chain = chain
        self.temperature = temperature

    # -- raw completion -----------------------------------------------------
    def complete(self, prompt: str, *, temperature: Optional[float] = None) -> LLMResult:
        temp = self.temperature if temperature is None else temperature

        # Exact cache (Part 11.6): reuse prior completions, don't re-spend quota.
        from regradar.models.cache import cache

        hit = cache.get(prompt, temp)
        if hit is not None:
            return LLMResult(hit["text"], "cache", hit.get("model", "cache"), 0.0,
                             hit.get("tokens"), is_mock=False)

        live = [p for p in self.chain if p.available()]
        try:
            import litellm  # lazy: optional dependency (extras = "llm")

            litellm.suppress_debug_info = True
        except ImportError:
            return self._mock(prompt, reason="litellm not installed")

        last_err: Optional[Exception] = None
        for provider in live:
            t0 = time.perf_counter()
            try:
                resp = litellm.completion(
                    model=provider.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temp,
                )
                dt = (time.perf_counter() - t0) * 1000
                text = resp["choices"][0]["message"]["content"]
                tokens = (resp.get("usage") or {}).get("total_tokens")
                cache.put(prompt, temp, {"text": text, "model": provider.model, "tokens": tokens})
                return LLMResult(text, provider.name, provider.model, dt, tokens)
            except Exception as e:  # transparent fall-through (429/5xx/etc.)
                last_err = e
                continue
        return self._mock(prompt, reason=f"all providers exhausted: {last_err}")

    # -- structured output + repair-retry (Part 11.2) -----------------------
    def call_structured(
        self,
        prompt: str,
        schema: Type[T],
        *,
        max_repair: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> tuple[T, LLMResult]:
        """Return a schema-validated object. On validation failure, re-prompt with
        the exact error up to N times; if still failing, raise SchemaRepairFailed
        (caught upstream, flagged, routed to a human gate)."""
        max_repair = config.SCHEMA_MAX_REPAIR if max_repair is None else max_repair
        last_err: Optional[Exception] = None
        result: Optional[LLMResult] = None
        for attempt in range(max_repair + 1):
            full = prompt if attempt == 0 else (
                f"{prompt}\n\nYour previous output failed validation with this error:\n"
                f"{last_err}\nReturn ONLY valid JSON matching the schema."
            )
            result = self.complete(full, temperature=temperature)
            try:
                obj = schema.model_validate_json(_extract_json(result.text))
                return obj, result
            except (ValidationError, ValueError) as e:
                last_err = e
        raise SchemaRepairFailed(str(last_err))

    # -- deterministic floor ------------------------------------------------
    def _mock(self, prompt: str, *, reason: str) -> LLMResult:
        h = hashlib.sha256(prompt.encode()).hexdigest()[:8]
        return LLMResult(
            text=f'{{"_mock": true, "reason": "{reason}", "prompt_sha": "{h}"}}',
            provider="mock",
            model="deterministic-floor",
            latency_ms=0.0,
            is_mock=True,
        )

    @property
    def active_providers(self) -> list[str]:
        return [p.name for p in self.chain if p.available()] or ["mock"]


def _extract_json(text: str) -> str:
    """Pull the first JSON object/array out of a possibly chatty LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return m.group(1) if m else text


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


# A module-level default the agents import.
router = Router()
