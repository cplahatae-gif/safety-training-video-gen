import json
from unittest.mock import MagicMock, patch
import pytest
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


def _mock_client():
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    return mock_client


def test_generate_script_3min_returns_scene_list(sample_sop):
    mock_client = _mock_client()
    with patch("pipeline.script_gen.genai.Client", return_value=mock_client):
        scenes = generate_script(sop=sample_sop, duration=180)

    assert isinstance(scenes, list)
    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == "S01"
    assert "narration_ko" in scenes[0]
    assert "image_prompt" in scenes[0]


def test_generate_script_30sec_uses_shortform_template(sample_sop):
    mock_client = _mock_client()
    with patch("pipeline.script_gen.genai.Client", return_value=mock_client):
        generate_script(sop=sample_sop, duration=30)
        call_kwargs = mock_client.models.generate_content.call_args.kwargs

    user_content = call_kwargs["contents"]
    assert "30초" in user_content or "shortform" in user_content.lower()
