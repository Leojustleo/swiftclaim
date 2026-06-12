import json

import pytest
from pydantic import BaseModel

import app.llm as llm


class Out(BaseModel):
    x: int


class FakeResponse:
    def __init__(self, status_code, content=None, text=""):
        self.status_code = status_code
        self.text = text
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


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
