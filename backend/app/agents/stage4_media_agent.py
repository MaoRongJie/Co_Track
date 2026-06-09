from __future__ import annotations

from dataclasses import dataclass

from app.agents.providers.aihubmix_media_provider import AiHubMixMediaProvider


@dataclass(slots=True)
class Stage4MediaContext:
    session_id: int
    result_id: str | None
    scheme_name: str | None
    image_prompt: str
    video_prompt: str
    screenshot_data_url: str | None = None
    image_url: str | None = None
    duration: int = 5
    resolution: str = "480p"
    generate_audio: bool = True


@dataclass(slots=True)
class Stage4SceneImageResult:
    image_url: str
    image_prediction_id: str
    image_prompt: str


@dataclass(slots=True)
class Stage4SceneVideoResult:
    video_url: str
    video_prediction_id: str
    video_prompt: str


class Stage4MediaAgent:
    async def generate_scene_image(
        self,
        *,
        provider: AiHubMixMediaProvider,
        context: Stage4MediaContext,
    ) -> Stage4SceneImageResult:
        if not context.screenshot_data_url:
            raise RuntimeError("生成场景图需要第四阶段截图。")
        image_prompt = self._compose_image_prompt(context)
        image_result = await provider.generate_scene_image(
            screenshot_data_url=context.screenshot_data_url,
            prompt=image_prompt,
        )
        return Stage4SceneImageResult(
            image_url=image_result.image_url,
            image_prediction_id=image_result.prediction_id,
            image_prompt=image_prompt,
        )

    async def generate_scene_video(
        self,
        *,
        provider: AiHubMixMediaProvider,
        context: Stage4MediaContext,
    ) -> Stage4SceneVideoResult:
        if not context.image_url:
            raise RuntimeError("生成视频需要第四阶段场景图 URL。")
        video_prompt = self._compose_video_prompt(context)
        video_result = await provider.generate_video(
            image_url=context.image_url,
            prompt=video_prompt,
            duration=context.duration,
            resolution=context.resolution,
            ratio="16:9",
            generate_audio=context.generate_audio,
        )
        return Stage4SceneVideoResult(
            video_url=video_result.video_url,
            video_prediction_id=video_result.prediction_id,
            video_prompt=video_prompt,
        )

    @staticmethod
    def _compose_image_prompt(context: Stage4MediaContext) -> str:
        scheme_hint = f"方案名称：{context.scheme_name}。\n" if context.scheme_name else ""
        return (
            "请把提供的 3D 预览截图编辑为同一列高速列车的真实运行场景。"
            "必须保留输入图像中的列车形态、涂装、颜色、标记、相机角度和产品身份。"
            "请用用户指定的环境和光照替换简单预览背景。"
            "不要重新设计列车。\n"
            f"{scheme_hint}"
            f"用户场景提示词：{context.image_prompt.strip()}"
        )

    @staticmethod
    def _compose_video_prompt(context: Stage4MediaContext) -> str:
        return (
            "请从提供的首帧图像开始生成视频，0 秒画面必须与输入首帧保持一致。"
            "随后把该首帧动画化为高速铁路运行镜头，同时保留图像中的列车设计、构图和场景身份。"
            "不要重新设计列车、涂装或开场构图。"
            f"用户视频提示词：{context.video_prompt.strip()}"
        )
