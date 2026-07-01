from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

import httpx
from pydantic import BaseModel, ValidationError

PIPELINE_VERSION = "2.0"

BACKEND_ENV = Path(__file__).parent.parent / ".env"
PIPELINE_ENV = Path(__file__).parent.parent.parent / "law-pipeline" / ".env"

PII_FIELDS = [
    ("customer_name", "[KUND]"),
    ("customer_email", "[EPOST]"),
    ("customer_phone", "[TELEFON]"),
    ("property_address", "[ADRESS]"),
]


class LLMError(RuntimeError):
    pass


def _read_env_key(name: str, env_file: Path) -> Optional[str]:
    key = os.environ.get(name)
    if key:
        return key
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    return None


PROVIDERS = [
    {
        "name": "deepseek",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "key": lambda: _read_env_key("DEEPSEEK_API_KEY", BACKEND_ENV),
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "moonshotai/kimi-k2.6",
        "key": lambda: _read_env_key("OPENROUTER_API_KEY", PIPELINE_ENV),
    },
]


def scrub_pii(text: str, case_fields: Dict[str, Any]) -> str:
    out = text or ""
    for field, placeholder in PII_FIELDS:
        val = str(case_fields.get(field) or "").strip()
        if len(val) >= 4:
            out = out.replace(val, placeholder)
    return out


def unscrub_pii(text: str, case_fields: Dict[str, Any]) -> str:
    out = text or ""
    for field, placeholder in PII_FIELDS:
        val = str(case_fields.get(field) or "").strip()
        if val:
            out = out.replace(placeholder, val)
    return out


def _log_call(db, job_id, stage, provider, model, status, error, latency_ms, prompt_text, response_text):
    if db is None:
        return
    from app.models import LLMCall

    try:
        db.add(LLMCall(
            job_id=job_id, stage=stage, provider=provider, model=model,
            status=status, error=error, latency_ms=latency_ms,
            prompt_text=(prompt_text or "")[:50000],
            response_text=(response_text or "")[:50000],
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[llm] call log failed: {e}")


def chat_json(
    system: str,
    user: str,
    schema: Type[BaseModel],
    *,
    db=None,
    job_id: Optional[str] = None,
    stage: str = "",
    max_tokens: int = 4000,
    timeout: float = 120.0,
) -> Tuple[BaseModel, Dict[str, Any]]:
    """JSON-mode chat across the provider chain, schema-validated.

    Per provider: up to 2 attempts (covers one 5xx/timeout retry OR one
    schema-error reprompt), then the next provider. Raises LLMError when
    all providers are exhausted. Returns (parsed, meta).
    """
    prompt_log = f"[system]\n{system}\n\n[user]\n{user}"
    last_err = "no LLM provider configured"
    for prov in PROVIDERS:
        key = prov["key"]()
        if not key:
            continue
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for attempt in range(2):
            t0 = time.time()
            try:
                r = httpx.post(
                    prov["url"],
                    json={
                        "model": prov["model"],
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "max_tokens": max_tokens,
                    },
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=timeout,
                )
            except httpx.RequestError as e:
                last_err = f"{prov['name']}: {e}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error", str(e),
                          int((time.time() - t0) * 1000), prompt_log, None)
                continue
            latency = int((time.time() - t0) * 1000)
            if r.status_code >= 500:
                last_err = f"{prov['name']}: HTTP {r.status_code}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"HTTP {r.status_code}: {r.text[:300]}", latency, prompt_log, None)
                continue
            if r.status_code != 200:
                last_err = f"{prov['name']}: HTTP {r.status_code} {r.text[:200]}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"HTTP {r.status_code}: {r.text[:300]}", latency, prompt_log, None)
                break
            try:
                choice = r.json()["choices"][0]
                raw = choice["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError):
                raw = None
            if not isinstance(raw, str) or not raw.strip():
                last_err = f"{prov['name']}: malformed response body"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"malformed: {r.text[:300]}", latency, prompt_log, None)
                continue
            if choice.get("finish_reason") == "length":
                last_err = f"{prov['name']}: output truncated at max_tokens={max_tokens}"
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          last_err, latency, prompt_log, raw)
                continue
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as e:
                _log_call(db, job_id, stage, prov["name"], prov["model"], "error",
                          f"schema: {str(e)[:500]}", latency, prompt_log, raw)
                last_err = f"{prov['name']}: schema validation failed"
                if attempt == 0:
                    messages = messages + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": (
                            "Ditt svar validerade inte mot schemat: "
                            f"{str(e)[:800]}\nSvara igen med endast giltig JSON enligt instruktionerna."
                        )},
                    ]
                    continue
                break
            _log_call(db, job_id, stage, prov["name"], prov["model"], "ok", None, latency, prompt_log, raw)
            return parsed, {"provider": prov["name"], "model": prov["model"], "latency_ms": latency}
    raise LLMError(last_err)
