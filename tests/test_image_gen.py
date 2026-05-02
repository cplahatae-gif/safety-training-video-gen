import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.image_gen import generate_images
from models.scene_manifest import Scene, SceneManifest, SceneStatus


_PASSING_CRITIQUE = {
    "anatomy": 9, "domain_match": 9, "no_split_screen": 10,
    "equipment_match": 9, "composition": 9,
    "main_issue": None, "retry_hint": None,
}


@pytest.fixture(autouse=True)
def _disable_character_sheet_by_default(monkeypatch, request):
    """Default: tests skip character sheet (legacy ref path).
    Tests that explicitly want sheet behavior should override with --override-ini or remove DISABLE_CHARACTER_SHEET.
    """
    if "use_sheet" in request.keywords:
        return  # marker overrides the default
    monkeypatch.setenv("DISABLE_CHARACTER_SHEET", "1")


@pytest.fixture(autouse=True)
def _mock_image_agent_gemini(request):
    """Mock the ImageAgent's Gemini Vision so tests don't hit the real API.

    Returns a passing critique by default. Tests that need a different
    critique result should patch `pipeline.agents.image_agent.gemini_client`
    themselves (the inner patch wins).
    """
    if "no_image_agent_gemini_mock" in request.keywords:
        yield
        return
    fake_response = MagicMock()
    fake_response.text = json.dumps(_PASSING_CRITIQUE)
    with patch("pipeline.agents.image_agent.gemini_client") as mc:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mc.return_value = mock_client
        yield


def _make_manifest(tmp_path: Path) -> SceneManifest:
    return SceneManifest(
        sop_title="테스트", total_duration_sec=8,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                status=SceneStatus.audio_ready,
                narration_ko="나레이션",
                image_prompt="Korean construction site, worker",
                motion_prompt="pan left", camera="wide", mood="tense",
            )
        ],
    )


def test_generate_images_saves_png_and_updates_status(tmp_path):
    manifest = _make_manifest(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.image_gen.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]

        updated = generate_images(manifest=manifest, workspace=workspace)

    img_path = workspace / "images" / "S01.png"
    assert img_path.exists()
    assert img_path.read_bytes() == fake_png
    assert updated.scenes[0].status == SceneStatus.image_ready


def test_generate_images_uses_ref_model_for_second_scene(tmp_path, monkeypatch):
    """Legacy path: first scene uses base model and saves _reference.png; second uses REF_IMAGE_MODEL.

    Sets DISABLE_CHARACTER_SHEET=1 to bypass the new CharacterAgent path.
    """
    monkeypatch.setenv("DISABLE_CHARACTER_SHEET", "1")
    manifest = SceneManifest(
        sop_title="테스트", total_duration_sec=14,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=7,
                status=SceneStatus.audio_ready,
                narration_ko="씬 1", image_prompt="worker at site",
                motion_prompt="pan", camera="wide", mood="calm",
            ),
            Scene(
                scene_id="S02", act="conflict", duration_sec=7,
                status=SceneStatus.audio_ready,
                narration_ko="씬 2", image_prompt="truck tilting",
                motion_prompt="zoom", camera="close", mood="tense",
            ),
        ],
    )
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.image_gen.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]
        import config as _cfg
        with patch.object(_cfg, "REF_IMAGE_MODEL", "black-forest-labs/flux-1.1-pro"):
            updated = generate_images(manifest=manifest, workspace=workspace)

    assert (workspace / "images" / "_reference.png").exists()
    assert (workspace / "images" / "S01.png").exists()
    assert (workspace / "images" / "S02.png").exists()
    assert updated.scenes[0].status == SceneStatus.image_ready
    assert updated.scenes[1].status == SceneStatus.image_ready
    # First call: base model for S01/_reference; second call: ref model for S02
    calls = mock_run.call_args_list
    assert calls[0][0][0] == _cfg.DEFAULT_IMAGE_MODEL
    assert calls[1][0][0] == "black-forest-labs/flux-1.1-pro"


@pytest.mark.use_sheet
def test_generate_images_uses_character_sheet_when_enabled(tmp_path):
    """New path: CharacterAgent generates sheet, scenes use sheet poses as references."""
    manifest = SceneManifest(
        sop_title="테스트", total_duration_sec=10,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=5,
                status=SceneStatus.audio_ready,
                narration_ko="씬 1", image_prompt="lab interior",
                motion_prompt="pan", camera="wide", mood="calm",
            ),
            Scene(
                scene_id="S02", act="resolution", duration_sec=5,
                status=SceneStatus.audio_ready,
                narration_ko="씬 2", image_prompt="researcher aligning",
                motion_prompt="track", camera="close", mood="instructive",
            ),
        ],
    )
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.image_gen.replicate.run") as mock_run, \
         patch("pipeline.agents.character_agent.replicate.run") as mock_sheet_run:
        mock_run.return_value = [fake_file]
        mock_sheet_run.return_value = [fake_file]
        updated = generate_images(manifest=manifest, workspace=workspace, domain="lab")

    # Character sheet directory should exist
    assert (workspace / "character_sheet").exists()
    # Scene images should exist
    assert (workspace / "images" / "S01.png").exists()
    assert (workspace / "images" / "S02.png").exists()
    # Both scenes should have image_ready status
    assert updated.scenes[0].status == SceneStatus.image_ready
    assert updated.scenes[1].status == SceneStatus.image_ready


def test_generate_images_skips_scene_after_two_failures(tmp_path):
    manifest = _make_manifest(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    with patch("pipeline.image_gen.replicate.run", side_effect=RuntimeError("API error")):
        updated = generate_images(manifest=manifest, workspace=workspace)

    assert updated.scenes[0].status == SceneStatus.skipped
