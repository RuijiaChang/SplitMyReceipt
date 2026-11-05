"""The single place that talks to an AI model. Supports OpenAI (default) and Gemini.

Choose with environment variables (or a .env file):
    AI_PROVIDER=openai | gemini        optional; auto-detected from whichever key is set
    OPENAI_API_KEY=...   OPENAI_MODELS=gpt-5.4-mini,gpt-5.4-nano
    GEMINI_API_KEY=...   GEMINI_MODELS=gemini-flash-latest,gemini-flash-lite-latest
No key at all -> the app runs in demo mode (no AI calls).

Both providers get the same JSON Schema and must answer with JSON that follows it.
Temporary failures (overloaded 503, rate limit 429, timeouts) are retried with a
short backoff, then the next model in the list is tried. Errors that won't fix
themselves (bad key, bad request) fail immediately with a clear message.
"""
from __future__ import annotations

import base64
import json
import os
import time

PROVIDERS = {
    "openai": {"label": "OpenAI", "key": "OPENAI_API_KEY", "models": "OPENAI_MODELS",
               "default": "gpt-5.4-mini,gpt-5.4-nano"},
    "gemini": {"label": "Gemini", "key": "GEMINI_API_KEY", "models": "GEMINI_MODELS",
               "default": "gemini-flash-latest,gemini-flash-lite-latest"},
}
RETRYABLE = {408, 409, 429, 500, 502, 503, 504}
ATTEMPTS_PER_MODEL = 2
BACKOFF_SECONDS = 1.5


class AIError(RuntimeError):
    pass


# ------------------------------------------------------------------ config (read at call time, so .env works)
def provider() -> str | None:
    """'openai', 'gemini', or None (demo mode)."""
    chosen = os.environ.get("AI_PROVIDER", "").strip().lower()
    if chosen in PROVIDERS:
        return chosen if os.environ.get(PROVIDERS[chosen]["key"], "").strip() else None
    for name, p in PROVIDERS.items():  # auto-detect: OpenAI first
        if os.environ.get(p["key"], "").strip():
            return name
    return None


def label(name: str | None = None) -> str:
    name = name or provider()
    return PROVIDERS[name]["label"] if name else "Demo"


def models(name: str) -> list[str]:
    p = PROVIDERS[name]
    legacy = os.environ.get("GEMINI_MODEL") if name == "gemini" else os.environ.get("OPENAI_MODEL")
    raw = os.environ.get(p["models"]) or legacy or p["default"]
    return [m.strip() for m in raw.split(",") if m.strip()]


# ------------------------------------------------------------------ retry / fallback (provider-agnostic)
def status_of(e: Exception | None) -> int | None:
    if e is None:
        return None
    code = getattr(e, "status_code", None) or getattr(e, "code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        name = type(e).__name__
        return 503 if ("Timeout" in name or "Connection" in name) else None


def with_fallback(model_list: list[str], call, *, who: str = "The AI", sleep=time.sleep) -> dict:
    """call(model) -> response text. Returns parsed JSON or raises AIError."""
    last: Exception | None = None
    for model in model_list:
        for attempt in range(ATTEMPTS_PER_MODEL):
            try:
                return json.loads(call(model) or "{}")
            except json.JSONDecodeError as e:
                last = e
                break  # garbled answer: try the next model
            except Exception as e:  # noqa: BLE001 - SDK errors vary by provider
                last = e
                code = status_of(e)
                if code == 404:
                    break  # model not available on this account: try the next one
                if code not in RETRYABLE:
                    raise AIError(friendly(e, who)) from e
                if attempt < ATTEMPTS_PER_MODEL - 1:
                    sleep(BACKOFF_SECONDS * (attempt + 1))
    raise AIError(friendly(last, who))


def friendly(e: Exception | None, who: str = "The AI") -> str:
    code = status_of(e)
    if isinstance(e, json.JSONDecodeError):
        return f"{who} returned an answer we couldn't read. Please try again."
    if code in (500, 502, 503, 504, 408, 409):
        return f"{who} is overloaded right now (tried several times and a backup model). Wait a minute and try again, or type it in yourself."
    if code == 429:
        return f"{who} rate limit or quota reached for this API key. Wait a minute, or check the account's billing."
    if code in (401, 403):
        return f"The server's {who} API key was rejected. Check the key in the server's environment."
    return f"{who} request failed: {str(e)[:160]}"


# ------------------------------------------------------------------ providers
def _openai_call(api_key: str, prompt: str, schema: dict, image: tuple[bytes, str] | None):
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=45, max_retries=0)  # we do our own retries
    content: list[dict] = [{"type": "text", "text": prompt}]
    if image:
        data, mime = image
        content.append({"type": "image_url", "image_url": {
            "url": f"data:{mime};base64,{base64.b64encode(data).decode()}", "detail": "high"}})

    def call(model: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "result", "schema": schema, "strict": True}},
        )
        return resp.choices[0].message.content
    return call


def _gemini_call(api_key: str, prompt: str, schema: dict, image: tuple[bytes, str] | None):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45_000))  # ms
    contents: list = [prompt]
    if image:
        contents.insert(0, types.Part.from_bytes(data=image[0], mime_type=image[1]))
    config = types.GenerateContentConfig(response_mime_type="application/json",
                                         response_json_schema=schema, temperature=0)

    def call(model: str) -> str:
        return client.models.generate_content(model=model, contents=contents, config=config).text
    return call


def generate_json(prompt: str, schema: dict, image: tuple[bytes, str] | None = None) -> dict:
    """Ask the configured provider for JSON matching `schema`. image = (bytes, mime)."""
    name = provider()
    if not name:
        raise AIError("No AI key is configured on the server.")
    key = os.environ[PROVIDERS[name]["key"]].strip()
    make = _openai_call if name == "openai" else _gemini_call
    return with_fallback(models(name), make(key, prompt, schema, image), who=label(name))
