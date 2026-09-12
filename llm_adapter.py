from __future__ import annotations
from .deepseek_client import configured, chat


def rewrite_with_llm(system_prompt: str, user_prompt: str, fallback: str) -> str:
    text, _meta = chat(system_prompt, user_prompt, fallback)
    return text
