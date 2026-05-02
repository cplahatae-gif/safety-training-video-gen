"""Script generation entrypoint.

By default, routes to the new ScenarioAgent (research-backed plan-then-generate).
Set USE_LEGACY_SCRIPT=1 to use the original one-shot Gemini call.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

import config
from prompts.script_prompt import (
    build_system_prompt,
    THREE_MIN_TEMPLATE,
    SHORTFORM_TEMPLATE,
    REQUIRED_ACTS,
    _FORBIDDEN_WORDS,
)


class ScriptError(RuntimeError):
    pass


def generate_script(
    sop: dict, duration: int, workspace: Optional[Path] = None
) -> list[dict]:
    """Generate scene list from SOP. Routes to ScenarioAgent unless USE_LEGACY_SCRIPT=1.

    If `workspace` is provided and the new agent path is used, the agent saves
    treatment.md there for human review.
    """
    if os.environ.get("USE_LEGACY_SCRIPT") == "1":
        return _generate_script_legacy(sop, duration)

    # Default: new agent-based path
    from pipeline.agents.scenario_agent import generate_script_v2
    return generate_script_v2(sop, duration, workspace=workspace)


# ─── Legacy implementation (kept for backwards compat / testing) ─────────────


def _generate_script_legacy(sop: dict, duration: int) -> list[dict]:
    """Original one-shot Gemini call. Kept for fallback and existing tests."""
    equipment_type = sop.get("equipment_type") or ""
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    system_prompt = build_system_prompt(equipment_type)
    gen_config = types.GenerateContentConfig(system_instruction=system_prompt)

    if duration <= 30:
        user_prompt = SHORTFORM_TEMPLATE.format(sop_json=json.dumps(sop, ensure_ascii=False))
    else:
        scene_count = duration // 8
        user_prompt = THREE_MIN_TEMPLATE.format(
            sop_json=json.dumps(sop, ensure_ascii=False),
            scene_count=scene_count,
        )

    last_exc: Exception | None = None
    for attempt in range(config.MAX_RETRY + 1):
        try:
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=user_prompt,
                config=gen_config,
            )
            text = (response.text or "").strip()
            if not text:
                finish = getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "no_candidates"
                raise ScriptError(f"Gemini returned no content (finish_reason={finish})")
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            scenes = json.loads(text)
            _validate_scenes(scenes, equipment_type)
            return scenes
        except Exception as exc:
            last_exc = exc
            if attempt == config.MAX_RETRY:
                raise ScriptError(f"Script generation failed after {config.MAX_RETRY + 1} attempts: {exc}") from exc

    raise ScriptError(f"Script generation failed: {last_exc}") from last_exc


def _validate_scenes(scenes: list[dict], equipment_type: str) -> None:
    """Check 5-act coverage and forbidden words. Raises ScriptError on violation."""
    acts_found = {s.get("act", "") for s in scenes}
    missing = REQUIRED_ACTS - acts_found
    if missing:
        raise ScriptError(f"Missing required acts: {missing}. Retrying...")

    forbidden_lower = [w.lower() for w in _FORBIDDEN_WORDS]
    for scene in scenes:
        prompt_lower = scene.get("image_prompt", "").lower()
        for word in forbidden_lower:
            if word in prompt_lower:
                raise ScriptError(
                    f"Forbidden word '{word}' found in {scene.get('scene_id')} image_prompt. Retrying..."
                )
