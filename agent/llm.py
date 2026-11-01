"""All Gemini calls go through here: one timeout, one retry policy, one model."""
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


class LLMUnavailable(Exception):
    """Gemini failed after all retries. Callers decide how to degrade."""


def generate(contents, *, tools: Optional[list] = None,
             schema: Optional[type[BaseModel]] = None,
             system: Optional[str] = None, retries: int = 2):
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
        except Exception as e:      # timeouts, 5xx, rate limits
            last_error = e
            time.sleep(1.5 * (attempt + 1))
    raise LLMUnavailable(str(last_error)[:300])


def generate_json(contents, schema: type[T], system: Optional[str] = None) -> T:
    """Ask Gemini for output that must match a Pydantic schema."""
    r = generate(contents, schema=schema, system=system)
    if isinstance(r.parsed, schema):
        return r.parsed
    return schema.model_validate_json(r.text)
