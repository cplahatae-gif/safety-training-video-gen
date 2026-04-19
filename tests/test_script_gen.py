import json
from unittest.mock import MagicMock, patch
import pytest
import google.generativeai as genai
from pipeline.script_gen import generate_script

FAKE_SCENES = [
    {
        "scene_id": "S01", "act": "hook",
        "narration_ko": "아웃리거를 전개하지 않으면 이런 일이 생깁니다.",
        "image_prompt": "aerial work platform truck tilting",
        "motion_prompt": "truck tilts slowly",
        "camera": "low angle", "mood": "tense", "on_screen_text": None
    }
]


def test_generate_script_3min_returns_scene_list(sample_sop):
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    with patch("pipeline.script_gen.genai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model

        scenes = generate_script(sop=sample_sop, duration=180)

    assert isinstance(scenes, list)
    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == "S01"
    assert "narration_ko" in scenes[0]
    assert "image_prompt" in scenes[0]


def test_generate_script_30sec_uses_shortform_template(sample_sop):
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    with patch("pipeline.script_gen.genai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model

        scenes = generate_script(sop=sample_sop, duration=30)
        call_args = mock_model.generate_content.call_args

    user_content = call_args[0][0]
    assert "30초" in user_content or "shortform" in user_content.lower()
