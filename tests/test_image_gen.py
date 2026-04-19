import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.image_gen import generate_images
from models.scene_manifest import Scene, SceneManifest, SceneStatus


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


def test_generate_images_skips_scene_after_two_failures(tmp_path):
    manifest = _make_manifest(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    with patch("pipeline.image_gen.replicate.run", side_effect=RuntimeError("API error")):
        updated = generate_images(manifest=manifest, workspace=workspace)

    assert updated.scenes[0].status == SceneStatus.skipped
