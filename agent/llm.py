"""All Gemini calls go through here: one timeout, one retry policy, one model."""
import re
import time
from typing import Optional, TypeVar
from google import genai
from google.genai import types
from pydantic import BaseModel

from agent.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TIMEOUT_MS

client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=LLM_TIMEOUT_MS),
)

T = TypeVar("T", bound=BaseModel)
MAX_RATE_LIMIT_WAIT = 45


class LLMUnavailable(Exception):
    """Gemini failed after all retries. Callers decide how to degrade."""


def _rate_limit_delay(err: Exception) -> Optional[float]:
    """If this is a 429, return how long Google asks us to wait."""
    s = str(err)
    if "429" not in s and "RESOURCE_EXHAUSTED" not in s:
        return None
    m = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", s)
    return float(m.group(1)) if m else 20.0


def generate(contents, *, tools: Optional[list] = None,
             schema: Optional[type[BaseModel]] = None,
             system: Optional[str] = None, retries: int = 3):
    config = types.GenerateContentConfig(
        temperature=0,
        system_instruction=system,
        tools=tools,
        response_mime_type="application/json" if schema else None,
        response_schema=schema,
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            return client.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=config)
        except Exception as e:
            last_error = e
            if attempt == retries:
                break
            delay = _rate_limit_delay(e)
            if delay is not None:
                print(f"[llm     ] rate limited, waiting {min(delay + 1, MAX_RATE_LIMIT_WAIT):.0f}s")
                time.sleep(min(delay + 1, MAX_RATE_LIMIT_WAIT))
            else:
                time.sleep(1.5 * (attempt + 1))
    raise LLMUnavailable(str(last_error)[:300])


def generate_json(contents, schema: type[T], system: Optional[str] = None) -> T:
    """Ask Gemini for output that must match a Pydantic schema."""
    r = generate(contents, schema=schema, system=system)
    if isinstance(r.parsed, schema):
        return r.parsed
    return schema.model_validate_json(r.text)
