"""OpenAI API settings for optional real-world explanation features.

The real-world visualizer currently uses deterministic explanations and should
not call OpenAI by default. This module centralizes future LLM configuration so
any optional use starts from a lightweight model and an explicit enable flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class OpenAISettings:
    enabled: bool
    model: str
    has_api_key: bool


def load_openai_settings(environ: Mapping[str, str] | None = None) -> OpenAISettings:
    env = os.environ if environ is None else environ
    enabled_raw = env.get("HADES_OPENAI_ENABLED", "0").strip().lower()
    model = env.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
    return OpenAISettings(
        enabled=enabled_raw in {"1", "true", "yes", "on"},
        model=model,
        has_api_key=bool(env.get("OPENAI_API_KEY", "").strip()),
    )
