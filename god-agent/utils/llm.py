"""
utils/llm.py — Unified LLM client with automatic fallback chain.

Provider order: Gemini → Groq → OpenRouter → Ollama (local, unlimited, free)
Ollama replaces DeepSeek as the last-resort tier — it never runs out of credits.
"""
from __future__ import annotations

import os
import time
from typing import Optional

GROQ_MODELS: dict[str, str] = {
    "llama":   "llama-3.3-70b-versatile",
    "llama3":  "llama-3.3-70b-versatile",
    "mixtral": "mixtral-8x7b-32768",
    "gemma":   "gemma2-9b-it",
    "fast":    "gemma2-9b-it",
    "long":    "mixtral-8x7b-32768",
    "best":    "llama-3.3-70b-versatile",
    "default": "llama-3.3-70b-versatile",
}
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def _resolve_groq(hint: Optional[str]) -> str:
    if not hint:
        return os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    return GROQ_MODELS.get(hint.lower().strip(), hint)


def _call_gemini(system: str, messages: list[dict], max_tokens: int) -> str:
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set.")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)
    formatted = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        formatted.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
    resp = client.models.generate_content(
        model=model,
        contents=formatted,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=max_tokens,
        ),
    )
    return (resp.text or "").strip()


def _call_groq(system: str, messages: list[dict], model: str, max_tokens: int) -> str:
    from groq import Groq
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set.")
    client = Groq(api_key=api_key)
    full = [{"role": "system", "content": system}] + messages
    if len(full) > 13:
        full = [full[0]] + full[-12:]
    resp = client.chat.completions.create(
        model=model,
        messages=full,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _call_openrouter(system: str, messages: list[dict], max_tokens: int) -> str:
    from openai import OpenAI
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set.")
    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    model = os.environ.get("OPENROUTER_MODEL", "google/gemini-flash-1.5")
    full = [{"role": "system", "content": system}] + messages
    resp = client.chat.completions.create(
        model=model, messages=full, temperature=0.2, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _call_ollama(system: str, messages: list[dict], max_tokens: int) -> str:
    """
    Local Ollama fallback — completely free, no credits, no rate limits.
    Requires: ollama serve (running in background)
    Models:   ollama pull qwen2.5:1.5b
              ollama pull qwen2.5-coder:1.5b
              ollama pull moondream
    """
    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
    full = [{"role": "system", "content": system}] + messages
    resp = client.chat.completions.create(
        model=model,
        messages=full,
        temperature=0.2,
        max_tokens=min(max_tokens, 1024),  # keep lean on local hardware
    )
    return resp.choices[0].message.content or ""


def call_llm(
    system: str,
    messages: list[dict],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 4096,
) -> str:
    """
    Call LLM with automatic fallback chain.
    Order: env GOD_LLM_PROVIDER → gemini → groq → openrouter → ollama
    Ollama is always last — it's local and never exhausted.
    """
    provider = (provider or os.environ.get("GOD_LLM_PROVIDER", "gemini")).lower()
    all_providers = ["gemini", "groq", "openrouter", "ollama"]
    chain = [provider] + [p for p in all_providers if p != provider]

    last_error: Exception = RuntimeError("No provider configured.")

    for prov in chain:
        for attempt in range(3):
            try:
                if prov == "gemini":
                    if not os.environ.get("GEMINI_API_KEY"):
                        break
                    return _call_gemini(system, messages, max_tokens)
                elif prov == "groq":
                    if not os.environ.get("GROQ_API_KEY"):
                        break
                    resolved = _resolve_groq(model)
                    return _call_groq(system, messages, resolved, max_tokens)
                elif prov == "openrouter":
                    if not os.environ.get("OPENROUTER_API_KEY"):
                        break
                    return _call_openrouter(system, messages, max_tokens)
                elif prov == "ollama":
                    return _call_ollama(system, messages, max_tokens)

            except Exception as exc:
                last_error = exc
                err = str(exc).lower()

                # Daily/quota limit → jump to next provider immediately
                if any(k in err for k in ["day", "quota", "credit", "billing", "insufficient", "402"]):
                    print(f"  [{prov} limit/credits] → trying next provider...")
                    break

                # Connection refused = Ollama not running
                if prov == "ollama" and ("refused" in err or "connect" in err):
                    print(f"  [ollama] not running — start with: ollama serve")
                    break

                # 403 = network/auth block → skip immediately
                if "403" in err:
                    print(f"  [{prov}] access denied (403) → trying next provider...")
                    break

                # RPM rate limit → backoff and retry
                if "429" in err or ("rate" in err and "limit" in err):
                    wait = 20 * (attempt + 1)
                    print(f"  [{prov} rate limit] waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if attempt >= 2:
                    print(f"  [{prov}] failed: {exc}")
                    break
                time.sleep(3)

    raise RuntimeError(f"All providers exhausted. Last error: {last_error}")
