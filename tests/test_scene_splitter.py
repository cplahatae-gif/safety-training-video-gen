import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from pipeline.scene_splitter import split_scenes
from models.scene_manifest import SceneStatus

FAKE_SCRIPT = [
    {
        "scene_id": "S01", "act": "hook",
        "narration_ko": "안전모를 착용하세요.",
        "image_prompt": "construction site", "motion_prompt": "pan left",
        "camera": "wide", "mood": "calm", "on_screen_text": None,
    },
    {
        "scene_id": "S02", "act": "conflict",
        "narration_ko": "아웃리거를 완전히 전개하지 않으면 장비가 전도될 수 있습니다. 반드시 확인하세요.",
        "image_prompt": "truck tilting", "motion_prompt": "tilt slow",
        "camera": "low angle", "mood": "tense", "on_screen_text": None,
    },
]


def test_split_scenes_creates_manifest_and_audio(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("pipeline.scene_splitter.synthesize") as mock_tts:
        mock_tts.side_effect = [
            (b"AUDIO01", 5.0),
            (b"AUDIO02", 12.5),
        ]
        with patch("pipeline.scene_splitter._split_audio_file") as mock_split:
            manifest = split_scenes(
                script=FAKE_SCRIPT,
                workspace=workspace,
                video_style="hybrid",
                sop_title="테스트 SOP",
                duration=180,
            )

    manifest_path = workspace / "manifest.json"
    assert manifest_path.exists()
    scene_ids = [s.scene_id for s in manifest.scenes]
    assert "S01" in scene_ids
    assert "S02a" in scene_ids
    assert "S02b" in scene_ids
    assert "S02" not in scene_ids
    assert manifest.tts_provider == "google"
    assert manifest.tts_voice is not None
    assert mock_split.call_count == 2
    calls = mock_split.call_args_list
    assert calls[0].kwargs["start"] == 0
    assert calls[0].kwargs["length"] == 10
    assert calls[1].kwargs["start"] == 10
    assert calls[1].kwargs["length"] is None


def test_split_scenes_no_subsplit_needed(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    single_scene = [FAKE_SCRIPT[0]]

    with patch("pipeline.scene_splitter.synthesize") as mock_tts:
        mock_tts.return_value = (b"AUDIO", 5.0)
        manifest = split_scenes(
            script=single_scene,
            workspace=workspace,
            video_style="hybrid",
            sop_title="테스트 SOP",
            duration=180,
        )

    assert len(manifest.scenes) == 1
    assert manifest.scenes[0].duration_sec == math.ceil(5.0)


def test_split_scenes_empty_narration_skips_tts_and_writes_silence(tmp_path):
    """When narration_ko is empty, TTS is skipped and a silent wav placeholder is written.
    The scene's duration_sec field on the script is used directly.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    silent_script = [
        {
            "scene_id": "S01", "act": "hook", "duration_sec": 6,
            "narration_ko": "",  # explicitly empty
            "image_prompt": "lab", "motion_prompt": "static",
            "camera": "wide", "mood": "tense", "on_screen_text": None,
            "bgm_keywords": ["tense low drone", "ticking clock"],
        },
    ]

    with patch("pipeline.scene_splitter.synthesize") as mock_tts, \
         patch("pipeline.scene_splitter._write_silent_wav") as mock_silent:
        manifest = split_scenes(
            script=silent_script,
            workspace=workspace,
            video_style="shortform",
            sop_title="테스트 SOP",
            duration=30,
        )

    # TTS should NOT be called when narration is empty
    assert mock_tts.call_count == 0
    # Silent wav should be written instead
    assert mock_silent.call_count == 1
    # Scene takes its duration from the script's duration_sec
    assert len(manifest.scenes) == 1
    assert manifest.scenes[0].duration_sec == 6
    # bgm_keywords flow through to the Scene model
    assert manifest.scenes[0].bgm_keywords == ["tense low drone", "ticking clock"]
