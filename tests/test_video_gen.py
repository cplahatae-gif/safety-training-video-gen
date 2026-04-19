from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.video_gen import generate_videos
from models.scene_manifest import Scene, SceneManifest, SceneStatus


def _make_manifest_with_image(tmp_path: Path) -> tuple[SceneManifest, Path]:
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)
    (workspace / "clips").mkdir(parents=True)
    img_path = workspace / "images" / "S01.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    manifest = SceneManifest(
        sop_title="테스트", total_duration_sec=8,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                status=SceneStatus.image_ready,
                narration_ko="나레이션", image_prompt="construction",
                motion_prompt="slow pan", camera="wide", mood="tense",
            )
        ],
    )
    return manifest, workspace


def test_generate_videos_downloads_and_updates_status(tmp_path, monkeypatch):
    manifest, workspace = _make_manifest_with_image(tmp_path)
    monkeypatch.setenv("FORCE_RUN", "1")
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100

    fake_file = MagicMock()
    fake_file.read.return_value = fake_mp4

    with patch("pipeline.video_gen.replicate.run") as mock_run:
        mock_run.return_value = fake_file

        updated = generate_videos(manifest=manifest, workspace=workspace)

    clip_path = workspace / "clips" / "S01.mp4"
    assert clip_path.exists()
    assert clip_path.read_bytes() == fake_mp4
    assert updated.scenes[0].status == SceneStatus.clip_ready


def test_generate_videos_skips_scene_after_two_failures(tmp_path, monkeypatch):
    manifest, workspace = _make_manifest_with_image(tmp_path)
    monkeypatch.setenv("FORCE_RUN", "1")

    with patch("pipeline.video_gen.replicate.run", side_effect=RuntimeError("Kling error")):
        updated = generate_videos(manifest=manifest, workspace=workspace)

    assert updated.scenes[0].status == SceneStatus.skipped
