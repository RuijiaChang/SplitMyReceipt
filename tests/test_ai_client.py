"""AI provider layer: choosing a provider, retry/fallback, request format. No network."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_client  # noqa: E402
from ai_client import AIError, with_fallback  # noqa: E402
from assigner import ASSIGN_SCHEMA  # noqa: E402
from extractor import RECEIPT_SCHEMA  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("AI_PROVIDER", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_MODELS", "GEMINI_MODELS",
              "OPENAI_MODEL", "GEMINI_MODEL"):
        monkeypatch.delenv(k, raising=False)


# ------------------------------------------------------------------ provider choice
def test_no_key_means_demo():
    assert ai_client.provider() is None and ai_client.label() == "Demo"


def test_openai_preferred_when_both_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    assert ai_client.provider() == "gemini"
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    assert ai_client.provider() == "openai"
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    assert ai_client.provider() == "gemini" and ai_client.label() == "Gemini"


def test_model_lists_are_configurable(monkeypatch):
    assert ai_client.models("openai") == ["gpt-5.4-mini", "gpt-5.4-nano"]
    monkeypatch.setenv("OPENAI_MODELS", "a, b")
    assert ai_client.models("openai") == ["a", "b"]


# ------------------------------------------------------------------ retry / fallback
class Err(Exception):
    def __init__(self, status_code):
        super().__init__(f"{status_code}")
        self.status_code = status_code


def scripted(script):
    calls = []

    def call(model):
        calls.append(model)
        r = script[model].pop(0)
        if isinstance(r, int):
            raise Err(r)
        return r
    return call, calls


def run(script):
    call, calls = scripted(script)
    return with_fallback(["main", "lite"], call, sleep=lambda s: None), calls


def test_retries_after_503():
    assert run({"main": [503, '{"ok": 1}'], "lite": []}) == ({"ok": 1}, ["main", "main"])


def test_falls_back_when_main_stays_busy():
    assert run({"main": [503, 429], "lite": ['{"ok": 2}']}) == ({"ok": 2}, ["main", "main", "lite"])


def test_unknown_model_skips_to_next():
    assert run({"main": [404], "lite": ['{"ok": 3}']}) == ({"ok": 3}, ["main", "lite"])


def test_bad_key_fails_fast():
    with pytest.raises(AIError, match="key was rejected"):
        run({"main": [401], "lite": ['{"ok": 4}']})


def test_all_busy_gives_friendly_message():
    with pytest.raises(AIError, match="overloaded"):
        run({"main": [503, 503], "lite": [503, 503]})


def test_timeouts_count_as_temporary():
    class APITimeoutError(Exception):
        pass
    seq = iter([APITimeoutError(), '{"ok": 5}'])

    def call(model):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r
    assert with_fallback(["m"], call, sleep=lambda s: None) == {"ok": 5}


# ------------------------------------------------------------------ OpenAI request format
def test_openai_request_has_image_and_strict_schema(monkeypatch):
    sent = {}

    class FakeCompletions:
        def create(self, **kw):
            sent.update(kw)
            msg = type("M", (), {"content": json.dumps({"ok": True})})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    class FakeOpenAI:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    out = ai_client.generate_json("read this", RECEIPT_SCHEMA, image=(b"\xff\xd8jpeg", "image/jpeg"))
    assert out == {"ok": True}
    assert sent["model"] == "gpt-5.4-mini"
    content = sent["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "read this"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert sent["response_format"]["json_schema"]["strict"] is True


def assert_strict(schema, path="root"):
    """OpenAI strict mode: every object lists all its properties as required and forbids extras."""
    if schema.get("type") == "object" or "properties" in schema:
        assert schema.get("additionalProperties") is False, path
        assert set(schema["required"]) == set(schema["properties"]), path
        for k, v in schema["properties"].items():
            assert_strict(v, f"{path}.{k}")
    if "items" in schema:
        assert_strict(schema["items"], f"{path}[]")


def test_schemas_are_valid_for_openai_strict_mode():
    assert_strict(RECEIPT_SCHEMA)
    assert_strict(ASSIGN_SCHEMA)
