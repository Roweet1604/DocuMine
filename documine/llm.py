"""The only place that talks to Gemini. Retries rate limits and temporary errors with backoff."""

import time

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from documine import config

MAX_ATTEMPTS = 5
FIRST_DELAY_SECONDS = 2
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

_client = None


class LLMError(RuntimeError):
    """Raised with a message that is safe to show in the UI."""


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.require("GEMINI_API_KEY"))
    return _client


def _explain(error: errors.APIError) -> str:
    code = error.code
    if code == 429:
        return "Gemini rate limit reached. Wait a minute and try again."
    if code in (401, 403):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
    if code == 404:
        return f"Gemini model '{config.GEMINI_MODEL}' was not found. Check GEMINI_MODEL in .env."
    if code == 400:
        return f"Gemini rejected the request: {error.message}"
    if code is not None and code >= 500:
        return "Gemini is temporarily unavailable. Try again in a moment."
    return f"Gemini error {code}: {error.message}"


def _call(prompt: str, gen_config: types.GenerateContentConfig | None = None):
    delay = FIRST_DELAY_SECONDS
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _get_client().models.generate_content(
                model=config.GEMINI_MODEL, contents=prompt, config=gen_config
            )
        except errors.APIError as e:
            if e.code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS:
                raise LLMError(_explain(e)) from e
        except httpx.TransportError as e:
            if attempt == MAX_ATTEMPTS:
                raise LLMError("Could not reach Gemini. Check your internet connection.") from e
        time.sleep(delay)
        delay *= 2


def generate_text(prompt: str) -> str:
    response = _call(prompt)
    text = response.text
    if not text:
        raise LLMError("Gemini returned an empty answer (the response may have been blocked).")
    return text


def generate_json(prompt: str, schema: type[BaseModel]) -> BaseModel:
    gen_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )
    response = _call(prompt, gen_config)
    if isinstance(response.parsed, schema):
        return response.parsed
    try:
        return schema.model_validate_json(response.text or "")
    except ValidationError as e:
        raise LLMError(f"Gemini returned data that does not match {schema.__name__}.") from e
