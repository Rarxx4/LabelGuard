"""AI providers behind one small interface.

Every provider implements:
* structured()  - one call that must return a given Pydantic model
                  (structured outputs: the response is schema-validated).
* stream_text() - streaming free-text answers for the follow-up chat.

Supported: Google Gemini (default - has a free tier) and Anthropic Claude.
The pipeline builds requests as provider-neutral content blocks
(image_block / text_block); each client converts them to its own API format.

Responses of structured() are cached on disk keyed by a hash of the full
request, so re-running the same files (e.g. while recording a demo) is
instant and free.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import time
from typing import Iterator, Type, TypeVar

from pydantic import BaseModel, ValidationError

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def image_block(png_bytes: bytes, media_type: str = "image/png") -> dict:
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(png_bytes).decode()},
    }


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


class BaseLLM:
    provider = "base"
    model = ""

    def _cache_key(self, name: str, system: str, content: list, schema: Type[BaseModel], effort: str) -> str:
        payload = json.dumps(
            {"p": self.provider, "n": name, "m": self.model, "s": system, "c": content,
             "o": schema.model_json_schema(), "e": effort},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def structured(self, name: str, system: str, content: list, schema: Type[T], effort: str = "medium") -> T:
        key = self._cache_key(name, system, content, schema, effort)
        cache_file = config.CACHE_DIR / f"{name}-{key}.json"
        if config.USE_CACHE and cache_file.exists():
            return schema.model_validate_json(cache_file.read_text(encoding="utf-8"))
        result = self._structured(name, system, content, schema, effort)
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(result.model_dump_json(), encoding="utf-8")
        return result

    def _structured(self, name, system, content, schema, effort):
        raise NotImplementedError

    def chat(self, system: str, messages: list[dict], effort: str = "medium") -> Iterator[str]:
        """Streaming chat answer; a complete answer is cached, so asking the same question again is instant."""
        key = hashlib.sha256(json.dumps({"p": self.provider, "m": self.model, "s": system, "c": messages},
                                        sort_keys=True).encode()).hexdigest()[:32]
        cache_file = config.CACHE_DIR / f"chat-{key}.txt"
        if config.USE_CACHE and cache_file.exists():
            yield cache_file.read_text(encoding="utf-8")
            return
        parts, ok = [], True
        for chunk in self.stream_text(system, messages, effort):
            if chunk.startswith("\n\n_("):  # provider error message - don't cache it
                ok = False
            parts.append(chunk)
            yield chunk
        if ok and parts:
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file.write_text("".join(parts), encoding="utf-8")

    def stream_text(self, system: str, messages: list[dict], effort: str = "medium") -> Iterator[str]:
        raise NotImplementedError


# ==========================================================================
# Google Gemini
# ==========================================================================
def _inline_refs(schema: dict) -> dict:
    """Replace $ref/$defs with the referenced definitions (simplest schema form for the API)."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


class GeminiClient(BaseLLM):
    provider = "gemini"
    THINKING = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH", "xhigh": "HIGH", "max": "HIGH"}

    def __init__(self, api_key: str | None = None, model: str | None = None):
        from google import genai
        from google.genai import types
        self.types = types
        self.model = model or config.GEMINI_MODEL
        key = api_key or config.GEMINI_API_KEY
        if not key:
            raise LLMError("No Gemini API key. Get a free key at https://aistudio.google.com/apikey and put it in "
                           ".env as GEMINI_API_KEY=... (or paste it in the sidebar).")
        self.client = genai.Client(api_key=key)
        self.thinking_ok = True

    # ---- request building
    def _parts(self, content) -> list:
        t = self.types
        if isinstance(content, str):
            return [t.Part.from_text(text=content)]
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append(t.Part.from_text(text=block["text"]))
            elif block["type"] == "image":
                src = block["source"]
                parts.append(t.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
        return parts

    def _config(self, system, effort, schema=None, thinking=True):
        t = self.types
        kwargs = dict(system_instruction=system, media_resolution=t.MediaResolution.MEDIA_RESOLUTION_HIGH)
        if thinking:
            kwargs["thinking_config"] = t.ThinkingConfig(thinking_level=self.THINKING.get(effort, "MEDIUM"))
        if schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_json_schema"] = _inline_refs(schema.model_json_schema())
        return t.GenerateContentConfig(**kwargs)

    def _call(self, fn, **kwargs):
        """Runs a request; retries rate limits / overload a few times and drops options a model rejects."""
        from google.genai import errors
        for attempt in range(4):
            try:
                return fn(thinking=self.thinking_ok, **kwargs)
            except errors.ClientError as e:
                msg = str(e)
                if (e.code == 400 and "API_KEY" in msg.upper()) or e.code in (401, 403):
                    raise LLMError("Gemini API key is invalid or not allowed. Check GEMINI_API_KEY "
                                   "(https://aistudio.google.com/apikey).") from e
                if e.code == 400 and self.thinking_ok and "think" in msg.lower():
                    self.thinking_ok = False  # this model does not accept thinking levels
                    continue
                if e.code == 429 and attempt < 3:
                    time.sleep(20 * (attempt + 1))  # free tier: requests per minute
                    continue
                if e.code == 429:
                    raise LLMError("Gemini free-tier rate limit reached. Wait a minute (or until the daily quota "
                                   "resets) and retry - finished steps are cached.") from e
                if e.code == 404:
                    raise LLMError(f"Gemini model '{self.model}' not found. Set LABELGUARD_GEMINI_MODEL in .env "
                                   "(e.g. gemini-flash-latest).") from e
                raise LLMError(f"Gemini API error {e.code}: {msg[:300]}") from e
            except errors.ServerError as e:
                if attempt < 3:
                    time.sleep(10 * (attempt + 1))
                    continue
                raise LLMError(f"Gemini is unavailable right now ({e.code}). Retry in a minute.") from e
            except (OSError, ConnectionError) as e:
                raise LLMError("Could not reach the Gemini API - check your internet connection.") from e

    # ---- structured output
    def _structured(self, name, system, content, schema, effort):
        parts = self._parts(content)
        last_error = ""
        for attempt in range(2):  # one repair attempt if the JSON does not validate
            extra = [] if not last_error else [self.types.Part.from_text(
                text=f"Your previous answer did not match the required schema: {last_error[:800]}. "
                     "Return valid JSON only.")]

            def go(thinking, _parts=parts + extra):
                return self.client.models.generate_content(
                    model=self.model, contents=[self.types.Content(role="user", parts=_parts)],
                    config=self._config(system, effort, schema, thinking))

            response = self._call(go)
            text = response.text or ""
            try:
                return schema.model_validate_json(text)
            except ValidationError as e:
                last_error = str(e)
        raise LLMError(f"The '{name}' step returned output that did not match the schema.")

    # ---- chat
    def stream_text(self, system, messages, effort="medium"):
        from google.genai import errors
        contents = [self.types.Content(role="model" if m["role"] == "assistant" else "user",
                                       parts=self._parts(m["content"])) for m in messages]
        try:
            # Errors of a streamed call surface while iterating, so they are handled here.
            for chunk in self.client.models.generate_content_stream(
                    model=self.model, contents=contents, config=self._config(system, effort, None, self.thinking_ok)):
                if chunk.text:
                    yield chunk.text
        except errors.APIError as e:
            hint = (" (free-tier rate limit - wait a minute)" if e.code == 429 else
                    " (invalid API key)" if "API_KEY" in str(e).upper() else "")
            yield f"\n\n_(Gemini API error {e.code}{hint})_"
        except (OSError, ConnectionError):
            yield "\n\n_(Could not reach the Gemini API - check your internet connection.)_"


# ==========================================================================
# Anthropic Claude
# ==========================================================================
# Server-side refusal fallback: if the model declines a request on policy
# grounds, the API re-runs it on the default fallback model in the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ClaudeClient(BaseLLM):
    provider = "claude"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        import anthropic
        self.anthropic = anthropic
        self.model = model or config.CLAUDE_MODEL
        # With api_key=None the SDK resolves ANTHROPIC_API_KEY / an `ant auth login` profile.
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def _structured(self, name, system, content, schema, effort):
        anthropic = self.anthropic
        request = dict(model=self.model, max_tokens=64000, system=system,
                       messages=[{"role": "user", "content": content}], output_config={"effort": effort},
                       output_format=schema)
        try:
            message = self._final_message(request)
        except anthropic.AuthenticationError as e:
            raise LLMError("Claude API key is missing or invalid. Set ANTHROPIC_API_KEY in .env or the sidebar.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude API rate limit reached - wait a moment and retry.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Claude API - check your internet connection.") from e

        if message.stop_reason == "refusal":
            raise LLMError(f"The model declined the '{name}' step.")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"The '{name}' step ran out of output tokens; try fewer rules or pages.")
        if message.parsed_output is None:
            raise LLMError(f"The '{name}' step returned output that did not match the schema.")
        return message.parsed_output

    def _final_message(self, request: dict):
        """Streams the request (avoids HTTP timeouts on long answers); retries once without the
        refusal-fallback beta if the account / proxy does not accept it."""
        try:
            with self.client.beta.messages.stream(**request, betas=[FALLBACK_BETA], fallbacks="default") as stream:
                return stream.get_final_message()
        except self.anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            with self.client.beta.messages.stream(**request) as stream:
                return stream.get_final_message()

    def stream_text(self, system, messages, effort="medium"):
        anthropic = self.anthropic
        request = dict(model=self.model, max_tokens=16000, system=system, messages=messages,
                       output_config={"effort": effort})
        try:
            try:
                with self.client.beta.messages.stream(**request, betas=[FALLBACK_BETA],
                                                      fallbacks="default") as stream:
                    yield from stream.text_stream
            except anthropic.BadRequestError as e:
                if "fallback" not in str(e).lower():
                    raise
                with self.client.beta.messages.stream(**request) as stream:
                    yield from stream.text_stream
        except anthropic.APIError as e:
            yield f"\n\n_(Claude API error: {getattr(e, 'message', e)})_"


def make_llm(provider: str | None = None, api_key: str | None = None) -> BaseLLM:
    provider = (provider or config.PROVIDER).lower()
    if provider == "claude":
        return ClaudeClient(api_key=api_key)
    if provider == "gemini":
        return GeminiClient(api_key=api_key)
    raise LLMError(f"Unknown provider '{provider}' (use 'gemini' or 'claude').")
