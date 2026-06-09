from __future__ import annotations

import asyncio
import base64
import io
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from app.agents.providers.provider_protocols import ModelProviderError, ModelProviderNotConfiguredError
from app.core.config import Settings

# Maximum dimension for screenshots sent to the image edit API.
# Large images slow down upload and API processing significantly.
_MAX_SCREENSHOT_DIMENSION = 1536
_SCREENSHOT_JPEG_QUALITY = 85


@dataclass(slots=True)
class AiHubMixImageResult:
    prediction_id: str
    image_url: str
    provider_payload: dict[str, Any]


@dataclass(slots=True)
class AiHubMixVideoResult:
    prediction_id: str
    video_url: str
    provider_payload: dict[str, Any]


class AiHubMixMediaProvider:
    image_model = "gpt-image-2"
    video_model = "doubao-seedance-2-0-260128"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.aihubmix_api_key.strip()
        self.base_url = settings.aihubmix_base_url.rstrip("/")
        self.poll_timeout_sec = max(30, int(settings.aihubmix_poll_timeout_sec or 600))
        if not self.api_key:
            raise ModelProviderNotConfiguredError("AIHUBMIX_API_KEY is not configured")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    async def generate_scene_image(
        self,
        *,
        screenshot_data_url: str,
        prompt: str,
        size: str = "auto",
        quality: str = "auto",
    ) -> AiHubMixImageResult:
        image_bytes, mime_type = self._decode_image_data_url(screenshot_data_url)

        # Compress/resize the screenshot to avoid slow uploads and API timeouts
        image_bytes, mime_type = self._compress_screenshot(image_bytes, mime_type)

        # gpt-image-2 uses /images/edits with multipart form data
        edits_url = f"{self.base_url}/images/edits"

        # Build multipart form data
        files = {
            "image": ("screenshot.png", image_bytes, mime_type),
        }
        data: dict[str, str] = {
            "model": self.image_model,
            "prompt": prompt,
            "n": "1",
            "size": size if size and size != "2K" else "auto",
            "quality": quality if quality else "auto",
        }

        # gpt-image-2 can take 2-5 minutes for image editing;
        # use generous timeouts: 30s connect, 600s read (wait for generation)
        timeout = httpx.Timeout(connect=30.0, read=600.0, write=60.0, pool=30.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    edits_url,
                    headers=self._auth_headers(),
                    files=files,
                    data=data,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "AiHubMix gpt-image-2 edit request timed out (the model may need more time for complex edits)",
                status_code=504,
                provider_code="AIHUBMIX_IMAGE_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "AiHubMix gpt-image-2 edit request failed",
                status_code=502,
                provider_code="AIHUBMIX_IMAGE_NETWORK_ERROR",
            ) from exc

        response_payload = self._parse_response(response, provider_code="AIHUBMIX_IMAGE_ERROR")
        image_url = self._try_extract_image_output(response_payload)
        if not image_url:
            raise ModelProviderError(
                f"AiHubMix gpt-image-2 edit API returned no usable image. Response: {self._summarize_payload(response_payload)}",
                status_code=502,
                provider_code="AIHUBMIX_IMAGE_NO_OUTPUT",
            )
        return AiHubMixImageResult(
            prediction_id=(
                self._find_first_string(response_payload, keys=("id", "prediction_id", "task_id"))
                or f"image_{uuid4().hex[:12]}"
            ),
            image_url=image_url,
            provider_payload=response_payload,
        )


    async def generate_video(
        self,
        *,
        image_url: str,
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: bool = True,
    ) -> AiHubMixVideoResult:
        payload = {
            "model": self.video_model,
            "prompt": prompt,
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": image_url},
                    "role": "first_frame",
                }
            ],
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio,
            "watermark": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.poll_timeout_sec) as client:
                response = await client.post(
                    f"{self.base_url}/videos",
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ModelProviderError(
                "AiHubMix video request timed out",
                status_code=504,
                provider_code="AIHUBMIX_VIDEO_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelProviderError(
                "AiHubMix video request failed",
                status_code=502,
                provider_code="AIHUBMIX_VIDEO_NETWORK_ERROR",
            ) from exc

        response_payload = self._parse_response(response, provider_code="AIHUBMIX_VIDEO_ERROR")
        video_url = self._find_media_url(response_payload, suffixes=(".mp4", ".mov", ".webm", ".m3u8"))
        prediction_id = self._find_first_string(
            response_payload,
            keys=("id", "video_id", "task_id", "prediction_id"),
        )
        status_text = (self._find_first_string(response_payload, keys=("status", "state")) or "").lower()
        pending_statuses = {"", "created", "queued", "pending", "processing", "running", "in_progress"}
        if not video_url and prediction_id and status_text in pending_statuses:
            response_payload = await self._poll_video(prediction_id)
            video_url = self._find_media_url(response_payload, suffixes=(".mp4", ".mov", ".webm", ".m3u8"))

        if not video_url:
            raise ModelProviderError(
                f"AiHubMix video API returned no usable video URL. Response: {self._summarize_payload(response_payload)}",
                status_code=502,
                provider_code="AIHUBMIX_VIDEO_NO_URL",
            )

        return AiHubMixVideoResult(
            prediction_id=prediction_id or f"video_{uuid4().hex[:12]}",
            video_url=video_url,
            provider_payload=response_payload,
        )

    async def _poll_video(self, video_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.poll_timeout_sec
        last_payload: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.get(f"{self.base_url}/videos/{video_id}", headers=self._auth_headers())
            except httpx.TimeoutException:
                await asyncio.sleep(2)
                continue
            except httpx.HTTPError as exc:
                raise ModelProviderError(
                    "AiHubMix video polling failed",
                    status_code=502,
                    provider_code="AIHUBMIX_VIDEO_POLL_ERROR",
                ) from exc

            payload = self._parse_response(response, provider_code="AIHUBMIX_VIDEO_POLL_ERROR")
            last_payload = payload
            if self._find_media_url(payload, suffixes=(".mp4", ".mov", ".webm", ".m3u8")):
                return payload
            status_text = (self._find_first_string(payload, keys=("status", "state")) or "").lower()
            if status_text in {"failed", "error", "cancelled"}:
                raise ModelProviderError(
                    self._extract_error_message(payload, default="AiHubMix video generation failed"),
                    status_code=502,
                    provider_code="AIHUBMIX_VIDEO_FAILED",
                )
            await asyncio.sleep(2)

        if last_payload is not None:
            return last_payload
        raise ModelProviderError(
            "AiHubMix video generation timed out",
            status_code=504,
            provider_code="AIHUBMIX_VIDEO_GENERATION_TIMEOUT",
        )


    @staticmethod
    def _decode_image_data_url(data_url: str) -> tuple[bytes, str]:
        header, separator, payload = data_url.partition(",")
        if separator != "," or ";base64" not in header:
            raise ModelProviderError(
                "Stage 4 screenshot must be a base64 image data URL",
                status_code=400,
                provider_code="AIHUBMIX_IMAGE_BAD_INPUT",
            )
        mime_type = header.removeprefix("data:").split(";", 1)[0] or "image/png"
        try:
            return base64.b64decode(payload), mime_type
        except ValueError as exc:
            raise ModelProviderError(
                "Stage 4 screenshot data URL is not valid base64",
                status_code=400,
                provider_code="AIHUBMIX_IMAGE_BAD_INPUT",
            ) from exc

    @staticmethod
    def _compress_screenshot(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
        """Resize and compress screenshot to reduce upload size and API processing time.

        gpt-image-2 processes large images slowly. Downscaling to max 1536px and
        converting to PNG keeps quality high while significantly cutting latency.
        """
        try:
            from PIL import Image
        except ImportError:
            # If Pillow is not available, return the image as-is
            return image_bytes, mime_type

        try:
            img = Image.open(io.BytesIO(image_bytes))
        except Exception:
            return image_bytes, mime_type

        # Convert RGBA to RGB if needed (PNG with transparency)
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if either dimension exceeds the limit
        max_dim = _MAX_SCREENSHOT_DIMENSION
        width, height = img.size
        if width > max_dim or height > max_dim:
            scale = max_dim / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        # Save as PNG for best compatibility with gpt-image-2
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"

    @staticmethod
    def _parse_response(response: httpx.Response, *, provider_code: str) -> dict[str, Any]:
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            raise ModelProviderError(
                AiHubMixMediaProvider._extract_error_message(
                    payload,
                    default=f"AiHubMix API error ({response.status_code})",
                ),
                status_code=502,
                provider_code=provider_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ModelProviderError(
                "AiHubMix API returned invalid JSON",
                status_code=502,
                provider_code=provider_code,
            ) from exc
        if not isinstance(payload, dict):
            raise ModelProviderError(
                "AiHubMix API returned an unexpected payload",
                status_code=502,
                provider_code=provider_code,
            )
        return payload

    @staticmethod
    def _extract_image_output(payload: dict[str, Any]) -> str:
        image_url = AiHubMixMediaProvider._try_extract_image_output(payload)
        if image_url:
            return image_url
        raise ModelProviderError(
            "AiHubMix image generation returned no usable image",
            status_code=502,
            provider_code="AIHUBMIX_IMAGE_NO_OUTPUT",
        )

    @staticmethod
    def _try_extract_image_output(payload: dict[str, Any]) -> str | None:
        data = payload.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()
                b64_json = item.get("b64_json")
                if isinstance(b64_json, str) and b64_json.strip():
                    return f"data:image/png;base64,{b64_json.strip()}"

        media_url = AiHubMixMediaProvider._find_media_url(payload, suffixes=(".png", ".jpg", ".jpeg", ".webp"))
        if media_url:
            return media_url
        return None

    @staticmethod
    def _find_media_url(value: Any, *, suffixes: tuple[str, ...]) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("http://", "https://", "data:")):
                lower = stripped.lower().split("?", 1)[0]
                if stripped.startswith("data:") or any(lower.endswith(suffix) for suffix in suffixes):
                    return stripped
            return None
        if isinstance(value, list):
            for item in value:
                found = AiHubMixMediaProvider._find_media_url(item, suffixes=suffixes)
                if found:
                    return found
        if isinstance(value, dict):
            direct_media_keys = {
                "url",
                "image",
                "image_url",
                "video",
                "video_url",
                "download_url",
                "output_url",
                "output",
                "outputs",
                "file",
            }
            for key in direct_media_keys:
                child_value = value.get(key)
                if isinstance(child_value, str):
                    stripped = child_value.strip()
                    if stripped.startswith(("http://", "https://", "data:")):
                        return stripped
                if isinstance(child_value, list):
                    for child in child_value:
                        if isinstance(child, str) and child.strip().startswith(("http://", "https://", "data:")):
                            return child.strip()
                found = AiHubMixMediaProvider._find_media_url(child_value, suffixes=suffixes)
                if found:
                    return found
            for key in ("url", "content"):
                found = AiHubMixMediaProvider._find_media_url(value.get(key), suffixes=suffixes)
                if found:
                    return found
            for item in value.values():
                found = AiHubMixMediaProvider._find_media_url(item, suffixes=suffixes)
                if found:
                    return found
        return None

    @staticmethod
    def _find_first_string(value: Any, *, keys: tuple[str, ...]) -> str | None:
        if isinstance(value, dict):
            for key in keys:
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, int):
                    return str(item)
            for item in value.values():
                found = AiHubMixMediaProvider._find_first_string(item, keys=keys)
                if found:
                    return found
        if isinstance(value, list):
            for item in value:
                found = AiHubMixMediaProvider._find_first_string(item, keys=keys)
                if found:
                    return found
        return None

    @staticmethod
    def _summarize_payload(value: Any, *, max_length: int = 900) -> str:
        def scrub(item: Any) -> Any:
            if isinstance(item, str):
                if item.startswith("data:"):
                    return item[:48] + "...<data-url omitted>"
                if len(item) > 220:
                    return item[:220] + "..."
                return item
            if isinstance(item, list):
                return [scrub(child) for child in item[:6]]
            if isinstance(item, dict):
                return {str(key): scrub(child) for key, child in list(item.items())[:16]}
            return item

        try:
            import json

            text = json.dumps(scrub(value), ensure_ascii=False)
        except Exception:
            text = str(value)
        return text if len(text) <= max_length else text[:max_length] + "..."

    @staticmethod
    def _extract_error_message(payload: Any, *, default: str) -> str:
        if isinstance(payload, dict):
            for key in ("error", "message", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    message = value.get("message")
                    if isinstance(message, str) and message.strip():
                        return message.strip()
            data = payload.get("data")
            if isinstance(data, dict):
                return AiHubMixMediaProvider._extract_error_message(data, default=default)
        return default
