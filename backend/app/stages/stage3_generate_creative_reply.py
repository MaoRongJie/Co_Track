from __future__ import annotations

from app.agents.creative_dialogue_and_image_agent import CreativeDialogueAndImageAgent, SessionAiContext
from app.graph.engine import get_creative_dialogue_and_image_agent


def get_stage3_agent() -> CreativeDialogueAndImageAgent:
    return get_creative_dialogue_and_image_agent()


async def run_stage3_generate_creative_reply(
    *,
    stage3_agent: CreativeDialogueAndImageAgent,
    mode: str,
    message: str,
    context: SessionAiContext,
):
    return await stage3_agent.plan_chat(mode=mode, message=message, context=context)

