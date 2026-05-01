import json
import os
from unittest.mock import MagicMock, patch
import pytest
from pipeline.script_gen import generate_script


@pytest.fixture(autouse=True)
def use_legacy_script(monkeypatch):
    """Force legacy one-shot path for these tests; ScenarioAgent has its own test file."""
    monkeypatch.setenv("USE_LEGACY_SCRIPT", "1")

FAKE_SCENES = [
    {
        "scene_id": "S01", "act": "hook",
        "narration_ko": "아웃리거를 전개하지 않으면 이런 일이 생깁니다.",
        "image_prompt": "aerial work platform truck tilting",
        "motion_prompt": "truck tilts slowly",
        "camera": "low angle", "mood": "tense", "on_screen_text": None,
    },
    {
        "scene_id": "S02", "act": "conflict",
        "narration_ko": "아웃리거 미전개 시 전도 위험이 있습니다.",
        "image_prompt": "truck leaning on uneven ground",
        "motion_prompt": "camera pans slowly",
        "camera": "wide", "mood": "tense", "on_screen_text": None,
    },
    {
        "scene_id": "S03", "act": "consequence",
        "narration_ko": "장비가 전도되면 중대 재해가 발생합니다.",
        "image_prompt": "warning tape around tilted truck",
        "motion_prompt": "static shot",
        "camera": "medium", "mood": "serious", "on_screen_text": None,
    },
    {
        "scene_id": "S04", "act": "resolution",
        "narration_ko": "아웃리거를 완전히 전개하고 수평을 확인합니다.",
        "image_prompt": "worker extending outriggers fully",
        "motion_prompt": "close-up of outrigger extension",
        "camera": "close", "mood": "calm", "on_screen_text": "아웃리거 완전 전개",
    },
    {
        "scene_id": "S05", "act": "rules",
        "narration_ko": "아웃리거 전개는 작업 전 필수 점검 항목입니다.",
        "image_prompt": "checklist with outrigger checked",
        "motion_prompt": "zoom in on checklist",
        "camera": "close", "mood": "informative", "on_screen_text": "작업 전 필수 확인",
    },
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
    assert len(scenes) == 5
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
