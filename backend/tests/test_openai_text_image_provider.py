import asyncio

import httpx

from app.agents.providers.openai_text_image_provider import OpenAITextImageProvider, _candidate_base_urls
import app.agents.providers.openai_text_image_provider as provider_module


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


def test_candidate_base_urls_adds_aihubmix_alternate() -> None:
    assert _candidate_base_urls("https://aihubmix.com/v1") == [
        "https://aihubmix.com/v1",
        "https://api.aihubmix.com/v1",
    ]


def test_complete_text_falls_back_to_aihubmix_alternate(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.ConnectError("primary unavailable")
            return _FakeResponse({"choices": [{"message": {"content": "fallback-ok"}}]})

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = OpenAITextImageProvider(
        api_key="test-key",
        base_url="https://aihubmix.com/v1",
        text_model="gpt-4.1",
        vision_model="gpt-4.1",
        image_model="gpt-image-1-mini",
        timeout_ms=10000,
    )

    text = asyncio.run(
        provider.complete_text(
            system_prompt="system",
            user_message="user",
            history=[],
        )
    )

    assert text == "fallback-ok"
    assert calls == [
        "https://aihubmix.com/v1/chat/completions",
        "https://api.aihubmix.com/v1/chat/completions",
    ]


def test_generate_image_falls_back_to_aihubmix_alternate(monkeypatch) -> None:  # noqa: ANN001
    calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.ConnectError("primary unavailable")
            return _FakeResponse({"data": [{"url": "https://example.com/pattern.png"}]})

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = OpenAITextImageProvider(
        api_key="test-key",
        base_url="https://aihubmix.com/v1",
        text_model="gpt-4.1",
        vision_model="gpt-4.1",
        image_model="gpt-image-1-mini",
        timeout_ms=10000,
    )

    items = asyncio.run(
        provider.generate_image(
            prompt="simple decal",
            background="transparent",
            output_format="png",
        )
    )

    assert items[0].image_url == "https://example.com/pattern.png"
    assert calls == [
        "https://aihubmix.com/v1/images/generations",
        "https://api.aihubmix.com/v1/images/generations",
    ]
