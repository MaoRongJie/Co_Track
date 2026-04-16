from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Settings

ThreeDProviderRoute = Literal["tripo", "meshy", "hyper3d", "fallback"]


@dataclass(slots=True)
class ThreeDModelGenerationArtifact:
    provider_route: ThreeDProviderRoute
    model_url: str
    uv_template_url: str
    surface_area_m2: float
    paintable_uv_pixels: int
    mapping_meta: dict[str, Any]
    precision_level: str = "approximate"
    license_scope: str = "external_restricted"
    export_glb_allowed: bool = False


def _default_surface_and_uv(product_category: str) -> tuple[float, int, tuple[int, int]]:
    train_categories = {"high_speed_train", "intercity_train", "metro_vehicle"}
    if product_category in train_categories:
        uv_size = (4096, 2048)
        return 298.4, uv_size[0] * uv_size[1], uv_size
    uv_size = (2048, 1024)
    return 52.6, uv_size[0] * uv_size[1], uv_size


class ThreeDModelGenerationProvider:
    """Provider adapter used by Stage-1 model generation workflow.

    This class intentionally keeps generation side effects optional. For local
    development and CI, it deterministically emits placeholder model/uv URLs.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def provider_availability(self) -> dict[str, bool]:
        return {
            "tripo": bool(self._settings.tripo_api_key.strip()),
            "meshy": bool(self._settings.meshy_api_key.strip()),
            "hyper3d": bool(self._settings.hyper3d_api_key.strip()),
        }

    def build_artifact(
        self,
        *,
        task_id: int,
        session_id: int,
        product_category: str,
        generation_plan: dict[str, Any],
    ) -> ThreeDModelGenerationArtifact:
        provider = self._normalize_route(generation_plan.get("provider_route"))
        default_area, default_uv_pixels, uv_size = _default_surface_and_uv(product_category)

        area = self._to_positive_float(generation_plan.get("suggested_surface_area_m2"), default_area)
        uv_pixels = self._to_positive_int(generation_plan.get("suggested_paintable_uv_pixels"), default_uv_pixels)

        prompt = str(generation_plan.get("generation_prompt", "")).strip()
        prompt_digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:10] if prompt else "noprompt"
        task_suffix = str(task_id).zfill(6)
        model_url = f"/files/models/{provider}_generated_{session_id}_{task_suffix}_{prompt_digest}.glb"
        uv_template_url = f"/files/uv/{provider}_generated_{session_id}_{task_suffix}_{uv_size[0]}x{uv_size[1]}.png"

        mapping_meta: dict[str, Any] = {
            "mesh_to_region": {
                "body": "body",
                "front": "front",
                "rear": "rear",
                "roof": "roof",
            },
            "generation": {
                "provider_route": provider,
                "remote_enabled": bool(self._settings.model_generation_enable_remote),
                "availability": self.provider_availability,
                "plan": generation_plan,
            },
            "uv_spec": {
                "width": uv_size[0],
                "height": uv_size[1],
                "paintable_uv_pixels": uv_pixels,
            },
        }

        return ThreeDModelGenerationArtifact(
            provider_route=provider,
            model_url=model_url,
            uv_template_url=uv_template_url,
            surface_area_m2=area,
            paintable_uv_pixels=uv_pixels,
            mapping_meta=mapping_meta,
            precision_level="approximate",
            license_scope="external_restricted",
            export_glb_allowed=False,
        )

    @staticmethod
    def _normalize_route(raw: object) -> ThreeDProviderRoute:
        if raw in {"tripo", "meshy", "hyper3d"}:
            return raw
        return "fallback"

    @staticmethod
    def _to_positive_float(raw: object, default: float) -> float:
        if isinstance(raw, (int, float)) and float(raw) > 0:
            return float(raw)
        if isinstance(raw, str):
            try:
                parsed = float(raw.strip())
            except ValueError:
                return default
            if parsed > 0:
                return parsed
        return default

    @staticmethod
    def _to_positive_int(raw: object, default: int) -> int:
        if isinstance(raw, int) and raw > 0:
            return raw
        if isinstance(raw, float) and raw > 0:
            return int(raw)
        if isinstance(raw, str):
            try:
                parsed = int(raw.strip())
            except ValueError:
                return default
            if parsed > 0:
                return parsed
        return default

    @staticmethod
    def compact_plan_for_log(plan: dict[str, Any]) -> str:
        try:
            return json.dumps(plan, ensure_ascii=False, separators=(",", ":"))[:800]
        except Exception:
            return "{}"


# Backward-compatible aliases for existing imports.
ThreeDGenerationArtifact = ThreeDModelGenerationArtifact
ThreeDGenerationProvider = ThreeDModelGenerationProvider

