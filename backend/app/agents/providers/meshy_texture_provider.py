"""Meshy Retexture API provider with mock fallback.

When MESHY_API_KEY is empty the provider returns mock results that reuse the
original base model URL so the full UI flow can be tested without credits.

When a real key is supplied the provider reads the local GLB file, encodes it
as a ``data:application/octet-stream;base64,...`` Data URI, and posts it to
the Meshy Retexture endpoint together with the scheme prompt text.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.model_processing import NORMALIZED_MODEL_DIR, TEXTURE_MAP_DIR, to_texture_url

logger = logging.getLogger(__name__)

RETEXTURE_ENDPOINT = "/openapi/v1/retexture"
TASK_ENDPOINT = "/openapi/v1/retexture/{task_id}"
POLL_INTERVAL_SEC = 4
MAX_POLL_ATTEMPTS = 90  # ~6 minutes
DOWNLOAD_TIMEOUT_SEC = 300.0
DOWNLOAD_MAX_ATTEMPTS = 3
SUBMIT_RETRYABLE_STATUS_CODES = {499, 502, 503, 504}
SUBMIT_MAX_ATTEMPTS = 2


@dataclass(slots=True)
class TexturedModelResult:
    scheme_id: str
    status: str  # pending | processing | completed | failed
    textured_model_url: str | None = None
    meshy_task_id: str | None = None
    error_message: str | None = None
    texture_maps: dict[str, str | None] | None = None


def _build_data_uri(glb_path: str) -> str:
    """Read a local GLB file and return a base64 Data URI."""
    raw = Path(glb_path).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:application/octet-stream;base64,{encoded}"


def _relative_model_url_to_local_path(model_url: str) -> Path | None:
    normalized = model_url.strip()
    if not normalized.startswith("/files/models/"):
        return None
    file_name = Path(normalized).name
    candidate = (NORMALIZED_MODEL_DIR / file_name).resolve()
    try:
        candidate.relative_to(NORMALIZED_MODEL_DIR.resolve())
    except ValueError:
        return None
    return candidate


def _build_local_meshy_model_url(*, scheme_id: str, task_id: str) -> tuple[Path, str]:
    file_name = f"retexture_{scheme_id}_{task_id}.glb"
    return NORMALIZED_MODEL_DIR / file_name, f"/files/models/{file_name}"


def _infer_remote_suffix(remote_url: str, *, fallback: str) -> str:
    suffix = Path(urlparse(remote_url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".glb"}:
        return suffix
    return fallback


def _build_local_texture_map_url(*, scheme_id: str, task_id: str, texture_key: str, remote_url: str) -> tuple[Path, str]:
    safe_key = texture_key.strip().lower().replace(" ", "_")
    suffix = _infer_remote_suffix(remote_url, fallback=".png")
    file_name = f"retexture_{scheme_id}_{task_id}_{safe_key}{suffix}"
    local_path = TEXTURE_MAP_DIR / file_name
    return local_path, to_texture_url(local_path)


def _build_sanitized_meshy_input_path(source_path: Path) -> Path:
    suffix = source_path.suffix.lower() or ".glb"
    return NORMALIZED_MODEL_DIR / f"{source_path.stem}__meshy_input{suffix}"


def _gltf_has_texture_bindings(gltf: Any) -> bool:
    for material in gltf.materials or []:
        pbr = getattr(material, "pbrMetallicRoughness", None)
        if pbr is not None and (
            getattr(pbr, "baseColorTexture", None) is not None
            or getattr(pbr, "metallicRoughnessTexture", None) is not None
        ):
            return True
        if (
            getattr(material, "normalTexture", None) is not None
            or getattr(material, "occlusionTexture", None) is not None
            or getattr(material, "emissiveTexture", None) is not None
        ):
            return True
    return False


def _sanitize_local_model_for_meshy(source_path: Path) -> Path:
    """Best-effort sanitize a local GLB into a UV-preserving, texture-free Meshy input.

    The locked normalized model is the right geometry/UV source for Meshy, but some
    exported GLBs can still carry embedded images or material texture bindings that
    make Meshy reject the upload. For submission we strip those payloads while keeping
    the original geometry and UV coordinates intact.
    """

    try:
        from pygltflib import GLTF2, ImageFormat, PbrMetallicRoughness
    except ImportError:
        logger.warning("pygltflib is unavailable; sending Meshy the original local GLB: %s", source_path)
        return source_path

    try:
        gltf = GLTF2().load_binary(str(source_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to inspect local GLB for Meshy sanitization (%s): %r", source_path, exc)
        return source_path

    needs_sanitization = bool(gltf.images or gltf.textures or gltf.samplers or _gltf_has_texture_bindings(gltf))
    if not needs_sanitization:
        return source_path

    sanitized_path = _build_sanitized_meshy_input_path(source_path)
    try:
        if sanitized_path.is_file() and sanitized_path.stat().st_mtime >= source_path.stat().st_mtime:
            return sanitized_path
    except OSError:
        pass

    try:
        # Remove image bufferViews from the GLB binary so the submission payload only
        # carries geometry + UV data, not stale or synthesized texture content.
        if gltf.images:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                gltf.convert_images(ImageFormat.DATAURI)

        gltf.images = []
        gltf.textures = []
        gltf.samplers = []

        for material in gltf.materials or []:
            if getattr(material, "pbrMetallicRoughness", None) is None:
                material.pbrMetallicRoughness = PbrMetallicRoughness()
            material.pbrMetallicRoughness.baseColorTexture = None
            material.pbrMetallicRoughness.metallicRoughnessTexture = None
            material.pbrMetallicRoughness.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
            material.pbrMetallicRoughness.metallicFactor = 0.0
            material.pbrMetallicRoughness.roughnessFactor = 1.0
            material.normalTexture = None
            material.occlusionTexture = None
            material.emissiveTexture = None
            material.emissiveFactor = [0.0, 0.0, 0.0]

        sanitized_path.parent.mkdir(parents=True, exist_ok=True)
        gltf.save_binary(str(sanitized_path))
        return sanitized_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to build sanitized Meshy input for %s: %r", source_path, exc)
        return source_path


class MeshyTextureProvider:
    """Wraps the Meshy Retexture API.

    Falls back to mock results when no API key is configured.
    """

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.meshy_api_key.strip()
        self._base_url = settings.meshy_base_url.strip().rstrip("/")
        self._timeout_sec = settings.model_generation_timeout_sec

    @property
    def is_mock(self) -> bool:
        return not self._api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retexture_model(
        self,
        *,
        model_glb_path: str,
        prompt_text: str,
        scheme_id: str,
    ) -> TexturedModelResult:
        """Apply a texture to a model for a single scheme.

        In mock mode the original model URL is returned directly.
        """
        if self.is_mock:
            return self._mock_result(model_glb_path, scheme_id)

        try:
            task_id = await self._submit_retexture(model_glb_path, prompt_text)
            return await self._poll_until_done(task_id, scheme_id)
        except Exception as exc:
            logger.exception("Meshy retexture failed for %s", scheme_id)
            return TexturedModelResult(
                scheme_id=scheme_id,
                status="failed",
                error_message=str(exc),
            )

    async def retexture_all_schemes(
        self,
        *,
        model_glb_path: str,
        schemes: list[dict[str, Any]],
    ) -> list[TexturedModelResult]:
        """Run retexture for every scheme in a stable sequence.

        Meshy submit requests can time out when several large inline GLB payloads
        are posted in parallel from local development. Sequential submission keeps
        the request pressure lower and avoids avoidable 504 gateway errors.
        """
        results: list[TexturedModelResult] = []
        for i, scheme in enumerate(schemes):
            result = await self.retexture_model(
                model_glb_path=model_glb_path,
                prompt_text=str(scheme.get("prompt_text", "")),
                scheme_id=str(scheme.get("id", f"scheme_{i + 1}")),
            )
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_result(model_glb_path: str, scheme_id: str) -> TexturedModelResult:
        return TexturedModelResult(
            scheme_id=scheme_id,
            status="completed",
            textured_model_url=model_glb_path,
            meshy_task_id=f"mock_{scheme_id}",
            texture_maps=None,
        )

    # ------------------------------------------------------------------
    # Real Meshy calls
    # ------------------------------------------------------------------

    async def _submit_retexture(self, model_glb_path: str, prompt_text: str) -> str:
        model_url = self._resolve_model_input(model_glb_path)
        payload = {
            "model_url": model_url,
            "text_style_prompt": prompt_text,
            "enable_original_uv": True,
            "enable_pbr": True,
            "ai_model": "latest",
            "target_formats": ["glb"],
        }
        submit_url = f"{self._base_url}{RETEXTURE_ENDPOINT}"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        last_error: Exception | None = None
        for attempt in range(1, SUBMIT_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(
                        submit_url,
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()
                    body = response.json()
                    task_id = body.get("result") or body.get("task_id") or body.get("id")
                    if not task_id:
                        raise ValueError(f"Meshy did not return a task id: {body}")
                    return str(task_id)
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code not in SUBMIT_RETRYABLE_STATUS_CODES or attempt >= SUBMIT_MAX_ATTEMPTS:
                    raise RuntimeError(self._format_submit_http_error(exc, model_url=model_url)) from exc
                await asyncio.sleep(2 * attempt)
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= SUBMIT_MAX_ATTEMPTS:
                    raise RuntimeError(self._format_submit_timeout_error(model_url=model_url)) from exc
                await asyncio.sleep(2 * attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("Meshy submit failed before a task id was returned.")

    def _resolve_model_input(self, model_glb_path: str) -> str:
        candidate = model_glb_path.strip()
        if not candidate:
            raise ValueError("Meshy model input is empty.")

        if candidate.startswith("data:"):
            return candidate

        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            return candidate

        local_path: Path | None = None
        if Path(candidate).is_file():
            local_path = Path(candidate)
        else:
            local_path = _relative_model_url_to_local_path(candidate)

        if local_path and local_path.is_file():
            sanitized_path = _sanitize_local_model_for_meshy(local_path)
            return _build_data_uri(str(sanitized_path))

        raise FileNotFoundError(
            "Meshy could not resolve the base model file. "
            f"Expected a public URL, data URI, or a local model file, got: {model_glb_path}"
        )

    async def _poll_until_done(self, task_id: str, scheme_id: str) -> TexturedModelResult:
        url = f"{self._base_url}{TASK_ENDPOINT.format(task_id=task_id)}"
        async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
            for _ in range(MAX_POLL_ATTEMPTS):
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                body = response.json()
                status = str(body.get("status", "")).lower()

                if status in ("succeeded", "completed"):
                    model_url = (
                        body.get("model_urls", {}).get("glb")
                        or body.get("model_url")
                        or body.get("output", {}).get("model_url")
                    )

                    if not model_url:
                        return TexturedModelResult(
                            scheme_id=scheme_id,
                            status="failed",
                            meshy_task_id=task_id,
                            error_message="Meshy finished without returning a GLB download URL.",
                        )

                    if model_url and str(model_url).startswith("http"):
                        try:
                            model_url = await self._download_remote_result_model(
                                remote_url=str(model_url),
                                scheme_id=scheme_id,
                                task_id=task_id,
                            )
                        except Exception as exc:
                            logger.error("Failed to cache Meshy model %s from %s: %r", task_id, model_url, exc)
                            return TexturedModelResult(
                                scheme_id=scheme_id,
                                status="failed",
                                meshy_task_id=task_id,
                                error_message="Meshy generated a model, but the backend could not cache the GLB for preview/download.",
                            )

                    texture_maps = await self._extract_and_cache_texture_maps(
                        body=body,
                        scheme_id=scheme_id,
                        task_id=task_id,
                    )

                    return TexturedModelResult(
                        scheme_id=scheme_id,
                        status="completed",
                        textured_model_url=model_url,
                        meshy_task_id=task_id,
                        texture_maps=texture_maps,
                    )

                if status in ("failed", "error", "expired"):
                    error_msg = (
                        body.get("task_error", {}).get("message")
                        or body.get("error", {}).get("message")
                        or body.get("message")
                        or "Unknown error"
                    )
                    return TexturedModelResult(
                        scheme_id=scheme_id,
                        status="failed",
                        meshy_task_id=task_id,
                        error_message=str(error_msg),
                    )

                await asyncio.sleep(POLL_INTERVAL_SEC)

        return TexturedModelResult(
            scheme_id=scheme_id,
            status="failed",
            meshy_task_id=task_id,
            error_message="Meshy retexture timed out.",
        )

    async def _download_remote_result_model(self, *, remote_url: str, scheme_id: str, task_id: str) -> str:
        local_path, public_url = _build_local_meshy_model_url(scheme_id=scheme_id, task_id=task_id)
        await self._download_binary_to_path(remote_url=remote_url, output_path=local_path)
        if not local_path.is_file() or local_path.stat().st_size <= 0:
            raise IOError(f"Downloaded Meshy model is empty: {local_path}")
        return public_url

    async def _download_binary_to_path(self, *, remote_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(f"{output_path.suffix}.part")
        last_error: Exception | None = None
        for attempt in range(1, DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(DOWNLOAD_TIMEOUT_SEC, connect=45.0),
                    follow_redirects=True,
                ) as client:
                    async with client.stream("GET", remote_url) as response:
                        response.raise_for_status()
                        with temp_path.open("wb") as output:
                            async for chunk in response.aiter_bytes():
                                if chunk:
                                    output.write(chunk)
                os.replace(temp_path, output_path)
                return
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
                last_error = exc
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                if attempt >= DOWNLOAD_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(attempt)
            except Exception:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                raise

        if last_error is not None:
            raise last_error

    async def _extract_and_cache_texture_maps(
        self,
        *,
        body: dict[str, Any],
        scheme_id: str,
        task_id: str,
    ) -> dict[str, str | None] | None:
        raw_texture_sets = body.get("texture_urls")
        if isinstance(raw_texture_sets, list):
            primary_set = next((item for item in raw_texture_sets if isinstance(item, dict)), None)
        elif isinstance(raw_texture_sets, dict):
            primary_set = raw_texture_sets
        else:
            primary_set = None

        if not isinstance(primary_set, dict):
            return None

        texture_maps: dict[str, str | None] = {}
        for source_key, target_key in (
            ("base_color", "base_color"),
            ("metallic", "metallic"),
            ("normal", "normal"),
            ("roughness", "roughness"),
        ):
            remote_url = primary_set.get(source_key)
            if not isinstance(remote_url, str) or not remote_url.strip():
                texture_maps[target_key] = None
                continue
            if remote_url.startswith("http"):
                try:
                    local_path, public_url = _build_local_texture_map_url(
                        scheme_id=scheme_id,
                        task_id=task_id,
                        texture_key=target_key,
                        remote_url=remote_url,
                    )
                    await self._download_binary_to_path(
                        remote_url=remote_url,
                        output_path=local_path,
                    )
                    if not local_path.is_file() or local_path.stat().st_size <= 0:
                        raise IOError(f"Downloaded Meshy texture is empty: {local_path}")
                    texture_maps[target_key] = public_url
                except Exception as exc:
                    logger.error(
                        "Failed to cache Meshy texture %s for %s from %s: %r",
                        target_key,
                        task_id,
                        remote_url,
                        exc,
                    )
                    texture_maps[target_key] = None
                continue
            texture_maps[target_key] = remote_url

        if not any(value for value in texture_maps.values()):
            return None
        return texture_maps

    def _format_submit_http_error(self, exc: httpx.HTTPStatusError, *, model_url: str) -> str:
        status_code = exc.response.status_code
        response_excerpt = exc.response.text.strip()[:240]
        if status_code == 504:
            if model_url.startswith("data:"):
                return (
                    "Meshy submit timed out at the gateway while uploading the inline GLB payload. "
                    "This usually happens in local development when the base model is sent as a large data URI. "
                    "Try a smaller model or expose the GLB with a public URL instead of an inline upload."
                )
            return (
                "Meshy submit timed out at the gateway while creating the retexture task. "
                "Please retry in a moment."
            )
        if response_excerpt:
            return f"Meshy submit failed with HTTP {status_code}: {response_excerpt}"
        return f"Meshy submit failed with HTTP {status_code}."

    def _format_submit_timeout_error(self, *, model_url: str) -> str:
        if model_url.startswith("data:"):
            return (
                "Meshy submit timed out while uploading the inline GLB payload. "
                "The current local-development flow sends the model as base64 data, which can be slow for larger files."
            )
        return "Meshy submit timed out before the retexture task was accepted."
