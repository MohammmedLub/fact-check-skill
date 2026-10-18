"""Thin wrapper around the Claude API that returns validated pydantic objects."""

from __future__ import annotations

import json
import os
from typing import Protocol, TypeVar

from pydantic import BaseModel

from .schemas import strict_schema

DEFAULT_MODEL = os.environ.get("HAYAT_MODEL", "claude-opus-5-5")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def structured(self, system: str, user: str, output: type[T], effort: str = "medium") -> T: ...


class Claude:
    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        import anthropic

        self.model = model
        self.client = client or anthropic.Anthropic()

    def structured(self, system: str, user: str, output: type[T], effort: str = "medium") -> T:
        # Streaming keeps long lessons clear of HTTP timeouts; the server-side
        # fallback re-runs the request on another model if this one declines.
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": strict_schema(output)},
            },
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise LLMError("Claude declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The response was cut off (max_tokens). Try a shorter video.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return output.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(f"Could not parse Claude's answer: {exc}") from exc
