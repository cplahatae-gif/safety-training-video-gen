from __future__ import annotations
import json

import google.generativeai as genai

import config
from prompts.script_prompt import SYSTEM_PROMPT, THREE_MIN_TEMPLATE, SHORTFORM_TEMPLATE


def generate_script(sop: dict, duration: int) -> list[dict]:
    """Call Gemini to generate a list of scene dicts from SOP JSON."""
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )

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
            response = model.generate_content(user_prompt)
            if not response.candidates or not response.candidates[0].content.parts:
                finish = getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "no_candidates"
                raise RuntimeError(f"Gemini returned no content (finish_reason={finish})")
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                raise RuntimeError(f"Script generation failed: {exc}") from exc
