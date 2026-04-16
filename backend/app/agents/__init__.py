"""AI agent runtime and provider adapters."""

from app.agents.creative_dialogue_and_image_agent import (
    CreativeDialogueAndImageAgent,
    SessionAiContext,
)
from app.agents.intent_and_3d_generation_agent import Stage1IntentAndThreeDGenerationAgent

# Backward-compatible aliases.
AgentRuntime = CreativeDialogueAndImageAgent
Stage1AgentRuntime = Stage1IntentAndThreeDGenerationAgent

__all__ = [
    "CreativeDialogueAndImageAgent",
    "AgentRuntime",
    "SessionAiContext",
    "Stage1IntentAndThreeDGenerationAgent",
    "Stage1AgentRuntime",
]

