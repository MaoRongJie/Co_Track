import asyncio

import app.agents.providers.aihubmix_media_provider as provider_module
from app.agents.providers.aihubmix_media_provider import AiHubMixMediaProvider


def test_gpt_image_2_scene_image_uses_edits_endpoint(monkeypatch) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    class SettingsStub:
        aihubmix_api_key = "test-aihubmix-key"
        aihubmix_base_url = "https://aihubmix.com/v1"
        aihubmix_poll_timeout_sec = 30

    class FakeResponse:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "data": [{"b64_json": "AAAA"}],
            }

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> FakeResponse:
            captured["url"] = url
            captured["headers"] = kwargs.get("headers")
            captured["files"] = kwargs.get("files")
            captured["data"] = kwargs.get("data")
            return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)

    result = asyncio.run(
        AiHubMixMediaProvider(SettingsStub()).generate_scene_image(
            screenshot_data_url="data:image/png;base64,AAAA",
            prompt="保留列车涂装并生成真实站台场景",
        )
    )

    # Verify it uses /images/edits endpoint (not /images/generations)
    assert captured["url"] == "https://aihubmix.com/v1/images/edits"

    # Verify multipart form data fields
    form_data = captured["data"]
    assert isinstance(form_data, dict)
    assert form_data["model"] == "gpt-image-2"
    assert form_data["prompt"] == "保留列车涂装并生成真实站台场景"
    assert form_data["n"] == "1"
    assert form_data["quality"] == "auto"

    # Verify image file is sent as multipart
    files = captured["files"]
    assert isinstance(files, dict)
    assert "image" in files
    file_tuple = files["image"]
    assert file_tuple[0] == "screenshot.png"  # filename
    assert file_tuple[2] == "image/png"  # mime type

    # Verify result extracted b64_json as data URL
    assert result.image_url == "data:image/png;base64,AAAA"
