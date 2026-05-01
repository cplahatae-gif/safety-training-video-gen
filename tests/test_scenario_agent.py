"""Tests for ScenarioAgent (Phase A)."""
import json
from unittest.mock import patch, MagicMock
import pytest

from pipeline.agents.scenario_agent import ScenarioAgent, generate_script_v2
from pipeline.agents.base_agent import CritiqueResult


# ─── Fixtures ────────────────────────────────────────────────────────────────

FAKE_BRIEF = (
    "Class 4 펄스 레이저는 0.5초 노출만으로도 망막을 영구 손상시킨다. "
    "연구원이 보호 안경을 잠시 벗고 작업하다 빔이 잘못된 방향으로 반사된다. "
    "정렬이 어긋난 거울 주변에 경고테이프가 설치되고 광학 부품에 검은 탄 흔적이 남는다. "
    "올바른 절차는 OD 5+ 보호 안경 착용 + <1mW 출력 + 빔 블록 사용이다. "
    "안전 절차 준수가 본인의 시력을 지키는 핵심이다."
)

FAKE_SCENES = [
    {"scene_id": "S01", "act": "hook",
     "narration_ko": "Class 4 펄스 레이저, 0.5초 노출로 망막 영구손상.",
     "image_prompt": "Optical lab, Class 4 laser system on optical breadboard, single continuous shot",
     "motion_prompt": "Slow zoom toward laser warning light",
     "camera": "low angle close-up", "mood": "tense", "on_screen_text": None},
    {"scene_id": "S02", "act": "conflict",
     "narration_ko": "보호 안경을 잠시 올리는 단 3초가 사고를 부른다.",
     "image_prompt": "Researcher in lab coat lifting safety goggles, single continuous shot",
     "motion_prompt": "Worker tilts goggles up briefly",
     "camera": "medium shot", "mood": "warning", "on_screen_text": "위험!"},
    {"scene_id": "S03", "act": "consequence",
     "narration_ko": "정렬 어긋난 거울, 광학 부품에 탄 자국.",
     "image_prompt": "Damaged optical component with burn marks, warning tape, single continuous shot",
     "motion_prompt": "Static slow pan",
     "camera": "close-up", "mood": "serious", "on_screen_text": "사고!"},
    {"scene_id": "S04", "act": "resolution",
     "narration_ko": "OD 5+ 보호 안경 착용, 출력 1mW 이하로 정렬.",
     "image_prompt": "Researcher in OD 5+ goggles aligning beam, single continuous shot",
     "motion_prompt": "Tracking shot following hands",
     "camera": "medium close-up", "mood": "instructive", "on_screen_text": "정확한 절차!"},
    {"scene_id": "S05", "act": "rules",
     "narration_ko": "보호 장비, 출력 제한, 빔 블록 — 매일의 시작.",
     "image_prompt": "Lab worker showing safety checklist, single continuous shot",
     "motion_prompt": "Slow zoom out", "camera": "wide shot",
     "mood": "empowering", "on_screen_text": "수칙 준수!"},
]

FAKE_CRITIQUE_PASS = {
    "specificity": 9, "act_coverage": 10, "equipment_lock": 9,
    "safety_accuracy": 9, "visual_clarity": 8, "issues": [],
}

FAKE_CRITIQUE_FAIL = {
    "specificity": 4, "act_coverage": 6, "equipment_lock": 5,
    "safety_accuracy": 5, "visual_clarity": 6,
    "issues": ["슬로건 위주", "구체 수치 부족"],
}


SAMPLE_SOP = {
    "sop_title": "Laser Safety SOP",
    "legal_basis": [],
    "hazards": [{"id": "H1", "name": "Eye damage", "severity": "permanent"}],
    "procedure_steps": [{"step": 1, "action": "Align beam", "key_rules": ["Wear OD 5+ goggles"]}],
    "target_audience": "researchers",
    "common_violations": [],
    "equipment_type": "Class 4 pulsed laser",
    "domain": "lab",
    "deep_extract": {
        "specific_hazards": ["0.5초 노출로 망막 영구손상"],
        "specific_procedures": ["OD 5+ 보호 안경 착용 후 <1mW 출력으로 정렬"],
        "equipment_details": ["Spectra Physics Spitfire, Class 4, 800nm"],
        "injury_types": ["망막 화상", "각막 영구손상"],
        "thresholds": ["MPE 0.5 J/cm²", "OD 5+"],
    },
}


def _mock_gemini_calls(brief: str, scenes_json: dict, critique_json: dict):
    """Build a side_effect for call_gemini_with_retry that returns brief, scenes, critique in order."""
    responses = [brief, json.dumps(scenes_json), json.dumps(critique_json)]
    idx = {"i": 0}

    def _fake(prompt: str, **kwargs):
        i = idx["i"]
        idx["i"] += 1
        if i >= len(responses):
            return responses[-1]
        return responses[i]

    return _fake


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_scenario_agent_passes_on_first_try():
    """Critique returns score >= 7 → no refine."""
    fake = _mock_gemini_calls(FAKE_BRIEF, FAKE_SCENES, FAKE_CRITIQUE_PASS)
    with patch("pipeline.agents.scenario_agent.call_gemini_with_retry", side_effect=fake), \
         patch("pipeline.agents.sop_extractor.enrich_sop", return_value=SAMPLE_SOP):
        scenes = generate_script_v2(SAMPLE_SOP, duration=30)

    assert isinstance(scenes, list)
    assert len(scenes) == 5
    assert scenes[0]["scene_id"] == "S01"
    assert scenes[0]["act"] == "hook"


def test_scenario_agent_refines_on_low_score():
    """Critique returns < 7 → refine cycle triggers."""
    # responses: brief, scenes_v1, critique_fail, scenes_v2, critique_pass
    responses = [
        FAKE_BRIEF,
        json.dumps(FAKE_SCENES),
        json.dumps(FAKE_CRITIQUE_FAIL),
        json.dumps(FAKE_SCENES),  # refined
        json.dumps(FAKE_CRITIQUE_PASS),
    ]
    idx = {"i": 0}

    def _fake(prompt, **kwargs):
        i = idx["i"]
        idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    with patch("pipeline.agents.scenario_agent.call_gemini_with_retry", side_effect=_fake), \
         patch("pipeline.agents.sop_extractor.enrich_sop", return_value=SAMPLE_SOP):
        scenes = generate_script_v2(SAMPLE_SOP, duration=30)

    # Should have called Gemini at least 4 times: brief + scenes_v1 + critique + scenes_refined (+ critique optional)
    assert idx["i"] >= 4
    assert len(scenes) == 5


def test_scenario_agent_deterministic_check_catches_forbidden_word():
    """If image_prompt contains a forbidden word, score gets penalized."""
    bad_scenes = [dict(s) for s in FAKE_SCENES]
    bad_scenes[0]["image_prompt"] = "split screen showing two views"

    responses = [
        FAKE_BRIEF,
        json.dumps(bad_scenes),
        json.dumps(FAKE_CRITIQUE_PASS),  # Gemini says OK but deterministic check catches
        json.dumps(FAKE_SCENES),  # refined
        json.dumps(FAKE_CRITIQUE_PASS),
    ]
    idx = {"i": 0}

    def _fake(prompt, **kwargs):
        i = idx["i"]
        idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    with patch("pipeline.agents.scenario_agent.call_gemini_with_retry", side_effect=_fake), \
         patch("pipeline.agents.sop_extractor.enrich_sop", return_value=SAMPLE_SOP):
        scenes = generate_script_v2(SAMPLE_SOP, duration=30)

    # Must have refined (called more than initial 3 times)
    assert idx["i"] >= 4
    # Final scenes should not have forbidden word
    assert "split screen" not in scenes[0]["image_prompt"].lower()


def test_critique_result_score_calculation():
    """CritiqueResult averages numeric fields when 'score' missing."""
    result = CritiqueResult.from_dict({
        "specificity": 8, "act_coverage": 9, "equipment_lock": 7,
        "safety_accuracy": 8, "visual_clarity": 9, "issues": []
    }, threshold=7.0)
    assert result.score == pytest.approx(8.2)
    assert result.passed is True


def test_critique_result_below_threshold():
    """Passed = False when score < threshold."""
    result = CritiqueResult.from_dict({"score": 5.0, "issues": ["bad"]}, threshold=7.0)
    assert result.passed is False
    assert "bad" in result.issues


def test_legacy_path_still_works(monkeypatch, sample_sop):
    """USE_LEGACY_SCRIPT=1 should bypass ScenarioAgent."""
    from pipeline.script_gen import generate_script

    monkeypatch.setenv("USE_LEGACY_SCRIPT", "1")
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("pipeline.script_gen.genai.Client", return_value=mock_client):
        scenes = generate_script(sop=sample_sop, duration=180)

    assert len(scenes) == 5
    # Legacy uses single Gemini call, not the agent's multi-call pattern
    assert mock_client.models.generate_content.call_count == 1
