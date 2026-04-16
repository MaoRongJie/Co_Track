from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from app.agents.providers.provider_protocols import (
    ImageGenerationResult,
    ModelProviderError,
    ModelProviderNotConfiguredError,
)


def _extract_openai_error(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return None


def _append_text_fragments_from_content(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        if value:
            output.append(value)
        return

    if isinstance(value, dict):
        text_field = value.get("text")
        if isinstance(text_field, str) and text_field:
            output.append(text_field)
        elif isinstance(text_field, dict):
            nested = text_field.get("value")
            if isinstance(nested, str) and nested:
                output.append(nested)

        nested_value = value.get("value")
        if isinstance(nested_value, str) and nested_value:
            output.append(nested_value)
        return

    if isinstance(value, list):
        for part in value:
            _append_text_fragments_from_content(part, output)


def _extract_text_fragments(payload: Any) -> list[str]:
    fragments: list[str] = []
    if not isinstance(payload, dict):
        return fragments

    # OpenAI Responses-style streaming events.
    event_type = payload.get("type")
    if isinstance(event_type, str):
        if event_type in {"response.output_text.delta", "output_text.delta"}:
            delta = payload.get("delta")
            if isinstance(delta, str) and delta:
                fragments.append(delta)
        elif event_type in {"response.output_text.done", "output_text.done"}:
            text = payload.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            delta = choice.get("delta")
            if isinstance(delta, dict):
                _append_text_fragments_from_content(delta.get("content"), fragments)
                text_field = delta.get("text")
                if isinstance(text_field, str) and text_field:
                    fragments.append(text_field)

            text_field = choice.get("text")
            if isinstance(text_field, str) and text_field:
                fragments.append(text_field)

            message = choice.get("message")
            if isinstance(message, dict):
                _append_text_fragments_from_content(message.get("content"), fragments)

    message = payload.get("message")
    if isinstance(message, dict):
        _append_text_fragments_from_content(message.get("content"), fragments)

    # OpenAI Responses non-stream shape.
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            _append_text_fragments_from_content(item.get("content"), fragments)

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        fragments.append(output_text)

    # Remove empty chunks while preserving order.
    return [chunk for chunk in fragments if isinstance(chunk, str) and chunk]


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for idx in range(start, len(text)):
        char = text[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                fragment = text[start : idx + 1]
                try:
                    parsed = json.loads(fragment)
                except Exception:
                    return None
                if isinstance(parsed, dict):
                    return parsed
                return None
    return None


class OpenAITextImageProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        text_model: str,
        vision_model: str,
        image_model: str,
        timeout_ms: int,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.text_model = text_model
        self.vision_model = vision_model.strip() or text_model
        self.image_model = image_model
        self.timeout = max(5000, timeout_ms) / 1000
        # Image generation often takes longer than text completion.
        self.image_timeout = max(self.timeout, 120.0)
        self.model_name = text_model

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ModelProviderNotConfiguredError("OPENAI_API_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_chat_completion(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "OpenAI text API timed out",
                status_code=504,
                provider_code="OPENAI_TEXT_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "OpenAI text API request failed",
                status_code=502,
                provider_code="OPENAI_TEXT_NETWORK_ERROR",
            ) from exc

        if response.status_code >= 400:
            raw = response.text
            error_message = f"OpenAI text API error ({response.status_code})"
            try:
                decoded = json.loads(raw)
                parsed = _extract_openai_error(decoded)
                if parsed:
                    error_message = parsed
            except Exception:
                pass
            raise ModelProviderError(error_message, status_code=502, provider_code="OPENAI_TEXT_ERROR")

        try:
            parsed = response.json()
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "OpenAI text API returned invalid JSON",
                status_code=502,
                provider_code="OPENAI_TEXT_BAD_JSON",
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelProviderError(
                "OpenAI text API returned unexpected payload",
                status_code=502,
                provider_code="OPENAI_TEXT_BAD_PAYLOAD",
            )
        return parsed

    async def _complete_text_once(self, *, payload: dict[str, Any]) -> str:
        request_payload = dict(payload)
        request_payload["stream"] = False
        parsed = await self._post_chat_completion(payload=request_payload)
        return "".join(_extract_text_fragments(parsed)).strip()

    async def complete_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.2,
    ) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages.extend((history or [])[-10:])
        messages.append({"role": "user", "content": user_message})
        payload = {
            "model": self.text_model,
            "messages": messages,
            "temperature": max(0.0, min(temperature, 1.5)),
        }
        return await self._complete_text_once(payload=payload)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any] | None:
        text = await self.complete_text(
            system_prompt=system_prompt,
            user_message=user_message,
            history=history,
            temperature=temperature,
        )
        return _extract_json_object(text)

    async def complete_json_with_messages(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "model": (model or self.text_model).strip(),
            "messages": messages,
            "temperature": max(0.0, min(temperature, 1.5)),
            "stream": False,
        }
        parsed = await self._post_chat_completion(payload=payload)
        text = "".join(_extract_text_fragments(parsed)).strip()
        return _extract_json_object(text)

    async def analyze_image_keywords(
        self,
        *,
        image_url: str,
        brief_keywords: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        context_text = json.dumps(brief_keywords or {}, ensure_ascii=False)
        system_prompt = (
            "You are Co-Track image style analyzer. "
            "Read the reference image and extract style keywords useful for industrial coating texture planning. "
            "Return strict JSON only."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Analyze the uploaded image style for texture planning.\n"
                            "Extract both visible content cues and style cues useful for texture planning.\n"
                            "Use the brief context only as optional grounding.\n"
                            f"Brief context: {context_text}\n"
                            'Return JSON with schema: {"content_keywords":["string"],"style_keywords":["string"],"content_summary":"string","style_summary":"string"}. '
                            "Keep keywords concise and practical."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        return await self.complete_json_with_messages(
            messages=messages,
            temperature=0.2,
            model=self.vision_model,
        )

    async def analyze_image_style(
        self,
        *,
        image_url: str,
        brief_keywords: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return await self.analyze_image_keywords(image_url=image_url, brief_keywords=brief_keywords)

    async def stream_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        history: list[dict[str, str]],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(history[-10:])
        messages.append({"role": "user", "content": user_message})

        payload = {
            "model": self.text_model,
            "messages": messages,
            "temperature": max(0.0, min(temperature, 1.5)),
            "stream": True,
        }
        emitted_any = False

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        error_message = f"OpenAI text API error ({response.status_code})"
                        try:
                            decoded = json.loads(raw.decode("utf-8"))
                            parsed = _extract_openai_error(decoded)
                            if parsed:
                                error_message = parsed
                        except Exception:
                            pass
                        raise ModelProviderError(error_message, status_code=502, provider_code="OPENAI_TEXT_ERROR")

                    async for line in response.aiter_lines():
                        text = line.strip()
                        if not text or not text.startswith("data:"):
                            continue
                        data = text[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        for chunk in _extract_text_fragments(parsed):
                            emitted_any = True
                            yield chunk
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "OpenAI text API timed out",
                status_code=504,
                provider_code="OPENAI_TEXT_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "OpenAI text API request failed",
                status_code=502,
                provider_code="OPENAI_TEXT_NETWORK_ERROR",
            ) from exc

        if not emitted_any:
            fallback_text = await self._complete_text_once(payload=payload)
            if fallback_text:
                yield fallback_text

    async def generate_image(
        self,
        *,
        prompt: str,
        style_hint: str | None = None,
        reference_images: list[str] | None = None,
    ) -> list[ImageGenerationResult]:
        full_prompt = prompt.strip()
        if style_hint:
            full_prompt = f"{full_prompt}\n\nStyle hint: {style_hint.strip()}"
        if reference_images:
            refs = [item for item in reference_images if isinstance(item, str) and item.strip()]
            if refs:
                full_prompt = f"{full_prompt}\n\nReference images:\n" + "\n".join(f"- {item}" for item in refs[:4])

        payload: dict[str, Any] = {
            "model": self.image_model,
            "prompt": full_prompt,
            "size": "1024x1024",
            "quality": "high",
        }

        try:
            async with httpx.AsyncClient(timeout=self.image_timeout) as client:
                response = await client.post(
                    f"{self.base_url}/images/generations",
                    headers=self._headers(),
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "OpenAI image API timed out",
                status_code=504,
                provider_code="OPENAI_IMAGE_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "OpenAI image API request failed",
                status_code=502,
                provider_code="OPENAI_IMAGE_NETWORK_ERROR",
            ) from exc

        if response.status_code >= 400:
            error_message = f"OpenAI image API error ({response.status_code})"
            try:
                payload = response.json()
                parsed = _extract_openai_error(payload)
                if parsed:
                    error_message = parsed
            except Exception:
                pass
            raise ModelProviderError(error_message, status_code=502, provider_code="OPENAI_IMAGE_ERROR")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ModelProviderError(
                "OpenAI image API returned invalid JSON",
                status_code=502,
                provider_code="OPENAI_IMAGE_BAD_JSON",
            ) from exc

        raw_items = data.get("data")
        if not isinstance(raw_items, list) or not raw_items:
            raise ModelProviderError(
                "OpenAI image API returned empty data",
                status_code=502,
                provider_code="OPENAI_IMAGE_EMPTY",
            )

        results: list[ImageGenerationResult] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            image_url: str | None = None
            if isinstance(item.get("url"), str) and item["url"].strip():
                image_url = item["url"].strip()
            elif isinstance(item.get("b64_json"), str) and item["b64_json"].strip():
                image_url = f"data:image/png;base64,{item['b64_json']}"

            if not image_url:
                continue

            revised_prompt = item.get("revised_prompt")
            results.append(
                ImageGenerationResult(
                    image_url=image_url,
                    revised_prompt=revised_prompt if isinstance(revised_prompt, str) else None,
                    provider_payload=item,
                )
            )

        if not results:
            raise ModelProviderError(
                "OpenAI image API returned no usable image",
                status_code=502,
                provider_code="OPENAI_IMAGE_NO_URL",
            )
        return results


# Backward-compatible alias for existing imports.
OpenAIProvider = OpenAITextImageProvider

