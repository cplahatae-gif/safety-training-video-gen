from __future__ import annotations
import json

from google import genai
from google.genai import types

import config
from prompts.script_prompt import SYSTEM_PROMPT, THREE_MIN_TEMPLATE, SHORTFORM_TEMPLATE


def generate_script(sop: dict, duration: int) -> list[dict]:
    """Call Gemini to generate a list of scene dicts from SOP JSON."""
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    gen_config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)

    if duration <= 30:
        user_prompt = SHORTFORM_TEMPLATE.format(sop_json=json.dumps(sop, ensure_ascii=False))
    else:
        scene_count = duration // 8
        user_prompt = THREE_MIN_TEMPLATE.format(
            sop_json=json.dumps(sop, ensure_ascii=False),
            scene_count=scene_count,
        )

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
                raise RuntimeError(f"Gemini returned no content (finish_reason={finish})")
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                raise RuntimeError(f"Script generation failed: {exc}") from exc
