import json

import pytest
from pydantic import BaseModel

import app.llm as llm


class Out(BaseModel):
    x: int


class FakeResponse:
    def __init__(self, status_code, content=None, text="", finish_reason="stop"):
        self.status_code = status_code
        self.text = text
        self._content = content
        self._finish_reason = finish_reason

    def json(self):
        return {"choices": [{"message": {"content": self._content},
                             "finish_reason": self._finish_reason}]}


def test_fallback_to_second_provider(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "deepseek" in url:
            return FakeResponse(500, text="boom")
        return FakeResponse(200, content=json.dumps({"x": 7}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 7
    assert meta["provider"] == "openrouter"
    assert len(calls) == 3  # 2 deepseek attempts + 1 openrouter


def test_schema_reprompt_then_success(monkeypatch):
    responses = [FakeResponse(200, content="not json at all"),
                 FakeResponse(200, content=json.dumps({"x": 1}))]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    parsed, _ = llm.chat_json("s", "u", Out)
    assert parsed.x == 1


def test_all_fail_raises(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: FakeResponse(500, text="x"))
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    with pytest.raises(llm.LLMError):
        llm.chat_json("s", "u", Out)


class ErrorBodyResponse(FakeResponse):
    def json(self):
        return {"error": {"message": "overloaded"}}


class NullContentResponse(FakeResponse):
    def json(self):
        return {"choices": [{"message": {"content": None}}]}


def test_malformed_200_falls_through_to_next_provider(monkeypatch):
    def fake_post(url, **kwargs):
        if "deepseek" in url:
            return ErrorBodyResponse(200, text="overloaded")
        return FakeResponse(200, content=json.dumps({"x": 3}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 3
    assert meta["provider"] == "openrouter"


def test_null_content_raises_llm_error_not_type_error(monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda url, **kw: NullContentResponse(200))
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "u", "model": "m", "key": lambda: "k"},
    ])
    with pytest.raises(llm.LLMError):
        llm.chat_json("s", "u", Out)


def test_truncated_output_skips_schema_reprompt(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"]["messages"])
        if "deepseek" in url:
            return FakeResponse(200, content='{"x": ', finish_reason="length")
        return FakeResponse(200, content=json.dumps({"x": 5}))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm, "PROVIDERS", [
        {"name": "deepseek", "url": "https://api.deepseek.com/x", "model": "m1", "key": lambda: "k"},
        {"name": "openrouter", "url": "https://openrouter.ai/x", "model": "m2", "key": lambda: "k"},
    ])
    parsed, meta = llm.chat_json("s", "u", Out)
    assert parsed.x == 5
    # no re-prompt: every request must be the original 2-message payload
    assert all(len(m) == 2 for m in calls)
