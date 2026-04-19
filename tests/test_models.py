import pytest
from models.scene_manifest import Scene, SceneManifest, SceneStatus, SopJson

def test_scene_status_lifecycle():
    scene = Scene(
        scene_id="S01", act="hook", duration_sec=8,
        narration_ko="테스트입니다.",
        image_prompt="Korean construction site",
        motion_prompt="slow pan left",
        camera="wide shot", mood="tense"
    )
    assert scene.status == SceneStatus.pending
    assert scene.on_screen_text is None

def test_scene_manifest_round_trip():
    manifest = SceneManifest(
        sop_title="테스트 SOP", total_duration_sec=8,
        video_style="hybrid", tts_provider="google",
        tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                narration_ko="나레이션", image_prompt="prompt",
                motion_prompt="motion", camera="wide", mood="tense"
            )
        ]
    )
    data = manifest.model_dump()
    restored = SceneManifest.model_validate(data)
    assert restored.sop_title == "테스트 SOP"
    assert restored.scenes[0].status == SceneStatus.pending

def test_sop_json_validates():
    sop = SopJson(
        sop_title="테스트", legal_basis=[], hazards=[],
        procedure_steps=[{"step": 1, "action": "점검", "key_rules": []}],
        target_audience="작업자", common_violations=[]
    )
    assert sop.sop_title == "테스트"
